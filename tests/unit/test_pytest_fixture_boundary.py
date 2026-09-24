"""Verify that pytest startup pins Ansible to the repository fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/ansible"
FIXTURE_ENVIRONMENT = {
    "ANSIBLE_INVENTORY": str(FIXTURE_ROOT / "inventory.yml"),
    "ANSIBLE_VAULT_PASSWORD_FILE": str(FIXTURE_ROOT / "vault-pass"),
}


def test_child_processes_inherit_fixture_environment() -> None:
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, os, sys; "
            "print(json.dumps({name: os.environ.get(name) for name in sys.argv[1:]}))",
            *FIXTURE_ENVIRONMENT,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(child.stdout) == FIXTURE_ENVIRONMENT


def test_pytest_startup_replaces_operator_environment(tmp_path: Path) -> None:
    # ./validate.sh already exports the fixtures, so only a pytest session that
    # starts from operator values shows whether the startup hook took effect.
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    for name in FIXTURE_ENVIRONMENT:
        sentinel = tmp_path / f"operator-{name.lower()}"
        sentinel.write_text("operator sentinel\n", encoding="utf-8")
        env[name] = str(sentinel)

    session = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            f"{__file__}::test_child_processes_inherit_fixture_environment",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert session.returncode == 0, session.stdout + session.stderr
