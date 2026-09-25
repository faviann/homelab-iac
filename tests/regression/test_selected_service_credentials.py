"""Selected stack configuration must not consume unrelated service credentials."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
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


def test_selected_placeholder_credential_is_rejected_before_writing(tmp_path: Path) -> None:
    stack_name = "credential_consumer"
    sensitive_values = {
        "jwt_secret": "REPLACE_WITH_RANDOM_JWT_SECRET",
        "postgres_password": "fixture-sensitive-postgres",
    }
    source = tmp_path / "source"
    shutil.copytree(REPO_ROOT / "stacks/jellyfin/jellystat", source / stack_name)
    shared = tmp_path / "shared"
    (shared / "stacks").mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        '#!/bin/sh\n'
        'printf "%s|%s\\n" "$PWD" "$*" >> "$DOCKER_TEST_LOG"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    docker_log = tmp_path / "docker.log"
    result = run_playbook(tmp_path, {
        "environment": {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "DOCKER_TEST_LOG": str(docker_log),
        },
        "vars": {
            "stack_filter": stack_name,
            "default_domain": "example.invalid",
            "docker_uid": os.getuid(), "docker_gid": os.getgid(),
            "lxc_docker_environment_internal": {
                "stacks_source": str(source), "shared_mount_source": str(shared),
                "root_docker_conf_path": str(shared), "external_networks": [],
                "shared_owner": os.getuid(), "shared_group": os.getgid(),
                "docker_uid": os.getuid(), "docker_gid": os.getgid(),
                "path_ownership_overrides": [],
            },
            "lxc_docker_env_stack_vars": {stack_name: sensitive_values},
        },
        "roles": ["config/lxc_stack_sync"],
    }, "-vvv", "--diff")
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "Required stack template inputs are missing or invalid" in output
    for value in sensitive_values.values():
        assert value not in output
    assert not (shared / f"stacks/{stack_name}").exists()
    assert not docker_log.exists()


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
    for stack in ("selected", "unselected"):
        (source / stack).mkdir(parents=True)
        (source / stack / "compose.yaml.j2").write_text(
            "services: {}\nx-secret: '{{ stack_vars.value }}'\nx-prereq-dirs: ['./data']\n"
        )
        (source / stack / ".env.j2").write_text("VALUE={{ stack_vars.value }}\n")
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
    retired = shared / "stacks/retired"
    retired.mkdir()
    (retired / "compose.yaml").write_text("services: {}\n")
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
            "dockhand_hawser_token": "REPLACE_ME",
            "dockhand_hawser_stacks_dir": str(shared / "dockhand-stacks"),
            "lxc_docker_env_shared_mount_source": str(shared),
            "lxc_docker_env_root_docker_conf_path": str(shared),
            "lxc_docker_env_stacks_source": str(source),
            "lxc_docker_env_absent_containers": [],
            "lxc_docker_env_legacy_managed_stacks": [{
                "name": "legacy", "dir": str(legacy), "compose_file": "compose.yml",
            }],
            "overmind_postgres_backup_enabled": True,
            "lxc_docker_env_stack_vars": {
                "selected": {"value": "fixture-selected-value"},
                "unselected": {"value": "{{ vault_unselected_service_secret }}"},
            },
        },
        "roles": ["config/lxc_docker_environment"],
        "tasks": [{"ansible.builtin.copy": {
            "content": "{{ lxc_docker_env_deployment_report | to_json }}", "dest": str(report),
        }}],
    }, "--skip-tags", "docker_host_setup", "-vvv", "--diff")
    output = result.stdout + result.stderr
    assert (agents / ".env").read_text() == existing_env
    if stack_filter == "docker-agents":
        assert result.returncode != 0, output
        assert "Validate Dockhand Hawser variables" in output
        assert not [line for line in docker_log.read_text().splitlines()
                    if "|compose up" in line]
        assert not report.exists()
        return

    assert result.returncode == 0, output
    assert "fixture-selected-value" not in output
    assert not (shared / "stacks/unselected").exists()
    assert not legacy.exists()
    assert not (shared / "admin").exists()
    assert not (shared / "README.md").exists()
    assert stat.S_IMODE(shared.stat().st_mode) == 0o710
    assert stat.S_IMODE((shared / "stacks").stat().st_mode) == 0o755
    assert "TOKEN=${TOKEN}" in (agents / "compose.yml").read_text()
    assert (shared / "stacks/selected/.env").read_text() == "VALUE=fixture-selected-value\n"
    assert (retired / "compose.yaml").exists()
    commands = docker_log.read_text().splitlines()
    assert not [line for line in commands if line.startswith(f"{retired}|")]
    assert f"{legacy}|compose down --remove-orphans" in commands
    assert [line for line in commands if "|compose up" in line] == [
        f"{shared}/stacks/selected|compose up -d",
    ]
    deployment = yaml.safe_load(report.read_text())
    assert deployment["changed"] is True
    assert deployment["discovered_stacks"] == ["selected"]
    assert sorted(deployment["skipped_stacks"]) == ["docker-agents", "retired"]
