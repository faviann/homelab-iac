"""API validation owns its collection without changing task selection."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests/regression"))
try:
    from ansible_test_helper import ansible_playbook_command
finally:
    sys.path.pop(0)

TASKS = REPO_ROOT / "playbooks/roles/infrastructure/proxmox_host_bootstrap/tasks"


@pytest.fixture
def api_validation(tmp_path: Path) -> tuple[list[str], dict[str, str]]:
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(
        yaml.safe_dump([
            {
                "hosts": "localhost",
                "gather_facts": False,
                "vars": {
                    "proxmox_validate_api": True,
                    "proxmox_validate_pct": False,
                    "proxmox_ssh_ready": False,
                    "proxmox_api_host": "controlled.invalid",
                    "proxmox_host": "localhost",
                    "proxmox_api_user": "fixture",
                    "proxmox_api_token_id": "fixture",
                    "proxmox_api_token_secret": "unused-fixture-placeholder",
                    "proxmox_default_node": "fixture",
                },
                "tasks": [{
                    "ansible.builtin.import_tasks": str(TASKS / "validation.yml"),
                    "tags": ["proxmox_bootstrap", "validation"],
                }],
            }
        ])
    )
    collections = tmp_path / "collections"
    module = collections / "ansible_collections/community/proxmox/plugins/modules/proxmox_vm_info.py"
    module.parent.mkdir(parents=True)
    # An intentional module failure proves execution, independent of callbacks.
    module.write_text(
        '#!/usr/bin/python\n'
        'print(\'{"failed": true, "msg": "controlled API invocation"}\')\n'
    )
    env = {
        **os.environ,
        "ANSIBLE_COLLECTIONS_PATH": str(collections),
        "ANSIBLE_COLLECTIONS_SCAN_SYS_PATH": "false",
        "ANSIBLE_STDOUT_CALLBACK": "default",
    }
    return [
        *ansible_playbook_command(supplies_own_inventory=True), "-i", "localhost,",
        "-c", "local", str(playbook),
    ], env


@pytest.mark.parametrize(
    "tags",
    [
        [],
        ["--tags", "validation"],
        ["--tags", "proxmox_bootstrap"],
        ["--skip-tags", "always"],
    ],
)
def test_selected_api_validation_executes(
    api_validation: tuple[list[str], dict[str, str]], tags: list[str]
) -> None:
    command, env = api_validation
    result = subprocess.run(command + tags, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "controlled API invocation" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize("selection", [
    ["-e", "proxmox_validate_api=false"],
    ["--tags", "ssh_setup"],
    ["--skip-tags", "validation"],
    ["--skip-tags", "proxmox_bootstrap"],
])
def test_unselected_api_validation_needs_no_collection(
    api_validation: tuple[list[str], dict[str, str]], selection: list[str], tmp_path: Path
) -> None:
    command, env = api_validation
    env["ANSIBLE_COLLECTIONS_PATH"] = str(tmp_path / "empty")
    result = subprocess.run(command + selection, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_task_and_tag_listing_preserves_api_and_surrounding_tasks(
    api_validation: tuple[list[str], dict[str, str]], tmp_path: Path
) -> None:
    command, env = api_validation
    env["ANSIBLE_COLLECTIONS_PATH"] = str(tmp_path / "empty")
    result = subprocess.run(command + ["--list-tasks", "--list-tags"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    for name in (
        "Check if pct command is available",
        "Test Proxmox API connectivity",
        "Proxmox host validation summary",
    ):
        assert result.stdout.count(name + "\t") == 1
    assert "TASK TAGS: [proxmox_bootstrap, validation]" in result.stdout
