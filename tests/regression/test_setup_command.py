#!/usr/bin/env python3
"""Regression coverage for the ./setup.sh command facade.

`setup.sh` has one operation, `sync`, which delegates to `uv sync --locked`.
These tests observe the process, its exit status, and the work it delegates.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

# uv plus the programs a machine installation would reach for. Shimming them
# records any delegated work or install attempt without touching the package
# manager or the network. The ordinary commands the script itself runs are not
# delegation, so they stay unrecorded.
SHIMMED = ("uv", "curl", "sudo", "apt", "apt-get")

# An absolute interpreter keeps the shim runnable on the controlled PATH below.
RECORDING_SHIM = f'''#!{sys.executable}
import json, os, sys
from pathlib import Path

name = Path(sys.argv[0]).name
with Path(os.environ["SETUP_TEST_LOG"]).open("a", encoding="utf-8") as log:
    log.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
raise SystemExit(int(os.environ.get("SETUP_TEST_CHILD_STATUS", "0")))
'''

SYNC = ["uv", "sync", "--locked"]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A throwaway project root, so any filesystem write stays inside the test."""
    project = tmp_path / "project"
    (project / "scripts" / "lib").mkdir(parents=True)
    (project / "setup.sh").symlink_to(REPO_ROOT / "setup.sh")
    (project / "scripts" / "lib" / "uv-prerequisite.sh").symlink_to(
        REPO_ROOT / "scripts" / "lib" / "uv-prerequisite.sh"
    )
    return project


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in SHIMMED:
        shim = bin_dir / name
        shim.write_text(RECORDING_SHIM, encoding="utf-8")
        shim.chmod(0o755)
    # setup.sh runs only dirname, and cat for --help. PATH holds those and the
    # shims and nothing more, so a host uv is never the one found.
    for name in ("dirname", "cat"):
        (bin_dir / name).symlink_to(shutil.which(name))
    (tmp_path / "home").mkdir()

    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": str(bin_dir),
            "SETUP_TEST_LOG": str(tmp_path / "delegated.jsonl"),
        }
    )
    return environment


def run(project: Path, env: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(project / "setup.sh"), *arguments],
        cwd=project,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )


def delegated(env: dict[str, str]) -> list[list[str]]:
    log = Path(env["SETUP_TEST_LOG"])
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


# --- sync -----------------------------------------------------------------


def test_sync_runs_locked_synchronization_and_nothing_else(project, env) -> None:
    result = run(project, env, "sync")

    assert result.returncode == 0, result.stderr
    assert delegated(env) == [SYNC]


def test_sync_failure_is_not_reported_as_success(project, env) -> None:
    env["SETUP_TEST_CHILD_STATUS"] = "9"

    result = run(project, env, "sync")

    assert result.returncode == 1, result.stdout


# --- grammar --------------------------------------------------------------


def test_help_exits_zero_without_delegating(project, env) -> None:
    result = run(project, env, "--help")

    assert result.returncode == 0
    assert "sync" in result.stdout
    assert delegated(env) == []


@pytest.mark.parametrize(
    "arguments",
    [(), ("bogus",), ("--bogus",), ("sync", "extra"), ("--help", "extra")],
)
def test_missing_unknown_or_surplus_input_is_invalid_usage(
    project, env, arguments
) -> None:
    result = run(project, env, *arguments)

    assert result.returncode == 2
    assert delegated(env) == []
