#!/usr/bin/env python3
"""Regression coverage for the ./setup.sh command facade.

`setup.sh` has one operation, `sync`, which delegates to `uv sync --locked`.
These tests observe the process, its exit status, its output, the child
commands it invokes, and the filesystem it leaves behind.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

# uv plus the programs a machine installation would reach for. Shimming them
# records any attempt without touching the package manager or the network.
SHIMMED = ("uv", "curl", "sudo", "apt", "apt-get")

RECORDING_SHIM = '''#!/usr/bin/env python3
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
    (tmp_path / "home").mkdir()

    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SETUP_TEST_LOG": str(tmp_path / "children.jsonl"),
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


def children(env: dict[str, str]) -> list[list[str]]:
    log = Path(env["SETUP_TEST_LOG"])
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def filesystem(root: Path) -> list[tuple[str, int]]:
    return sorted(
        (str(path.relative_to(root)), path.lstat().st_mode) for path in root.rglob("*")
    )


# --- sync -----------------------------------------------------------------


def test_sync_runs_locked_synchronization_and_nothing_else(project, env) -> None:
    result = run(project, env, "sync")

    assert result.returncode == 0, result.stderr
    assert children(env) == [SYNC]


def test_sync_failure_is_not_reported_as_success(project, env) -> None:
    env["SETUP_TEST_CHILD_STATUS"] = "9"

    result = run(project, env, "sync")

    assert result.returncode == 1, result.stdout


def test_sync_is_independently_repeatable(project, env) -> None:
    first = run(project, env, "sync")
    second = run(project, env, "sync")

    assert (first.returncode, second.returncode) == (0, 0), first.stderr
    assert second.stdout == first.stdout
    assert children(env) == [SYNC, SYNC]


def test_sync_without_uv_names_the_machine_prerequisite(project, env, tmp_path) -> None:
    (tmp_path / "bin" / "uv").unlink()
    # PATH still carries /usr/bin, so this case only means anything while no
    # real uv is reachable there.
    assert shutil.which("uv", path=env["PATH"]) is None

    result = run(project, env, "sync")

    assert result.returncode == 1
    assert "uv not found on PATH" in result.stderr
    assert "https://docs.astral.sh/uv/" in result.stderr
    assert "./setup.sh" not in result.stdout + result.stderr
    assert children(env) == []


# --- grammar --------------------------------------------------------------


def test_help_exits_zero_and_documents_only_sync(project, env) -> None:
    result = run(project, env, "--help")

    assert result.returncode == 0
    assert "sync" in result.stdout and "--help" in result.stdout
    assert "bootstrap" not in result.stdout
    assert children(env) == []


def test_bare_invocation_requires_an_explicit_operation(project, env, tmp_path) -> None:
    before = filesystem(tmp_path)

    result = run(project, env)

    assert result.returncode == 2
    assert result.stderr.startswith("setup.sh: an operation is required")
    assert children(env) == []
    assert filesystem(tmp_path) == before


@pytest.mark.parametrize(
    "arguments",
    [
        ("bootstrap",),
        ("bogus",),
        ("--bogus",),
        ("sync", "extra"),
        ("bootstrap", "extra"),
        ("--help", "extra"),
    ],
)
def test_retired_unknown_or_surplus_input_is_invalid_usage(
    project, env, tmp_path, arguments
) -> None:
    before = filesystem(tmp_path)

    result = run(project, env, *arguments)

    assert result.returncode == 2
    assert result.stderr.startswith("setup.sh: ")
    assert children(env) == []
    assert filesystem(tmp_path) == before
