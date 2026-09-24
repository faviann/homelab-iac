from pathlib import Path

import yaml


TASKS = (
    Path(__file__).resolve().parents[2]
    / "playbooks/roles/config/lxc_docker_environment/tasks/main.yml"
)
DOCKER_USER = "{{ lxc_docker_environment_internal.docker_user }}"


def module_args(tasks: list[dict], module: str, name: str) -> dict:
    return next(
        task[module] for task in tasks if task.get(module, {}).get("name") == name
    )


def test_docker_account_is_pinned_to_inventory_ids_and_joins_docker() -> None:
    tasks = yaml.safe_load(TASKS.read_text())
    user = module_args(tasks, "ansible.builtin.user", DOCKER_USER)
    primary_group = module_args(tasks, "ansible.builtin.group", user["group"])

    assert user["uid"] == "{{ lxc_docker_environment_internal.docker_uid }}"
    assert primary_group["gid"] == "{{ lxc_docker_environment_internal.docker_gid }}"
    assert "docker" in user["groups"]
