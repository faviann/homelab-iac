#!/usr/bin/env python3
"""Regression test for overmind image-backed DbUp migrations."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "overmind_migrations_test.yml"
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="overmind-migrations-") as temp_root:
        success_root = Path(temp_root) / "success"
        failure_cleanup_root = Path(temp_root) / "failure-cleanup"
        success_root.mkdir()
        failure_cleanup_root.mkdir()

        success = subprocess.run(
            [*ANSIBLE_PLAYBOOK, str(PLAYBOOK), "-e", f"temp_root={success_root}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        success_output = f"{success.stdout}\n{success.stderr}"

        failure_cleanup = subprocess.run(
            [
                *ANSIBLE_PLAYBOOK,
                str(PLAYBOOK),
                "-e",
                f"temp_root={failure_cleanup_root}",
                "-e",
                "overmind_mock_verify_schema_fails=true",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        failure_cleanup_output = f"{failure_cleanup.stdout}\n{failure_cleanup.stderr}"

    if success.returncode != 0:
        print("success playbook failed unexpectedly", file=sys.stderr)
        print(success_output, file=sys.stderr)
        return 1

    if failure_cleanup.returncode != 0:
        print("failure cleanup playbook failed unexpectedly", file=sys.stderr)
        print(failure_cleanup_output, file=sys.stderr)
        return 1

    print("ok: overmind migrations verify disposable schema before production")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
