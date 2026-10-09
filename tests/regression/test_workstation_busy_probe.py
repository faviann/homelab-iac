"""The workstation busy probe decides whether a run may interrupt the workstation.

Reading server_not_running as busy would defer every night; reading an error as
idle would interrupt a working agent. Each case runs the probe against a stub
herdr and a temporary lock file.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
# The template's only Jinja is the home path, which every case overrides.
PROBE = (
    REPO_ROOT
    / "playbooks/roles/config/lxc_workstation_baseline/templates/workstation-busy-probe.py.j2"
)
# herdr 0.9.3 reports a stopped server like this, on stderr, with exit 1.
NOT_RUNNING = json.dumps(
    {"id": "cli:agent:list", "error": {"code": "server_not_running", "message": "no server"}}
)


def agents(*statuses: str) -> str:
    listed = [{"pane_id": f"p{index}", "agent_status": status} for index, status in enumerate(statuses)]
    return json.dumps({"id": "cli:agent:list", "result": {"type": "agent_list", "agents": listed}})


def run_probe(
    tmp_path: Path,
    stdout: str = "",
    stderr: str = "",
    status: int = 0,
    herdr: bool = True,
    lock: str = "missing",
) -> subprocess.CompletedProcess[str]:
    stub = tmp_path / "herdr"
    socket = tmp_path / "herdr.sock"
    if herdr:
        (tmp_path / "stdout").write_text(stdout, encoding="utf-8")
        (tmp_path / "stderr").write_text(stderr, encoding="utf-8")
        (tmp_path / "not-running").write_text(NOT_RUNNING, encoding="utf-8")
        # Run as root, herdr finds the user's server only through this
        # variable; without it, it reports no server, which reads as idle.
        stub.write_text(
            f'#!/bin/sh\n[ "$HERDR_SOCKET_PATH" = "{socket}" ] || '
            f'{{ cat "{tmp_path}/not-running" >&2; exit 1; }}\n'
            f'cat "{tmp_path}/stdout"\ncat "{tmp_path}/stderr" >&2\nexit {status}\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
    lock_path = tmp_path / "lifecycle.lock"
    if lock != "missing":
        lock_path.touch()
    env = {
        **os.environ,
        "WORKSTATION_BUSY_PROBE_HERDR": str(stub),
        "WORKSTATION_BUSY_PROBE_SOCKET": str(socket),
        "WORKSTATION_BUSY_PROBE_LOCK": str(lock_path),
    }
    command = [sys.executable, str(PROBE)]
    if lock == "held":
        with lock_path.open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            return subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize(
    ("world", "expected"),
    [
        ({"stdout": agents("idle", "working")}, 1),
        ({"stdout": agents("idle", "blocked", "done")}, 0),
        # A state the probe cannot place, or one a later herdr adds, is busy.
        ({"stdout": agents("idle", "unknown")}, 1),
        ({"stderr": NOT_RUNNING, "status": 1}, 0),
        ({"herdr": False}, 0),
        ({"stdout": "not json"}, 1),
        # An idle list does not excuse a failed exit.
        ({"stdout": agents("idle"), "stderr": json.dumps({"error": {"code": "socket_error"}}), "status": 2}, 1),
        ({"stdout": agents("idle"), "lock": "held"}, 1),
        # The lock file outlives every run, so existing must not mean held.
        ({"stdout": agents("idle"), "lock": "unheld"}, 0),
    ],
    ids=[
        "working-agent",
        "settled-states-without-lock-file",
        "unknown-state",
        "server-not-running",
        "herdr-not-installed",
        "malformed-json",
        "herdr-error-exit",
        "lock-held",
        "lock-file-unheld",
    ],
)
def test_probe_reads_idle_only_when_no_agent_or_run_can_be_interrupted(
    tmp_path: Path, world: dict, expected: int
) -> None:
    result = run_probe(tmp_path, **world)

    assert result.returncode == expected, result
    assert result.stdout.strip(), "every answer names its reason"
