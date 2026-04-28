#!/usr/bin/env python3
"""Opt-in probe for multiprocessing primitives in the Codex sandbox.

Run with:
EXPECT_SANDBOX_MULTIPROCESSING_PERMISSIONERROR=1 uv run --locked pytest \
    tests/regression/test_sandbox_multiprocessing_primitives.py
"""

from __future__ import annotations

import errno
import multiprocessing as mp
import os

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("EXPECT_SANDBOX_MULTIPROCESSING_PERMISSIONERROR") != "1",
    reason="environment-specific sandbox probe; opt in explicitly",
)


@pytest.mark.parametrize(
    ("name", "factory"),
    [
        ("Queue", mp.Queue),
        ("SimpleQueue", mp.SimpleQueue),
        ("Lock", mp.Lock),
        ("Semaphore", mp.Semaphore),
    ],
)
def test_multiprocessing_primitives_fail_with_permission_error(name, factory) -> None:
    with pytest.raises(PermissionError) as exc_info:
        factory()

    assert exc_info.value.errno == errno.EACCES, name
