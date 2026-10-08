"""Contract tests for the bootstrap node role."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_ROOT = REPO_ROOT / "playbooks/roles/config/lxc_bootstrap_node"
CONFIGURE_TASKS = REPO_ROOT / "playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml"


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def task_named(tasks: list[dict], name: str) -> dict:
    return next(task for task in tasks if task.get("name") == name)


def test_lifecycle_wires_the_role_once_behind_its_flag() -> None:
    guest_tasks = [
        task
        for top in load_yaml(CONFIGURE_TASKS)
        for task in [top, *top.get("block", [])]
        if task.get("ansible.builtin.include_role", {}).get("name") == "config/lxc_bootstrap_node"
    ]

    assert len(guest_tasks) == 1
    assert guest_tasks[0]["when"] == "bootstrap_node_enabled | default(false)"


def test_the_node_installs_bw_through_the_shared_role() -> None:
    install = task_named(load_yaml(ROLE_ROOT / "tasks/main.yml"), "Install Bitwarden CLI")

    assert install["ansible.builtin.import_role"] == {"name": "config/bitwarden_cli"}


def test_uv_comes_from_the_installer_for_the_pinned_version() -> None:
    version = load_yaml(ROLE_ROOT / "defaults/main.yml")["lxc_bootstrap_node_uv_version"]
    command = task_named(load_yaml(ROLE_ROOT / "tasks/main.yml"), "Install uv")["ansible.builtin.shell"]["cmd"]

    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert "https://astral.sh/uv/{{ lxc_bootstrap_node_uv_version }}/install.sh" in command


def unit_settings(name: str) -> dict[str, list[str]]:
    settings: dict[str, list[str]] = {}
    for line in (ROLE_ROOT / "files" / name).read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and not line.startswith("#"):
            settings.setdefault(key.strip(), []).append(value.strip())
    return settings


def test_both_deploy_units_report_every_outcome_and_only_one_interrupts() -> None:
    routine = unit_settings("workstation-deploy@.service")
    interrupting = unit_settings("workstation-deploy-interrupt@.service")

    for unit in (routine, interrupting):
        [start] = unit["ExecStart"]
        assert start.startswith("/usr/local/sbin/workstation-deploy %i")
        assert unit["ExecStopPost"]
    assert "--interrupt-busy" not in routine["ExecStart"][0]
    assert "--interrupt-busy" in interrupting["ExecStart"][0]


def test_the_nightly_timer_starts_the_routine_unit_without_catching_up() -> None:
    timer = unit_settings("workstation-deploy.timer")

    assert timer["Unit"] == ["workstation-deploy@main.service"]
    assert timer.get("Persistent", ["false"]) == ["false"]


def test_the_webhook_environment_file_is_root_only() -> None:
    task = task_named(load_yaml(ROLE_ROOT / "tasks/main.yml"), "Install the deploy webhook environment")

    assert (task["ansible.builtin.template"]["owner"], task["ansible.builtin.template"]["mode"]) == ("root", "0600")
