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


def test_dependency_manifests_define_one_exact_source_of_truth() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_names = {
        re.split(r"[<>=!~]", dependency, maxsplit=1)[0]
        for dependency in project["project"]["dependencies"]
    }
    assert "ansible-core" in dependency_names
    assert "ansible" not in dependency_names

    requirements = yaml.safe_load(
        (REPO_ROOT / "collections" / "requirements.yml").read_text(encoding="utf-8")
    )
    assert set(requirements) == {"collections"}
    declared = {item["name"]: str(item["version"]) for item in requirements["collections"]}
    assert declared == {
        "ansible.posix": "2.2.2",
        "community.crypto": "3.3.0",
        "community.docker": "5.2.0",
        "community.library_inventory_filtering_v1": "1.1.5",
        "community.proxmox": "2.0.0",
    }
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", version) for version in declared.values())

    role_requirements = yaml.safe_load(
        (REPO_ROOT / "requirements" / "roles.yml").read_text(encoding="utf-8")
    )
    assert set(role_requirements) == {"roles"}
    assert role_requirements["roles"] == [
        {"name": "geerlingguy.docker", "version": "7.9.0"}
    ]


def test_controller_prerequisites_require_lifecycle_wrapper() -> None:
    extra_vars: dict[str, object] = {}

    missing_marker = run_playbook(
        REPO_ROOT / "playbooks" / "controller-prerequisites.yml",
        extra_vars=extra_vars,
        env={"HOMELAB_IAC_LIFECYCLE_WRAPPER": ""},
        tags="control_node_prerequisites",
    )
    assert missing_marker.returncode == 2
    assert "Lifecycle runs must use ./run.sh" in (
        missing_marker.stdout + missing_marker.stderr
    )

    present_marker = run_playbook(
        REPO_ROOT / "playbooks" / "controller-prerequisites.yml",
        extra_vars=extra_vars,
        env={"HOMELAB_IAC_LIFECYCLE_WRAPPER": "1"},
        tags="control_node_prerequisites",
    )
    assert present_marker.returncode == 0, present_marker.stdout + present_marker.stderr


def test_controller_prerequisites_name_supported_virtualenv_repair(
    tmp_path: Path,
) -> None:
    result = run_playbook(
        REPO_ROOT / "playbooks" / "controller-prerequisites.yml",
        extra_vars={
            "control_node_uv_virtualenv": str(tmp_path / "missing-venv"),
        },
        env={"HOMELAB_IAC_LIFECYCLE_WRAPPER": "1"},
        tags="control_node_prerequisites",
    )
    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "Run `./setup.sh sync`" in output
    assert "uv sync --locked" not in output
