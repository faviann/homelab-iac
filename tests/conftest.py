"""Shared validation-test process setup."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def pytest_configure(config: Any) -> None:
    """Give each xdist worker an independent Ansible fact-cache directory."""
    workerinput = getattr(config, "workerinput", None)
    cache_root = os.environ.get("ANSIBLE_CACHE_PLUGIN_CONNECTION")
    if workerinput is None or not cache_root:
        return

    worker_cache = Path(cache_root) / "pytest-workers" / workerinput["workerid"]
    worker_cache.mkdir(parents=True, exist_ok=True)
    os.environ["ANSIBLE_CACHE_PLUGIN_CONNECTION"] = str(worker_cache)
