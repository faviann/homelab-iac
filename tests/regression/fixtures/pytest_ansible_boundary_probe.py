"""Probe the Ansible environment inherited by a subprocess under pytest."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/ansible"


def test_run_sh_inherits_the_pytest_fixture_boundary() -> None:
    result = subprocess.run(
        [str(REPO_ROOT / "run.sh"), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    capture = json.loads(Path(os.environ["PYTEST_BOUNDARY_CAPTURE"]).read_text())
    assert capture == {
        "inventory": str(FIXTURE_ROOT / "inventory.yml"),
        "vault_password_file": str(FIXTURE_ROOT / "vault-pass"),
    }
