#!/usr/bin/env python3
"""Regression test for workstation first-login setup contract."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_workstation_first_login_setup_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="workstation-first-login-setup-") as temp_root:
        result = subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                "ansible-playbook",
                "tests/regression/fixtures/workstation_first_login_setup_contract.yml",
                "-e",
                f"temp_root={temp_root}",
            ],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    assert result.returncode == 0, result.stdout
