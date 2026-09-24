from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_TASKS = (
    REPO_ROOT
    / "playbooks"
    / "roles"
    / "provisioning"
    / "proxmox_lxc_fleet_preflight"
    / "tasks"
    / "main.yml"
)
# The regression fixtures run every host locally, so they cannot observe where
# these API calls execute or what -vvv would print; both are asserted here.
CREDENTIAL_BEARING_MODULES = (
    "community.proxmox.proxmox_vm_info",
    "ansible.builtin.uri",
)


def tasks_using(module: str, tasks: list[dict]) -> list[dict]:
    found: list[dict] = []
    for task in tasks:
        if module in task:
            found.append(task)
        for section in ("block", "rescue", "always"):
            found += tasks_using(module, task.get(section, []))
    return found


def test_proxmox_api_calls_run_on_the_controller_without_disclosure() -> None:
    tasks = yaml.safe_load(PREFLIGHT_TASKS.read_text(encoding="utf-8"))

    for module in CREDENTIAL_BEARING_MODULES:
        matches = tasks_using(module, tasks)
        assert matches, f"fleet preflight no longer uses {module}"
        for task in matches:
            assert task.get("delegate_to") == "localhost", task["name"]
            assert task.get("no_log") is True, task["name"]


def test_problem_classification_does_not_parse_display_messages() -> None:
    tasks = yaml.safe_load(PREFLIGHT_TASKS.read_text(encoding="utf-8"))
    observation_derivation = next(
        task
        for task in tasks
        if task["name"]
        == "Derive per-target observations from the common Proxmox observation"
    )
    derivation = observation_derivation["ansible.builtin.set_fact"][
        "proxmox_fleet_target_observations"
    ]

    assert "problem.cause_hosts" in derivation
    assert "problem.message" not in derivation
