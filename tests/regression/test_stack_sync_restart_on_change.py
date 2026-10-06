#!/usr/bin/env python3
"""Regression test for recreating a stack service when a tracked file changes."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "stack_sync_restart_on_change.yml"


def test_stack_sync_restart_on_change() -> None:
    with tempfile.TemporaryDirectory(prefix="stack-sync-restart-") as temp_root:
        proc = subprocess.run(
            [*ansible_playbook_command(), str(PLAYBOOK), "-e", f"temp_root={temp_root}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
