"""Selected stack configuration must not consume unrelated service credentials."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest
import yaml

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_TASKS = REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/tasks"
LIFECYCLE_TASKS = REPO_ROOT / "playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks"


def run_playbook(tmp_path: Path, play: dict, *arguments: str) -> subprocess.CompletedProcess[str]:
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False, **play,
    }]), encoding="utf-8")
    return subprocess.run(
        ansible_playbook_command(str(playbook), *arguments),
        cwd=REPO_ROOT,
        env={**os.environ, "ANSIBLE_CACHE_PLUGIN_CONNECTION": str(tmp_path / "cache")},
        capture_output=True,
        text=True,
        check=False,
    )


def test_stack_filter_renders_only_selected_service_inputs(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shared = tmp_path / "shared"
    (shared / "stacks").mkdir(parents=True)
    for stack in ("selected", "unselected"):
        (source / stack).mkdir(parents=True)
        (source / stack / "compose.yaml.j2").write_text(
            "services: {}\nx-secret: '{{ stack_vars.value }}'\nx-prereq-dirs: ['./data']\n",
            encoding="utf-8",
        )
        (source / stack / ".env.j2").write_text(
            "VALUE={{ stack_vars.value }}\n", encoding="utf-8"
        )
    result = run_playbook(tmp_path, {
        "vars": {
            "stack_filter": "selected",
            "lxc_docker_environment_internal": {
                "stacks_source": str(source), "shared_mount_source": str(shared),
                "shared_owner": os.getuid(), "shared_group": os.getgid(),
                "docker_uid": os.getuid(), "docker_gid": os.getgid(),
            },
            "lxc_docker_env_stack_vars": {
                "selected": {"value": "fixture-selected-value"},
                "unselected": {"value": "{{ vault_unselected_service_secret }}"},
            },
        },
        "tasks": [{"ansible.builtin.include_role": {
            "name": "config/lxc_stack_sync", "tasks_from": task,
        }} for task in ("discover", "materialize")],
    }, "-vvv", "--diff")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "fixture-selected-value" not in result.stdout + result.stderr
    assert (shared / "stacks/selected/.env").read_text() == "VALUE=fixture-selected-value\n"
    assert not (shared / "stacks/unselected").exists()


def test_unselected_optional_credential_is_not_validated_by_docker_role(tmp_path: Path) -> None:
    result = run_playbook(tmp_path, {
        "vars": {
            "stack_filter": "selected", "docker_user": "fixture",
            "docker_uid": os.getuid(), "docker_gid": os.getgid(),
            "dockhand_hawser_token": "{{ vault_unselected_hawser_token }}",
        },
        "roles": ["config/lxc_docker_environment"],
    }, "--tags", "always")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("stack_filter", ["selected", "docker-agents", "overmind", "dockhand", "auth", None])
def test_service_branches_honor_stack_selection(tmp_path: Path, stack_filter: str | None) -> None:
    # Exercise the production include boundaries; their consumers are replaced by
    # a marker so selected branches cannot touch a host or service API.
    tasks = yaml.safe_load((DOCKER_TASKS / "main.yml").read_text())
    tasks += yaml.safe_load((LIFECYCLE_TASKS / "configure.yml").read_text())[1]["block"]
    branches = {
        "Materialize managed Docker assets": "docker-agents",
        "Configure overmind verified Postgres backups": "overmind",
        "Seed Dockhand environments": "dockhand",
        "Apply Authentik blueprints": "auth",
    }
    selected_tasks = []
    for task in tasks:
        if task["name"] in branches:
            selected_tasks.append({
                "name": task["name"], "when": task.get("when", True),
                "ansible.builtin.copy": {
                    "content": "selected", "dest": str(tmp_path / task["name"]), "mode": "0600",
                },
            })
    result = run_playbook(tmp_path, {
        "vars": {
            "stack_filter": stack_filter,
            "overmind_postgres_backup_enabled": True,
            "portal_instance": True, "authentik_blueprint_sync_enabled": True,
        },
        "tasks": selected_tasks,
    })
    assert result.returncode == 0, result.stdout + result.stderr
    for name, stack in branches.items():
        assert (tmp_path / name).exists() == (stack_filter in (None, stack))
