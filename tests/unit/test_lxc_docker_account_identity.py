from pathlib import Path

import yaml


TASKS = (
    Path(__file__).resolve().parents[2]
    / "playbooks/roles/config/lxc_docker_environment/tasks/main.yml"
)


def test_docker_account_is_pinned_to_inventory_ids_and_joins_docker() -> None:
    tasks = yaml.safe_load(TASKS.read_text())
    [user] = [task["ansible.builtin.user"] for task in tasks if "ansible.builtin.user" in task]
    [primary_group] = [
        task["ansible.builtin.group"]
        for task in tasks
        if task.get("ansible.builtin.group", {}).get("name") == user["group"]
    ]

    assert user["uid"] == "{{ lxc_docker_environment_internal.docker_uid }}"
    assert primary_group["gid"] == "{{ lxc_docker_environment_internal.docker_gid }}"
    assert "docker" in user["groups"]
