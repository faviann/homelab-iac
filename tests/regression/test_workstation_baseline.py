#!/usr/bin/env python3
"""Regression tests for the normal workstation baseline role run."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from ansible_test_helper import ansible_playbook_command
from bitwarden_release_boundary import bitwarden_release_boundary


REPO_ROOT = Path(__file__).resolve().parents[2]
SUCCESS_PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "workstation_baseline_test.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command()


def run_playbook(
    playbook: Path,
    temp_root: str,
    *,
    digest_matches: bool = True,
) -> subprocess.CompletedProcess[str]:
    with bitwarden_release_boundary(digest_matches=digest_matches) as bitwarden_args:
        command = [
            *ANSIBLE_PLAYBOOK,
            str(playbook),
            "-f",
            "1",
            "-e",
            f"temp_root={temp_root}",
            *bitwarden_args,
        ]
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )


def test_workstation_baseline_normal_run() -> None:
    with tempfile.TemporaryDirectory(prefix="workstation-baseline-success-") as temp_root:
        success = run_playbook(SUCCESS_PLAYBOOK, temp_root)

    success_output = f"{success.stdout}\n{success.stderr}"
    assert success.returncode == 0, success_output


def test_workstation_baseline_rejects_bitwarden_archive_digest_mismatch() -> None:
    with tempfile.TemporaryDirectory(prefix="workstation-baseline-digest-") as temp_root:
        mismatch = run_playbook(SUCCESS_PLAYBOOK, temp_root, digest_matches=False)

    mismatch_output = f"{mismatch.stdout}\n{mismatch.stderr}"
    assert mismatch.returncode != 0, mismatch_output
    assert "Download Bitwarden CLI archive" in mismatch_output, mismatch_output
    assert "The checksum for" in mismatch_output, mismatch_output
    assert "did not match" in mismatch_output, mismatch_output
