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
VALIDATION_PREREQUISITE_INVENTORY = (
    FIXTURES / "lxc_validation_prerequisite_inventory.yml"
)
PLAYBOOK = FIXTURES / "lxc_fleet_preflight_test.yml"
STANDALONE_PLAYBOOK = FIXTURES / "lxc_standalone_validation_test.yml"
MISSING_HOSTNAME_PLAYBOOK = FIXTURES / "lxc_fleet_missing_hostname_test.yml"
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


def run_case(limit: str, *, check_mode: bool = False) -> bool:
    env = os.environ.copy()
    env["ANSIBLE_VAULT_PASSWORD_FILE"] = str(
        Path.home() / ".ansible" / "vault-pass"
    )
    command = [
        *ANSIBLE_PLAYBOOK,
        "-i",
        str(INVENTORY),
        str(PLAYBOOK),
        "--limit",
        limit,
    ]
    if check_mode:
        command.append("--check")
    proc = subprocess.run(
        command,
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
    cases = (
        "target_a,target_b",
        "target_conflict",
        "hostname_conflict",
        "access_target",
    )
    if not all(run_case(case) for case in cases):
        return 1
    if not run_case("target_a,target_b", check_mode=True):
        return 1

    missing_hostname = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(INVENTORY),
            str(MISSING_HOSTNAME_PLAYBOOK),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if missing_hostname.returncode != 0:
        print("incomplete hostname reservations were not aggregated", file=sys.stderr)
        print(f"{missing_hostname.stdout}\n{missing_hostname.stderr}", file=sys.stderr)
        return 1

    validation_tasks = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(INVENTORY),
            "site.yml",
            "--list-tasks",
            "--tags",
            "validation",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    normal_tasks = subprocess.run(
        [*ANSIBLE_PLAYBOOK, "-i", str(INVENTORY), "site.yml", "--list-tasks"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if (
        validation_tasks.returncode != 0
        or "Run aggregate standalone lifecycle validation" not in validation_tasks.stdout
        or normal_tasks.returncode != 0
        or "Run aggregate standalone lifecycle validation" in normal_tasks.stdout
        or "Compile desired LXC specification" not in normal_tasks.stdout
    ):
        print("site.yml validation tag routing is incorrect", file=sys.stderr)
        print(f"validation route:\n{validation_tasks.stdout}\n{validation_tasks.stderr}", file=sys.stderr)
        print(f"normal route:\n{normal_tasks.stdout}\n{normal_tasks.stderr}", file=sys.stderr)
        return 1

    missing_domain = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(VALIDATION_PREREQUISITE_INVENTORY),
            "site.yml",
            "--tags",
            "validation",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    missing_domain_output = f"{missing_domain.stdout}\n{missing_domain.stderr}"
    if (
        missing_domain.returncode == 0
        or "missing `default_domain`" not in missing_domain_output
        or "missing_domain" not in missing_domain_output
    ):
        print("site validation did not reject missing default_domain", file=sys.stderr)
        print(missing_domain_output, file=sys.stderr)
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
