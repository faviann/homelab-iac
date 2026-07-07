from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_lxc_docker_runtime_does_not_manage_docker_user_membership() -> None:
    runtime_tasks = (
        REPO_ROOT / "playbooks/roles/config/lxc_docker_runtime/tasks/main.yml"
    ).read_text()
    environment_tasks = (
        REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/tasks/main.yml"
    ).read_text()

    assert "docker_user" not in runtime_tasks
    assert "docker_users:" not in runtime_tasks
    assert "Ensure Docker user primary group exists" in environment_tasks
    assert 'gid: "{{ lxc_docker_environment_internal.docker_gid }}"' in environment_tasks
    assert "Create Docker user" in environment_tasks
    assert 'group: "{{ lxc_docker_environment_internal.docker_user }}"' in environment_tasks
    assert "groups:" in environment_tasks
    assert "- docker" in environment_tasks
