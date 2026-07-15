#!/usr/bin/env python3
"""Thin runner for the targeted LXC lifecycle planning barrier fixture."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures"
ASSETS = FIXTURES / "lxc_lifecycle_facade_assets"
INVENTORY = FIXTURES / "lxc_lifecycle_planning_barrier_inventory.yml"
PLAYBOOK = FIXTURES / "lxc_lifecycle_planning_barrier_test.yml"
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


def run_case(temp_root: Path, name: str, *arguments: str) -> bool:
    state_dir = temp_root / name
    state_dir.mkdir()
    for vmid, state in (
        (7101, "stopped"),
        (7102, "absent"),
        (7103, "stopped"),
        (7104, "absent"),
        (7105, "stopped"),
    ):
        (state_dir / f"{vmid}.state").write_text(state, encoding="utf-8")
        (state_dir / f"{vmid}.release").write_text("12", encoding="utf-8")
        (state_dir / f"{vmid}.events").write_text("", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{ASSETS / 'bin'}:{env['PATH']}"
    env["LIFECYCLE_TEST_STATE_DIR"] = str(state_dir)
    env["ANSIBLE_ROLES_PATH"] = os.pathsep.join(
        [str(ASSETS / "roles"), str(REPO_ROOT / "playbooks" / "roles")]
    )
    env["ANSIBLE_COLLECTIONS_PATH"] = os.pathsep.join(
        [str(ASSETS / "collections"), str(REPO_ROOT / "collections")]
    )
    proc = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(INVENTORY),
            str(PLAYBOOK),
            "-e",
            f"lifecycle_test_state_dir={state_dir}",
            "-e",
            f"lifecycle_test_case={name}",
            *arguments,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    expected_failure = name in {"barrier", "execution_failure", "compile_failure"}
    assertions_complete = f"lifecycle_case_assertions_complete={name}" in proc.stdout
    controlled_failure = (
        "Barrier fixture published every targeted result before returning" in proc.stdout
    )
    succeeded = (
        (proc.returncode != 0 and controlled_failure and assertions_complete)
        if expected_failure
        else proc.returncode == 0 and assertions_complete
    )
    if not succeeded:
        print(f"lifecycle planning barrier case {name!r} failed", file=sys.stderr)
        print(f"{proc.stdout}\n{proc.stderr}", file=sys.stderr)
        return False
    return True


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lxc-planning-barrier-") as temp_dir:
        temp_root = Path(temp_dir)
        cases = (
            run_case(
                temp_root,
                "barrier",
                "--limit",
                "barrier_valid,barrier_invalid",
            ),
            run_case(
                temp_root,
                "check",
                "--limit",
                "barrier_valid",
            ),
            run_case(
                temp_root,
                "limited",
                "--limit",
                "barrier_valid",
                "--check",
            ),
            run_case(
                temp_root,
                "execution_failure",
                "--limit",
                "barrier_valid,barrier_after_failure",
                "-e",
                "lifecycle_test_execution_failure_host=barrier_valid",
            ),
            run_case(
                temp_root,
                "compile_failure",
                "--limit",
                "barrier_valid,barrier_compile_invalid",
            ),
            run_case(
                temp_root,
                "self_skip",
                "--limit",
                "workstation",
            ),
            run_case(
                temp_root,
                "self_include",
                "--limit",
                "workstation",
                "-e",
                "proxmox_skip_self=false",
            ),
        )
        if not all(cases):
            return 1

    print("ok: lifecycle barrier covers limits, check mode, and fail-fast execution")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
