"""API validation runs behind its own include without changing the advertised tasks."""

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
def api_validation(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> tuple[list[str], dict[str, str]]:
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
    collections.mkdir()
    if request.param:
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


@pytest.mark.parametrize("api_validation", [True], indirect=True)
def test_enabled_api_validation_executes(
    api_validation: tuple[list[str], dict[str, str]],
) -> None:
    """Enabled API validation resolves its collection and runs the module."""
    command, env = api_validation
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "controlled API invocation" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize("api_validation", [False], indirect=True)
def test_disabled_api_validation_does_not_resolve_the_api_collection(
    api_validation: tuple[list[str], dict[str, str]],
) -> None:
    """Disabled API validation succeeds without resolving its collection."""
    command, env = api_validation
    result = subprocess.run(
        command + ["-e", "proxmox_validate_api=false"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Proxmox host validation summary" in result.stdout, result.stdout
    assert "API access: not checked" in result.stdout, result.stdout
    assert "✓ API access" not in result.stdout, result.stdout
    assert "pct command: not checked" in result.stdout, result.stdout
    assert "✓ pct command" not in result.stdout, result.stdout
    assert "SSH access" not in result.stdout, result.stdout


@pytest.mark.parametrize("api_validation", [True], indirect=True)
def test_task_listing_advertises_api_task_exactly_once(
    api_validation: tuple[list[str], dict[str, str]],
) -> None:
    """Listing keeps the include's public task name, advertised once."""
    command, env = api_validation
    result = subprocess.run(command + ["--list-tasks"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("Test Proxmox API connectivity\t") == 1, result.stdout
