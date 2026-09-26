"""A held stack is left alone by stack sync until it is released."""

from __future__ import annotations

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
