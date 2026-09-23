"""Every public command path that runs uv reports a missing uv as a machine prerequisite."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


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

UV_COMMAND_PATHS = [
    ("setup.sh", "sync"),
    ("validate.sh",),
    ("validate.sh", "lint"),
    ("validate.sh", "lifecycle"),
    ("validate.sh", "tests"),
    ("validate.sh", "stack", "stacks/example/app"),
    ("run.sh",),
    ("run.sh", "provision"),
    ("run.sh", "configure"),
    ("recover.sh", "ssh-keys"),
    ("recover.sh", "proxmox-host-ssh"),
    ("inspect.sh", "credentials"),
    ("inspect.sh", "connectivity"),
    ("inspect.sh", "containers"),
    ("inspect.sh", "plan"),
    ("inspect.sh", "vars", "--graph"),
    ("inspect.sh", "vars", "example-host"),
    ("vault.sh", "check"),
    ("vault.sh", "configure"),
    ("vault.sh", "edit"),
    ("vault.sh", "set", "vault_example", "--from-file", "missing.txt", "--create"),
    ("vault.sh", "rotate"),
    ("vault.sh", "rotate", "--dry-run"),
]


@pytest.mark.parametrize("command", UV_COMMAND_PATHS, ids=" ".join)
def test_missing_uv_is_reported_before_any_effect(
    tmp_path: Path, command: tuple[str, ...]
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in INSTALLERS:
        shim = bin_dir / name
        shim.write_text(RECORDING_SHIM, encoding="utf-8")
        shim.chmod(0o755)
    # dirname is the only ordinary command any path runs before its uv check,
    # so PATH holds it and the shims, and no host uv can be found.
    (bin_dir / "dirname").symlink_to(shutil.which("dirname"))
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "children.jsonl"
    path = str(bin_dir)
    assert shutil.which("uv", path=path) is None

    result = subprocess.run(
        [str(REPO_ROOT / command[0]), *command[1:]],
        cwd=tmp_path,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": path,
            "UV_PREREQUISITE_LOG": str(log),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert f"{command[0]}: uv not found on PATH" in result.stderr
    assert "https://docs.astral.sh/uv/" in result.stderr
    assert "./setup.sh" not in result.stdout + result.stderr
    assert not log.exists(), [json.loads(line) for line in log.read_text().splitlines()]
    assert list(home.iterdir()) == []
