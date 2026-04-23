#!/usr/bin/env python3
"""Regression test for workstation baseline GitHub key population."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SUCCESS_PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "workstation_baseline_github_keys_test.yml"
EMPTY_PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "workstation_baseline_empty_github_keys_test.yml"
ANSIBLE_PLAYBOOK = REPO_ROOT / ".ansible" / "venv" / "bin" / "ansible-playbook"


def run_playbook(playbook: Path, temp_root: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ANSIBLE_PLAYBOOK), str(playbook), "-f", "1", "-e", f"temp_root={temp_root}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def main() -> int:
    if not ANSIBLE_PLAYBOOK.exists():
        print(f"missing ansible-playbook at {ANSIBLE_PLAYBOOK}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="workstation-baseline-github-keys-success-") as temp_root:
        success = run_playbook(SUCCESS_PLAYBOOK, temp_root)

    success_output = f"{success.stdout}\n{success.stderr}"
    if success.returncode != 0:
        print("success playbook failed unexpectedly", file=sys.stderr)
        print(success_output, file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="workstation-baseline-github-keys-empty-") as temp_root:
        empty = run_playbook(EMPTY_PLAYBOOK, temp_root)

    empty_output = f"{empty.stdout}\n{empty.stderr}"
    if empty.returncode == 0:
        print("empty-key playbook succeeded unexpectedly", file=sys.stderr)
        print(empty_output, file=sys.stderr)
        return 1

    markers = ["GitHub", "returned no SSH keys", "workstation_github_users"]
    missing = [marker for marker in markers if marker not in empty_output]
    if missing:
        print(f"empty-key playbook output missed expected fragments: {missing}", file=sys.stderr)
        print(empty_output, file=sys.stderr)
        return 1

    print("ok: workstation baseline GitHub keys succeed when present and fail clearly when empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
