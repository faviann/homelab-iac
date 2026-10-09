"""Contract tests for the bootstrap node role."""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_ROOT = REPO_ROOT / "playbooks/roles/config/lxc_bootstrap_node"
CONFIGURE_TASKS = REPO_ROOT / "playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml"


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_lifecycle_wires_the_role_once_behind_its_flag() -> None:
    guest_tasks = [
        task
        for top in load_yaml(CONFIGURE_TASKS)
        for task in [top, *top.get("block", [])]
        if task.get("ansible.builtin.include_role", {}).get("name") == "config/lxc_bootstrap_node"
    ]

    assert len(guest_tasks) == 1
    assert guest_tasks[0]["when"] == "bootstrap_node_enabled | default(false)"


def unit_settings(name: str) -> dict[str, list[str]]:
    settings: dict[str, list[str]] = {}
    for line in (ROLE_ROOT / "files" / name).read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and not line.startswith("#"):
            settings.setdefault(key.strip(), []).append(value.strip())
    return settings


def test_both_deploy_units_target_workstation_and_only_one_interrupts() -> None:
    routine = unit_settings("workstation-deploy@.service")
    interrupting = unit_settings("workstation-deploy-interrupt@.service")

    for unit in (routine, interrupting):
        assert unit["ExecStopPost"]
    assert routine["ExecStart"] == ["/usr/local/sbin/homelab-deploy %i --limit workstation"]
    assert interrupting["ExecStart"] == [
        "/usr/local/sbin/homelab-deploy %i --limit workstation --interrupt-busy"
    ]


def test_the_nightly_deploy_runs_behind_the_gate_and_never_interrupts() -> None:
    nightly = unit_settings("nightly-deploy@.service")

    assert nightly["ExecStopPost"]
    assert nightly["ExecStart"] == [
        "/usr/local/sbin/nightly-deploy-gate /usr/local/sbin/homelab-deploy %i"
    ]


def test_the_nightly_timer_starts_the_nightly_deploy_without_catching_up() -> None:
    timer = unit_settings("nightly-deploy.timer")

    assert timer["Unit"] == ["nightly-deploy@main.service"]
    assert timer.get("Persistent", ["false"]) == ["false"]
