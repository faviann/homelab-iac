"""A held stack is left alone by stack sync until it is released."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

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


SOURCE_COMPOSE = "services:\n  app:\n    image: {{ stack_name }}:rendered\n"
DRIFTED_COMPOSE = "services:\n  app:\n    image: held:maintenance\n"


def stage_sync(tmp_path: Path) -> dict[str, Path]:
    source = tmp_path / "source"
    for stack in ("active", "held"):
        (source / stack).mkdir(parents=True)
        (source / stack / "compose.yaml.j2").write_text(SOURCE_COMPOSE, encoding="utf-8")
    (source / "held" / ".env").write_text("HELD=1\n", encoding="utf-8")
    (source / "held" / "config").mkdir()
    shared = tmp_path / "shared"
    for stack, content in (
        ("held", DRIFTED_COMPOSE), ("paused", "services: {}\n"), ("retired", "services: {}\n"),
    ):
        (shared / "stacks" / stack).mkdir(parents=True)
        (shared / "stacks" / stack / "compose.yaml").write_text(content, encoding="utf-8")
    (shared / "held-stacks").mkdir()
    for stack in ("held", "paused"):
        (shared / "held-stacks" / stack).touch()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        '#!/bin/sh\n'
        'printf "%s|%s\\n" "$PWD" "$*" >> "$DOCKER_TEST_LOG"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return {"source": source, "shared": shared, "bin": bin_dir, "log": tmp_path / "docker.log"}


def run_sync(tmp_path: Path, staged: dict[str, Path], **extra_vars: object) -> subprocess.CompletedProcess[str]:
    shared = staged["shared"]
    return run_playbook(tmp_path, {
        "gather_facts": True,
        "environment": {
            "PATH": f"{staged['bin']}:{os.environ['PATH']}",
            "DOCKER_TEST_LOG": str(staged["log"]),
        },
        "vars": {
            "lxc_docker_environment_internal": {
                "stacks_source": str(staged["source"]), "shared_mount_source": str(shared),
                "root_docker_conf_path": str(shared), "external_networks": [],
                "stale_stack_quarantine_root": str(shared / "stale-stacks"),
                "held_stacks_root": str(shared / "held-stacks"),
                "shared_owner": os.getuid(), "shared_group": os.getgid(),
                "docker_uid": os.getuid(), "docker_gid": os.getgid(),
                "path_ownership_overrides": [],
            },
            **extra_vars,
        },
        "roles": ["config/lxc_stack_sync"],
        "post_tasks": [{
            "name": "Record deployment report",
            "ansible.builtin.copy": {
                "content": "{{ lxc_docker_env_deployment_report | to_json }}",
                "dest": str(tmp_path / "report.json"),
                "mode": "0644",
            },
        }],
    })


def deployment_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))


def docker_calls(staged: dict[str, Path]) -> list[tuple[str, str]]:
    return [
        tuple(line.split("|", 1))
        for line in staged["log"].read_text(encoding="utf-8").splitlines()
    ]


def test_held_stack_is_left_alone_and_released(tmp_path: Path) -> None:
    staged = stage_sync(tmp_path)
    shared = staged["shared"]
    held_compose = shared / "stacks" / "held" / "compose.yaml"

    held_run = run_sync(tmp_path, staged)
    assert held_run.returncode == 0, held_run.stdout + held_run.stderr
    assert held_compose.read_text(encoding="utf-8") == DRIFTED_COMPOSE, "held stack is not re-rendered"
    assert not (shared / "stacks" / "held" / ".env").exists(), "held stack static files are not copied"
    assert not (shared / "stacks" / "held" / "config").exists(), "held stack directories are not created"
    calls = docker_calls(staged)
    assert [
        args for cwd, args in calls
        if cwd in (str(shared / "stacks" / "held"), str(shared / "stacks" / "paused"))
    ] == [], "no docker command runs in a held stack"
    assert (shared / "stacks" / "paused" / "compose.yaml").is_file(), (
        "a held stack with no source is not quarantined"
    )
    assert (str(shared / "stacks" / "retired"), "compose down --remove-orphans") in calls, (
        "an unheld stale stack is still stopped"
    )
    assert [path.name.split("-")[0] for path in (shared / "stale-stacks").iterdir()] == ["retired"], (
        "only the unheld stale stack is quarantined"
    )
    assert (str(shared / "stacks" / "active"), "compose up -d") in calls, "an unheld stack still starts"
    report = deployment_report(tmp_path)
    assert {**report, "skipped_stacks": sorted(report["skipped_stacks"])} == {
        "changed": True,
        "discovered_stacks": ["active"],
        "quarantined_stacks": ["retired"],
        "skipped_stacks": ["held", "paused"],
    }

    (shared / "held-stacks" / "held").unlink()
    staged["log"].unlink()
    released_run = run_sync(tmp_path, staged)
    assert released_run.returncode == 0, released_run.stdout + released_run.stderr
    assert held_compose.read_text(encoding="utf-8") == SOURCE_COMPOSE.replace(
        "{{ stack_name }}", "held"
    ), "released stack is rendered from source"
    assert (shared / "stacks" / "held" / ".env").is_file(), "released stack static files are copied"
    assert (shared / "stacks" / "held" / "config").is_dir(), "released stack directories are created"
    assert (str(shared / "stacks" / "held"), "compose up -d") in docker_calls(staged), (
        "released stack starts"
    )
    assert sorted(deployment_report(tmp_path)["discovered_stacks"]) == ["active", "held"]


def test_stack_filter_cannot_override_a_hold(tmp_path: Path) -> None:
    staged = stage_sync(tmp_path)
    held_compose = staged["shared"] / "stacks" / "held" / "compose.yaml"

    result = run_sync(tmp_path, staged, stack_filter="held")
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "./run.sh release --limit localhost --stack held" in output
    assert not staged["log"].exists(), "no docker command runs"
    assert held_compose.read_text(encoding="utf-8") == DRIFTED_COMPOSE, "held stack is not re-rendered"


def test_hold_marker_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "held").mkdir(parents=True)
    shared = tmp_path / "shared"
    marker = shared / "held-stacks" / "held"

    def hold(*arguments: str) -> subprocess.CompletedProcess[str]:
        return run_playbook(tmp_path, {
            "vars": {
                "lxc_docker_env_shared_mount_source": str(shared),
                "lxc_docker_env_stacks_source": str(source),
            },
            "tasks": [{
                "name": "Apply stack hold",
                "ansible.builtin.include_role": {
                    "name": "config/lxc_docker_environment",
                    "tasks_from": "stack_hold",
                },
            }],
        }, *arguments)

    listed = hold()
    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert "localhost held stacks: none" in listed.stdout, "list-only run reports no holds"
    assert not (shared / "held-stacks").exists(), "list-only run creates nothing"

    first = hold("-e", "stack_hold_state=present", "-e", "stack_filter=held")
    assert first.returncode == 0, first.stdout + first.stderr
    assert marker.is_file(), "hold creates the marker"
    assert "localhost held stacks: held" in first.stdout, "hold reports the held stack"

    repeat = hold("-e", "stack_hold_state=present", "-e", "stack_filter=held")
    assert repeat.returncode == 0, repeat.stdout + repeat.stderr
    assert "changed=0" in repeat.stdout, "repeated hold reports no change"

    typo = hold("-e", "stack_hold_state=present", "-e", "stack_filter=typo")
    assert typo.returncode != 0, "hold of an unknown stack fails"
    assert f"{source}/typo" in typo.stdout and "Known stacks: held" in typo.stdout
    assert not (shared / "held-stacks" / "typo").exists(), "failed hold creates no marker"

    released = hold("-e", "stack_hold_state=absent", "-e", "stack_filter=held")
    assert released.returncode == 0, released.stdout + released.stderr
    assert not marker.exists(), "release removes the marker"
    assert "localhost held stacks: none" in released.stdout, "release reports no holds"

    orphaned = hold("-e", "stack_hold_state=present", "-e", "stack_filter=held")
    assert orphaned.returncode == 0, orphaned.stdout + orphaned.stderr
    shutil.rmtree(source / "held")
    released_orphan = hold("-e", "stack_hold_state=absent", "-e", "stack_filter=held")
    assert released_orphan.returncode == 0, released_orphan.stdout + released_orphan.stderr
    assert not marker.exists(), "release works after the source directory is gone"
