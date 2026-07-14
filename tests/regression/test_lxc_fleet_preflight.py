#!/usr/bin/env python3
"""Thin runner for fleet preflight behavior through the lifecycle facade."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures"
INVENTORY = FIXTURES / "lxc_fleet_preflight_inventory.yml"
PLAYBOOK = FIXTURES / "lxc_fleet_preflight_test.yml"
STANDALONE_PLAYBOOK = FIXTURES / "lxc_standalone_validation_test.yml"
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


def run_case(limit: str) -> bool:
    env = os.environ.copy()
    env["ANSIBLE_VAULT_PASSWORD_FILE"] = str(
        Path.home() / ".ansible" / "vault-pass"
    )
    proc = subprocess.run(
        [*ANSIBLE_PLAYBOOK, "-i", str(INVENTORY), str(PLAYBOOK), "--limit", limit],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode == 0:
        return True

    print(f"fleet preflight case {limit!r} failed unexpectedly", file=sys.stderr)
    print(f"{proc.stdout}\n{proc.stderr}", file=sys.stderr)
    return False


def main() -> int:
    cases = ("target_a,target_b", "target_conflict", "access_target")
    if not all(run_case(case) for case in cases):
        return 1

    env = os.environ.copy()
    proc = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(INVENTORY),
            str(STANDALONE_PLAYBOOK),
            "--limit",
            "target_conflict,release_problem",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    aggregate_output = f"{proc.stdout}\n{proc.stderr}"
    aggregate_fragments = (
        "Standalone lifecycle validation found",
        "Target identity conflict",
        "VMID 5199",
        "Guest release observation is required",
        "release_problem",
    )
    if proc.returncode == 0 or not all(
        fragment in aggregate_output for fragment in aggregate_fragments
    ):
        print("standalone validation did not aggregate all problems", file=sys.stderr)
        print(aggregate_output, file=sys.stderr)
        return 1

    print("ok: fleet preflight shares observations and standalone validation aggregates problems")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
