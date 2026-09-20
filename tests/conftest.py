"""Shared validation-test process setup."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/ansible"


def pytest_configure(config: Any) -> None:
    """Keep pytest and its descendants inside the non-live Ansible boundary."""
    os.environ["ANSIBLE_INVENTORY"] = str(FIXTURE_ROOT / "inventory.yml")
    os.environ["ANSIBLE_VAULT_PASSWORD_FILE"] = str(FIXTURE_ROOT / "vault-pass")

    # Give each xdist worker an independent Ansible fact-cache directory.
    workerinput = getattr(config, "workerinput", None)
    cache_root = os.environ.get("ANSIBLE_CACHE_PLUGIN_CONNECTION")
    if workerinput is None or not cache_root:
        return

    worker_cache = Path(cache_root) / "pytest-workers" / workerinput["workerid"]
    worker_cache.mkdir(parents=True, exist_ok=True)
    os.environ["ANSIBLE_CACHE_PLUGIN_CONNECTION"] = str(worker_cache)
