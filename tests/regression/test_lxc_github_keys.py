#!/usr/bin/env python3
"""Regression tests for config/lxc_github_keys role."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "regression" / "fixtures"
MULTI_USER_PLAYBOOK = FIXTURE_ROOT / "lxc_github_keys_multi_user_dedup_test.yml"
EMPTY_KEYS_PLAYBOOK = FIXTURE_ROOT / "lxc_github_keys_empty_keys_test.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command()


def run_playbook(playbook: Path, temp_root: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*ANSIBLE_PLAYBOOK, str(playbook), "-f", "1", "-e", f"temp_root={temp_root}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def test_lxc_github_keys() -> None:
    with tempfile.TemporaryDirectory(prefix="lxc-github-keys-") as temp_root:
        multi = run_playbook(MULTI_USER_PLAYBOOK, temp_root)
        assert multi.returncode == 0, f"{multi.stdout}\n{multi.stderr}"

        empty_keys = run_playbook(EMPTY_KEYS_PLAYBOOK, temp_root)
        empty_keys_output = f"{empty_keys.stdout}\n{empty_keys.stderr}"
        assert empty_keys.returncode == 0, empty_keys_output
