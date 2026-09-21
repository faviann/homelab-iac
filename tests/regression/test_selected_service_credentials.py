"""Selected stack configuration must not consume unrelated service credentials."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest
import yaml

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]


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


@pytest.mark.parametrize("stack_filter", ["selected", "docker-agents"])
def test_filtered_deployment_preserves_managed_host_assets_without_unselected_credentials(
    tmp_path: Path, stack_filter: str,
) -> None:
    source = tmp_path / "source"
    (source / "selected").mkdir(parents=True)
    (source / "selected/compose.yaml").write_text("services: {}\n")
    shared = tmp_path / "shared"
    agents = shared / "stacks/docker-agents"
    agents.mkdir(parents=True)
    existing_env = "TOKEN=existing-fixture-token\n"
    (agents / ".env").write_text(existing_env)
    (shared / "admin").mkdir()
    (shared / "README.md").write_text("obsolete deployed documentation\n")
    legacy = shared / "stacks/legacy"
    legacy.mkdir()
    (legacy / "compose.yml").write_text("services: {}\n")
    shared.chmod(0o710)
    (shared / "stacks").chmod(0o700)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        '#!/bin/sh\n'
        'printf "%s|%s\\n" "$PWD" "$*" >> "$DOCKER_TEST_LOG"\n'
        'printf "Total reclaimed space: 0B\\n"\n'
    )
    docker.chmod(0o755)
    docker_log = tmp_path / "docker.log"
    report = tmp_path / "report.yml"
    # Run the real role wiring and asset/stack reconciliation. Package, mount,
    # and account setup are outside this fixture; Docker commands are recorded.
    result = run_playbook(tmp_path, {
        "environment": {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "DOCKER_TEST_LOG": str(docker_log),
        },
        "vars": {
            "stack_filter": stack_filter,
            "docker_user": "fixture", "docker_uid": os.getuid(), "docker_gid": os.getgid(),
            "docker_enabled": True, "docker_agents_enabled": True,
            "portal_instance": False, "traefik_kop_enabled": False,
            "homepage_docker_proxy_port": 2375,
            "dockhand_hawser_token": "{{ vault_unselected_hawser_token }}",
            "dockhand_hawser_stacks_dir": str(shared / "dockhand-stacks"),
            "lxc_docker_env_shared_mount_source": str(shared),
            "lxc_docker_env_root_docker_conf_path": str(shared),
            "lxc_docker_env_stacks_source": str(source),
            "lxc_docker_env_absent_containers": [],
            "lxc_docker_env_legacy_managed_stacks": [{
                "name": "legacy", "dir": str(legacy), "compose_file": "compose.yml",
            }],
            "overmind_postgres_backup_enabled": True,
        },
        "roles": ["config/lxc_docker_environment"],
        "tasks": [{"ansible.builtin.copy": {
            "content": "{{ lxc_docker_env_deployment_report | to_json }}", "dest": str(report),
        }}],
    }, "--skip-tags", "docker_host_setup")
    output = result.stdout + result.stderr
    assert (agents / ".env").read_text() == existing_env
    if stack_filter == "docker-agents":
        assert result.returncode != 0, output
        assert "Validate Dockhand Hawser variables" in output
        assert not report.exists()
        return

    assert result.returncode == 0, output
    assert not legacy.exists()
    assert not (shared / "admin").exists()
    assert not (shared / "README.md").exists()
    assert stat.S_IMODE(shared.stat().st_mode) == 0o710
    assert stat.S_IMODE((shared / "stacks").stat().st_mode) == 0o755
    assert "TOKEN=${TOKEN}" in (agents / "compose.yml").read_text()
    assert (shared / "stacks/selected/compose.yaml").exists()
    commands = docker_log.read_text().splitlines()
    assert f"{legacy}|compose down --remove-orphans" in commands
    assert [line for line in commands if "|compose up" in line] == [
        f"{shared}/stacks/selected|compose up -d",
    ]
    deployment = yaml.safe_load(report.read_text())
    assert deployment["changed"] is True
    assert deployment["discovered_stacks"] == ["selected"]
