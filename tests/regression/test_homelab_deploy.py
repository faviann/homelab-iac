from __future__ import annotations

import fcntl
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
FILES = REPO_ROOT / "playbooks/roles/config/lxc_bootstrap_node/files"
BUSY_COMMAND = yaml.safe_load(
    (REPO_ROOT / "inventory/host_vars/bootstrap.yml").read_text(encoding="utf-8")
)["lxc_busy_check_host_command"]
RECORD = '#!/bin/sh\necho "$(basename "$0") $*" >>"$TEST_ROOT/calls"\n'
DEPLOYED = ["git fetch origin main", "git checkout --detach FETCH_HEAD"]


def deploy_lock() -> str:
    [default] = re.findall(
        r'"\$\{HOMELAB_DEPLOY_LOCK:-([^}]+)\}"',
        (FILES / "homelab-deploy").read_text(encoding="utf-8"),
    )
    return default


def exec_start(unit: str) -> list[str]:
    [line] = [
        line
        for line in (FILES / unit).read_text(encoding="utf-8").splitlines()
        if line.startswith("ExecStart=")
    ]
    command = shlex.split(line.removeprefix("ExecStart=").replace("%i", "main"))
    return [argument.replace("/usr/local/sbin/", f"{FILES}/") for argument in command]


def write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def world(tmp_path: Path) -> dict[str, str]:
    bin_dir, checkout = tmp_path / "bin", tmp_path / "checkout"
    bin_dir.mkdir()
    checkout.mkdir()
    write_executable(bin_dir / "ssh", RECORD + "exit 99\n")
    write_executable(bin_dir / "git", RECORD)
    write_executable(checkout / "run.sh", RECORD)
    return {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOMELAB_DEPLOY_LOCK": str(tmp_path / "homelab-deploy.lock"),
        "TEST_ROOT": str(tmp_path),
    }


def deploy(tmp_path: Path, env: dict[str, str], unit: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        exec_start(unit),
        cwd=tmp_path / "checkout",
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def calls(tmp_path: Path) -> list[str]:
    record = tmp_path / "calls"
    return record.read_text(encoding="utf-8").splitlines() if record.exists() else []


@pytest.mark.parametrize(
    ("unit", "arguments"),
    [
        ("nightly-deploy@.service", ""),
        ("workstation-deploy@.service", "--limit workstation"),
        ("workstation-deploy-interrupt@.service", "--limit workstation --interrupt-busy"),
    ],
)
def test_each_unit_checks_out_the_ref_then_runs_the_lifecycle_without_reading_anything(
    tmp_path: Path, unit: str, arguments: str
) -> None:
    result = deploy(tmp_path, world(tmp_path), unit)

    assert result.returncode == 0, result
    assert calls(tmp_path) == [*DEPLOYED, f"run.sh {arguments}"]


def test_a_second_deploy_waits_a_second_then_exits_75(tmp_path: Path) -> None:
    env = world(tmp_path)
    with open(env["HOMELAB_DEPLOY_LOCK"], "a", encoding="utf-8") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        start = time.monotonic()
        result = deploy(tmp_path, env, "nightly-deploy@.service")
        elapsed = time.monotonic() - start

    assert result.returncode == 75, result
    assert result.stderr == "homelab-deploy: another deploy is in flight\n"
    assert elapsed >= 0.9
    assert calls(tmp_path) == []


def test_the_busy_command_reads_the_lock_homelab_deploy_takes() -> None:
    assert f"flock --nonblock {deploy_lock()} true" in BUSY_COMMAND
