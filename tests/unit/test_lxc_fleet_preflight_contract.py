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


def test_common_proxmox_observation_runs_in_check_mode() -> None:
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

    assert query["check_mode"] is False
