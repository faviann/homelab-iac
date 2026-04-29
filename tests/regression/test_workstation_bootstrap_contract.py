#!/usr/bin/env python3
"""Regression test for workstation unattended bootstrap contract."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_workstation_bootstrap_contract() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "--locked",
            "ansible-playbook",
            "tests/regression/fixtures/workstation_bootstrap_contract.yml",
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout