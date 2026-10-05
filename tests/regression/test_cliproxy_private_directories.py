"""Exercise declared private storage through the existing host-directory tasks."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import shutil

import yaml

from ansible_test_helper import ansible_playbook_command


REPO = Path(__file__).resolve().parents[2]
PRIVATE_PATHS = {
    "/data/overmind/cliproxy",
    "/data/overmind/cliproxy/home",
    "/data/overmind/cliproxy/cpa",
    "/backups/overmind/cliproxy",
    "/conf/docker/stacks/cliproxy/appdata/auth",
}


def test_reconciliation_repairs_private_modes_without_changing_contents(tmp_path):
    inventory = yaml.safe_load((REPO / "inventory/host_vars/overmind.yml").read_text())
    declared = {
        item["path"]: item for item in inventory["lxc_docker_env_host_directories"]
        if item["path"] in PRIVATE_PATHS
    }
    assert declared.keys() == PRIVATE_PATHS
    sandbox = tmp_path / "private"
    entries = []
    for path, item in declared.items():
        assert (item["owner"], item["group"], item["mode"]) == ("0", "0", "0700")
        target = sandbox / path.lstrip("/")
        target.mkdir(parents=True, exist_ok=True)
        target.chmod(0o755)
        (target / "sentinel").write_bytes(b"synthetic-existing-state")
        entries.append({**item, "path": str(target)})

    digest = hashlib.sha1(b"synthetic-existing-state").hexdigest()
    tasks = REPO / "playbooks/roles/config/lxc_docker_environment/tasks/host_directories.yml"
    play = [{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": {"lxc_docker_env_host_directories": entries},
        "tasks": [
            {"ansible.builtin.include_tasks": str(tasks)},
            {"ansible.builtin.include_tasks": str(tasks)},
            {"ansible.builtin.stat": {"path": "{{ item.path }}"}, "loop": entries, "register": "dirs"},
            {"ansible.builtin.assert": {"that": [
                "item.stat.isdir", "item.stat.uid == 0", "item.stat.gid == 0", "item.stat.mode == '0700'",
            ]}, "loop": "{{ dirs.results }}", "loop_control": {"label": "{{ item.item.path }}"}},
            {"ansible.builtin.stat": {"path": "{{ item.path }}/sentinel"}, "loop": entries, "register": "files"},
            {"ansible.builtin.assert": {"that": [f"item.stat.checksum == '{digest}'"]},
             "loop": "{{ files.results }}", "loop_control": {"label": "{{ item.item.path }}"}},
        ],
    }]
    playbook = tmp_path / "reconcile.yml"
    playbook.write_text(yaml.safe_dump(play))
    try:
        result = subprocess.run(
            ["unshare", "-Ur", *ansible_playbook_command(str(playbook))], cwd=REPO,
            env={**os.environ, "ANSIBLE_CACHE_PLUGIN_CONNECTION": str(tmp_path / "cache")},
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        shutil.rmtree(sandbox)
