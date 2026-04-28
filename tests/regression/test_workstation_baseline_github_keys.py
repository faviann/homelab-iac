#!/usr/bin/env python3
"""Regression test for workstation baseline inbound GitHub key population."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SUCCESS_PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "workstation_baseline_github_keys_test.yml"
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
    with tempfile.TemporaryDirectory(prefix="workstation-baseline-github-keys-success-") as temp_root:
        success = run_playbook(SUCCESS_PLAYBOOK, temp_root)

    success_output = f"{success.stdout}\n{success.stderr}"
    if success.returncode != 0:
        print("success playbook failed unexpectedly", file=sys.stderr)
        print(success_output, file=sys.stderr)
        return 1

    print("ok: workstation baseline writes inbound GitHub authorized_keys without outbound identity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
