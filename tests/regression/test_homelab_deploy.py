"""homelab-deploy serializes this node's deploys, and gates the nightly deploy on
the workstation reading idle.

The nightly deploy must read the workstation only while it holds the deploy
lock: a workstation run that read this node first then still finds the lock
held, so the two never run together. Reading busy or an SSH failure as idle
would let two control nodes collide; a deferral without the busy-check header
and exit 3 would reach Discord as a failure with no reason. A busy probe that
makes a starting deploy exit 75 loses the night, so a deploy waits a second for
its lock. Each case runs a deploy unit's ExecStart against a stub ssh, git, and
./run.sh.
"""

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
STUB_SSH = """#!/bin/bash
flock --nonblock "$HOMELAB_DEPLOY_LOCK" true && { echo "probe ran without the deploy lock" >&2; exit 99; }
printf '%s\\n' "$@" >"$TEST_ROOT/ssh-argv"
cat "$TEST_ROOT/stdout"
cat "$TEST_ROOT/stderr" >&2
exit "$(cat "$TEST_ROOT/status")"
"""
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


def world(tmp_path: Path, status: int = 0, stdout: str = "", stderr: str = "") -> dict[str, str]:
    bin_dir, checkout = tmp_path / "bin", tmp_path / "checkout"
    bin_dir.mkdir()
    checkout.mkdir()
    write_executable(bin_dir / "ssh", STUB_SSH)
    write_executable(bin_dir / "git", RECORD)
    write_executable(checkout / "run.sh", RECORD)
    (tmp_path / "status").write_text(str(status), encoding="utf-8")
    (tmp_path / "stdout").write_text(stdout, encoding="utf-8")
    (tmp_path / "stderr").write_text(stderr, encoding="utf-8")
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


def test_idle_reads_the_workstation_under_the_lock_then_deploys(tmp_path: Path) -> None:
    env = world(tmp_path, 0, stdout="no herdr agent is working\n")

    result = deploy(tmp_path, env, "nightly-deploy@.service")

    assert result.returncode == 0, result
    assert calls(tmp_path) == [*DEPLOYED, "run.sh "]
    argv = (tmp_path / "ssh-argv").read_text(encoding="utf-8").splitlines()
    assert argv[-2:] == ["workstation.faviann.vms", "/usr/local/sbin/workstation-busy-probe"]
    assert {
        "AddressFamily=inet",
        "StrictHostKeyChecking=yes",
        f"UserKnownHostsFile={env['HOME']}/.ansible/known_hosts",
    } <= set(argv)


@pytest.mark.parametrize(
    ("answer", "line"),
    [
        (
            {"status": 1, "stdout": "1 herdr agent(s) working\n"},
            "workstation: busy (1 herdr agent(s) working); nightly deploy not started",
        ),
        (
            {"status": 255, "stderr": "Host key verification failed.\n"},
            "workstation: check failed (exit 255: Host key verification failed.); nightly deploy not started",
        ),
    ],
    ids=["busy", "ssh-failure"],
)
def test_any_answer_but_idle_defers_the_night_before_the_checkout(
    tmp_path: Path, answer: dict, line: str
) -> None:
    result = deploy(tmp_path, world(tmp_path, **answer), "nightly-deploy@.service")

    assert result.returncode == 3, result
    assert result.stderr == f"Deferred by busy checks:\n{line}\n"
    assert calls(tmp_path) == []


@pytest.mark.parametrize(
    ("unit", "arguments"),
    [
        ("workstation-deploy-interrupt@.service", "--limit workstation --interrupt-busy"),
    ],
)
def test_workstation_deploys_never_read_the_workstation(
    tmp_path: Path, unit: str, arguments: str
) -> None:
    result = deploy(tmp_path, world(tmp_path, 1, stdout="1 herdr agent(s) working\n"), unit)

    assert result.returncode == 0, result
    assert calls(tmp_path) == [*DEPLOYED, f"run.sh {arguments}"]
    assert not (tmp_path / "ssh-argv").exists()


def test_a_second_deploy_waits_a_second_then_exits_75_without_reading(tmp_path: Path) -> None:
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
    assert not (tmp_path / "ssh-argv").exists()


def test_the_busy_command_reads_the_lock_homelab_deploy_takes() -> None:
    assert f"flock --nonblock {deploy_lock()} true" in BUSY_COMMAND
