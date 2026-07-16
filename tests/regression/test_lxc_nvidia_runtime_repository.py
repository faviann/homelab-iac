#!/usr/bin/env python3
"""Regression test for retryable NVIDIA repository publication."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = (
    REPO_ROOT
    / "tests"
    / "regression"
    / "fixtures"
    / "lxc_nvidia_runtime_repository_test.yml"
)
FIXTURE_ROLES = (
    REPO_ROOT
    / "tests"
    / "regression"
    / "fixtures"
    / "lxc_nvidia_runtime_repository_assets"
    / "roles"
)


def test_lxc_nvidia_runtime_repository_publication_is_retryable() -> None:
    with tempfile.TemporaryDirectory(prefix="lxc-nvidia-repository-") as temp_root:
        repository_dir = Path(temp_root) / "repository"
        repository_dir.mkdir()

        env = os.environ.copy()
        env["ANSIBLE_CACHE_PLUGIN_CONNECTION"] = str(Path(temp_root) / "fact-cache")
        env["ANSIBLE_LOCAL_TEMP"] = str(Path(temp_root) / "ansible-local-tmp")
        env["ANSIBLE_REMOTE_TEMP"] = str(Path(temp_root) / "ansible-tmp")
        env["ANSIBLE_ROLES_PATH"] = os.pathsep.join(
            [str(FIXTURE_ROLES), str(REPO_ROOT / "playbooks" / "roles")]
        )
        env["UV_CACHE_DIR"] = str(Path(temp_root) / "uv-cache")
        env["TMPDIR"] = temp_root
        result = subprocess.run(
            [
                "bwrap",
                "--ro-bind",
                "/",
                "/",
                "--bind",
                temp_root,
                temp_root,
                "--bind",
                str(repository_dir),
                "/etc/apt/sources.list.d",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--chdir",
                str(REPO_ROOT),
                "uv",
                "run",
                "--locked",
                "ansible-playbook",
                str(PLAYBOOK),
                "-f",
                "1",
                "--tags",
                "lxc_nvidia_runtime_repository",
                "-e",
                f"temp_root={temp_root}",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, output
