"""Pin every pytest run in this checkout to the credential-free Ansible fixtures.

This file sits at the repository root so pytest loads it for any collected
path, including test trees outside ``tests/``. See
docs/adr/0008-enforce-non-live-validation-boundary.md.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


FIXTURE_ROOT = Path(__file__).resolve().parent / "tests/fixtures/ansible"
FIXTURE_ENVIRONMENT = {
    "ANSIBLE_INVENTORY": FIXTURE_ROOT / "inventory.yml",
    "ANSIBLE_VAULT_PASSWORD_FILE": FIXTURE_ROOT / "vault-pass",
}


def pytest_configure(config: pytest.Config) -> None:
    """Replace inherited operator values before collection starts."""
    for name, path in FIXTURE_ENVIRONMENT.items():
        if not path.is_file():
            raise pytest.UsageError(f"{name} fixture is missing: {path}")
        os.environ[name] = str(path)
