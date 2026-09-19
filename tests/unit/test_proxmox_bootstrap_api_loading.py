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


def test_enabled_api_validation_executes(
    api_validation: tuple[list[str], dict[str, str]],
) -> None:
    """Enabled API validation resolves its collection and runs the module."""
    command, env = api_validation
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "controlled API invocation" in result.stdout, result.stdout + result.stderr


def test_disabled_api_validation_does_not_invoke_the_api_module(
    api_validation: tuple[list[str], dict[str, str]],
) -> None:
    """Disabling API validation skips the API task instead of invoking the module.

    Ansible always searches `<playbook_dir>/collections`, where this fixture
    puts its stub, so the stub stays resolvable however
    ANSIBLE_COLLECTIONS_PATH is set. This case therefore proves the task is
    not executed; it cannot prove the collection goes unresolved.
    """
    command, env = api_validation
    result = subprocess.run(
        command + ["-e", "proxmox_validate_api=false"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "controlled API invocation" not in result.stdout


def test_task_listing_advertises_api_task_exactly_once(
    api_validation: tuple[list[str], dict[str, str]],
) -> None:
    """Listing keeps the include's public task name, advertised once."""
    command, env = api_validation
    result = subprocess.run(command + ["--list-tasks"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("Test Proxmox API connectivity\t") == 1, result.stdout
