"""A missing uv is reported as a machine prerequisite at each seam that runs it."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from vault_test_harness import run_vault_tty


REPO_ROOT = Path(__file__).resolve().parents[2]

# Programs a machine installation would reach for. Recording them proves the
# failure never turns into an install attempt.
INSTALLERS = ("curl", "sudo", "apt", "apt-get")

# An absolute interpreter keeps the shim runnable on the controlled PATH below.
RECORDING_SHIM = f'''#!{sys.executable}
import json, os, sys
from pathlib import Path

with Path(os.environ["UV_PREREQUISITE_LOG"]).open("a", encoding="utf-8") as log:
    log.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + "\\n")
'''

DIAGNOSTIC = "uv not found on PATH"


@pytest.fixture
def without_uv(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in INSTALLERS:
        shim = bin_dir / name
        shim.write_text(RECORDING_SHIM, encoding="utf-8")
        shim.chmod(0o755)
    # The ordinary commands the seams run before their uv check: dirname to find
    # the project, and stat and id for vault.sh set's source authorization.
    # PATH holds only these and the shims, so no host uv can be found.
    for name in ("dirname", "stat", "id"):
        (bin_dir / name).symlink_to(shutil.which(name))
    assert shutil.which("uv", path=str(bin_dir)) is None
    (tmp_path / "home").mkdir()
    # An authorized transfer source, so `vault.sh set` reaches its uv check.
    source = tmp_path / "source.txt"
    source.write_text("value\n", encoding="utf-8")
    source.chmod(0o600)
    return {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": str(bin_dir),
        "UV_PREREQUISITE_LOG": str(tmp_path / "installers.jsonl"),
    }


def run(env: dict[str, str], cwd: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(REPO_ROOT / command[0]), *command[1:]],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )


def assert_no_install(env: dict[str, str]) -> None:
    log = Path(env["UV_PREREQUISITE_LOG"])
    assert not log.exists(), log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(("setup.sh", "sync"), id="setup-sync"),
        pytest.param(("validate.sh",), id="validate"),
        pytest.param(("run.sh",), id="live-boundary-before-lock"),
        pytest.param(("inspect.sh", "vars", "example-host"), id="inspect-vars"),
        pytest.param(("vault.sh", "check"), id="vault-check"),
        pytest.param(
            ("vault.sh", "set", "vault_example", "--from-file", "source.txt", "--create"),
            id="vault-set",
        ),
        pytest.param(("vault.sh", "rotate", "--dry-run"), id="vault-rotate-preflight"),
    ],
)
def test_missing_uv_is_reported_as_a_machine_prerequisite(
    without_uv: dict[str, str], tmp_path: Path, command: tuple[str, ...]
) -> None:
    result = run(without_uv, tmp_path, *command)

    assert result.returncode == 1, result.stdout + result.stderr
    assert f"{command[0]}: {DIAGNOSTIC}" in result.stderr
    assert "https://docs.astral.sh/uv/" in result.stderr
    assert "./setup.sh" not in result.stdout + result.stderr
    assert_no_install(without_uv)
    if command[0] == "run.sh":
        # The live boundary creates its lifecycle lock under ~/.ansible.
        assert list(Path(without_uv["HOME"]).iterdir()) == []


def test_interactive_vault_mutation_reports_missing_uv_once_it_has_a_tty(
    without_uv: dict[str, str],
) -> None:
    returncode, transcript = run_vault_tty(REPO_ROOT, without_uv, [], "configure")

    assert returncode == 1, transcript
    assert f"vault.sh: {DIAGNOSTIC}" in transcript
    assert "https://docs.astral.sh/uv/" in transcript
    assert_no_install(without_uv)


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(("setup.sh",), id="setup"),
        pytest.param(("validate.sh", "--bogus"), id="validate"),
        pytest.param(("inspect.sh", "vars", "--bogus"), id="inspect-vars"),
        pytest.param(("vault.sh", "set", "vault_example"), id="vault-set"),
    ],
)
def test_invalid_grammar_outranks_missing_uv(
    without_uv: dict[str, str], tmp_path: Path, command: tuple[str, ...]
) -> None:
    result = run(without_uv, tmp_path, *command)

    assert result.returncode == 2, result.stdout + result.stderr
    assert DIAGNOSTIC not in result.stderr
    assert_no_install(without_uv)
