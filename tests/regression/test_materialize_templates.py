#!/usr/bin/env python3
"""Test that stack_sync_materialize.yml renders templates and copies static files correctly."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ansible_test_helper import ansible_playbook_command

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "stack_sync_materialize_test.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="stack-sync-materialize-") as temp_root:
        result = subprocess.run(
            [
                *ANSIBLE_PLAYBOOK,
                str(PLAYBOOK),
                "-e",
                f"temp_root={temp_root}",
                "-e",
                f"repo_root={REPO_ROOT}",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )

    if result.returncode != 0:
        print("playbook failed unexpectedly", file=sys.stderr)
        print(f"{result.stdout}\n{result.stderr}", file=sys.stderr)
        return 1

    print("ok: materialize preserves directory and exact stack-file metadata contracts")
    return 0


def test_materialize_templates() -> None:
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
