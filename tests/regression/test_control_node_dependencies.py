from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

import yaml

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)


def run_playbook(
    playbook: Path,
    *,
    extra_vars: dict[str, object],
    env: dict[str, str] | None = None,
    tags: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        *ANSIBLE_PLAYBOOK,
        "-i",
        "localhost,",
        "-c",
        "local",
        str(playbook),
        "-e",
        json.dumps(extra_vars),
    ]
    if tags:
        command.extend(["--tags", tags])
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+")


def test_dependency_manifests_pin_exact_versions() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_names = {
        re.split(r"[<>=!~]", dependency, maxsplit=1)[0]
        for dependency in project["project"]["dependencies"]
    }
    assert "ansible-core" in dependency_names
    assert "ansible" not in dependency_names

    for manifest, key in (
        ("collections/requirements.yml", "collections"),
        ("requirements/roles.yml", "roles"),
    ):
        entries = yaml.safe_load((REPO_ROOT / manifest).read_text(encoding="utf-8"))[key]
        assert entries, manifest
        for entry in entries:
            assert EXACT_VERSION.fullmatch(str(entry["version"])), (manifest, entry)


def test_controller_prerequisites_reject_a_missing_wrapper_marker() -> None:
    result = run_playbook(
        REPO_ROOT / "playbooks" / "controller-prerequisites.yml",
        extra_vars={},
        env={"HOMELAB_IAC_LIFECYCLE_WRAPPER": ""},
        tags="control_node_prerequisites",
    )
    assert result.returncode == 2
    assert "Lifecycle runs must use ./run.sh" in result.stdout + result.stderr


def test_controller_prerequisites_accept_the_marker_and_reject_a_missing_virtualenv(
    tmp_path: Path,
) -> None:
    # The success path is owned by controller_prerequisite_fact_cache_launcher.py.
    missing_virtualenv = tmp_path / "missing-venv"
    result = run_playbook(
        REPO_ROOT / "playbooks" / "controller-prerequisites.yml",
        extra_vars={"control_node_uv_virtualenv": str(missing_virtualenv)},
        env={"HOMELAB_IAC_LIFECYCLE_WRAPPER": "1"},
        tags="control_node_prerequisites",
    )
    output = result.stdout + result.stderr
    assert result.returncode == 2, output
    assert "Lifecycle runs must use ./run.sh" not in output
    assert str(missing_virtualenv) in output
