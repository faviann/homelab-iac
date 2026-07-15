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


def test_common_proxmox_observation_uses_proxmox_module_contract() -> None:
    tasks = yaml.safe_load(PREFLIGHT_TASKS.read_text(encoding="utf-8"))
    observation_block = next(
        task
        for task in tasks
        if task["name"] == "Observe Proxmox once for the targeted LXC set"
    )
    query = next(
        task
        for task in observation_block["block"]
        if task["name"] == "Query the common Proxmox LXC observation"
    )
    adoption = next(
        task
        for task in observation_block["block"]
        if task["name"] == "Adopt the common Proxmox LXC observation"
    )

    assert observation_block["module_defaults"] == {
        "group/community.proxmox.proxmox": "{{ _proxmox_auth }}"
    }
    assert set(observation_block["vars"]["_proxmox_auth"]) == {
        "api_host",
        "api_port",
        "api_user",
        "api_token_id",
        "api_token_secret",
        "validate_certs",
    }
    assert query["community.proxmox.proxmox_vm_info"] == {
        "type": "lxc",
    }
    assert query["delegate_to"] == "localhost"
    assert query["changed_when"] is False
    assert query["no_log"] is True
    assert "check_mode" not in query
    assert "proxmox_fleet_observation_response.proxmox_vms" in adoption[
        "ansible.builtin.set_fact"
    ]["proxmox_fleet_common_observation"]


def test_problem_classification_does_not_parse_display_messages() -> None:
    source = PREFLIGHT_TASKS.read_text(encoding="utf-8")
    tasks = yaml.safe_load(source)
    observation_derivation = next(
        task
        for task in tasks
        if task["name"]
        == "Derive per-target observations from the common Proxmox observation"
    )
    derivation = observation_derivation["ansible.builtin.set_fact"][
        "proxmox_fleet_target_observations"
    ]

    assert "proxmox_fleet_preflight_problem_records" in source
    assert "Classify targeted causes of fleet preflight problems" not in source
    assert "(\"'\" ~ host ~ \"'\") in problem" not in source
    assert "problem.cause_hosts" in derivation
    assert "problem.message" not in derivation
