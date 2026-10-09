"""The nightly deploy's gate decides whether the bootstrap node may run against
the LXCs a workstation run could be configuring.

Reading busy or an SSH failure as idle would let two control nodes collide;
a deferral without the busy-check header and exit 3 would reach Discord as a
failure with no reason. Each case runs the gate against a stub ssh.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "playbooks/roles/config/lxc_bootstrap_node/files/nightly-deploy-gate"


def run_gate(tmp_path: Path, status: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    (tmp_path / "stdout").write_text(stdout, encoding="utf-8")
    (tmp_path / "stderr").write_text(stderr, encoding="utf-8")
    stub = tmp_path / "ssh"
    stub.write_text(
        f'#!/bin/sh\ncat "{tmp_path}/stdout"\ncat "{tmp_path}/stderr" >&2\nexit {status}\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(
        [str(GATE), "echo", "handed over"], env=env, capture_output=True, text=True, timeout=30
    )


def test_idle_hands_over_to_the_deploy(tmp_path: Path) -> None:
    result = run_gate(tmp_path, 0, stdout="no herdr agent is working\n")

    assert result.returncode == 0, result
    assert result.stdout == "handed over\n"


@pytest.mark.parametrize(
    ("world", "line"),
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
def test_any_answer_but_idle_defers_the_night(tmp_path: Path, world: dict, line: str) -> None:
    result = run_gate(tmp_path, **world)

    assert result.returncode == 3, result
    assert result.stderr == f"Deferred by busy checks:\n{line}\n"
    assert "handed over" not in result.stdout
