"""Verify the validation cache setup observed by pytest workers."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import pytest_configure


def test_pytest_configure_gives_workers_distinct_usable_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = (tmp_path / "ansible-cache").resolve()
    cache_paths = []
    for worker_id in ("gw0", "gw1"):
        monkeypatch.setenv("ANSIBLE_CACHE_PLUGIN_CONNECTION", str(cache_root))
        pytest_configure(SimpleNamespace(workerinput={"workerid": worker_id}))

        cache_path = Path(os.environ["ANSIBLE_CACHE_PLUGIN_CONNECTION"]).resolve(
            strict=True
        )
        assert cache_path.is_dir()
        assert cache_path != cache_root
        assert cache_path.is_relative_to(cache_root)
        cache_paths.append(cache_path)

    assert cache_paths[0] != cache_paths[1]
