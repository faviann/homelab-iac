"""Verify the validation cache setup observed by pytest workers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# Multiple test items make xdist exercise both configured workers.
@pytest.mark.parametrize("_probe", range(4))
def test_parallel_worker_uses_its_private_ansible_cache(_probe: int) -> None:
    cache_connection = os.environ.get("ANSIBLE_CACHE_PLUGIN_CONNECTION")
    if not cache_connection:
        pytest.skip("run through ./validate.sh to configure the validation cache")

    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    cache_path = Path(cache_connection)
    if worker_id is None:
        assert cache_path.parent.name != "pytest-workers"
        return

    assert cache_path.parent.name == "pytest-workers"
    assert cache_path.name == worker_id
    assert cache_path.is_dir()
