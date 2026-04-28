#!/usr/bin/env python3
"""Regression tests for workstation agent-state persistence links."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "regression" / "fixtures"
SUCCESS_PLAYBOOK = FIXTURE_ROOT / "workstation_agent_state_success.yml"
DISABLED_PLAYBOOK = FIXTURE_ROOT / "workstation_agent_state_disabled.yml"
CONFLICT_PLAYBOOK = FIXTURE_ROOT / "workstation_agent_state_conflict.yml"
IDEMPOTENCY_PLAYBOOK = FIXTURE_ROOT / "workstation_agent_state_idempotency.yml"
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


def run_playbook(playbook: Path, temp_root: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*ANSIBLE_PLAYBOOK, str(playbook), "-f", "1", "-e", f"temp_root={temp_root}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="workstation-agent-state-success-") as temp_root:
        success = run_playbook(SUCCESS_PLAYBOOK, temp_root)

    success_output = f"{success.stdout}\n{success.stderr}"
    if success.returncode != 0:
        print("success playbook failed unexpectedly", file=sys.stderr)
        print(success_output, file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="workstation-agent-state-disabled-") as temp_root:
        disabled = run_playbook(DISABLED_PLAYBOOK, temp_root)

    disabled_output = f"{disabled.stdout}\n{disabled.stderr}"
    if disabled.returncode != 0:
        print("disabled playbook failed unexpectedly", file=sys.stderr)
        print(disabled_output, file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="workstation-agent-state-conflict-") as temp_root:
        conflict = run_playbook(CONFLICT_PLAYBOOK, temp_root)

    conflict_output = f"{conflict.stdout}\n{conflict.stderr}"
    if conflict.returncode == 0:
        print("conflict playbook succeeded unexpectedly", file=sys.stderr)
        print(conflict_output, file=sys.stderr)
        return 1

    expected_markers = [
        "exists and is not the managed symlink",
        "Move or migrate it manually",
        ".claude",
    ]
    if not all(marker in conflict_output for marker in expected_markers):
        print("conflict failure did not explain the unsafe existing path", file=sys.stderr)
        print(conflict_output, file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="workstation-agent-state-idempotency-") as temp_root:
        first_idempotency = run_playbook(IDEMPOTENCY_PLAYBOOK, temp_root)
        second_idempotency = run_playbook(IDEMPOTENCY_PLAYBOOK, temp_root)

    first_idempotency_output = f"{first_idempotency.stdout}\n{first_idempotency.stderr}"
    if first_idempotency.returncode != 0:
        print("idempotency setup playbook failed unexpectedly", file=sys.stderr)
        print(first_idempotency_output, file=sys.stderr)
        return 1

    second_idempotency_output = f"{second_idempotency.stdout}\n{second_idempotency.stderr}"
    if second_idempotency.returncode != 0:
        print("idempotency verification playbook failed unexpectedly", file=sys.stderr)
        print(second_idempotency_output, file=sys.stderr)
        return 1

    if "changed=0" not in second_idempotency_output:
        print("second agent-state-only run was not idempotent", file=sys.stderr)
        print(second_idempotency_output, file=sys.stderr)
        return 1

    print("ok: workstation agent state links are managed safely")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())