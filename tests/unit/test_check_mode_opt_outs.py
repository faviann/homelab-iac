#!/usr/bin/env python3
"""Every production task that opts out of check mode is an acknowledged read-only probe.

`check_mode: false` makes a task run for real under `./run.sh --check`. That is
correct for read-only probes whose results the rest of the role needs, and wrong
for anything that mutates. The behavioral check-mode regressions prove the
acknowledged probes stay dry-run safe; this test makes a new opt-out an explicit
decision instead of something that can land unnoticed.
"""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ROLES_ROOT = REPO_ROOT / "playbooks/roles"

# (task file relative to the repository, task name) -> why it must run in check mode.
# Add an entry only after confirming the task is read-only.
ACKNOWLEDGED_OPT_OUTS: dict[tuple[str, str], str] = {
    ("playbooks/roles/config/lxc_docker_runtime/tasks/main.yml", "Verify Docker installation"):
        "version probe",
    ("playbooks/roles/config/lxc_docker_runtime/tasks/main.yml", "Verify Docker Compose installation"):
        "version probe",
    ("playbooks/roles/config/lxc_nvidia_runtime/tasks/main.yml", "Verify NVIDIA runtime is registered with Docker"):
        "docker info probe",
    ("playbooks/roles/config/lxc_workstation_baseline/tasks/origin_firewall.yml", "Resolve workstation origin firewall allowlist address"):
        "DNS lookup the firewall validation needs",
    ("playbooks/roles/config/lxc_workstation_baseline/tasks/persistent_home.yml", "Inspect existing mount status for persistent home paths"):
        "findmnt read the mount plan needs",
    ("playbooks/roles/infrastructure/proxmox_host_bootstrap/tasks/check_ssh.yml", "Test selected identity trust on Proxmox host"):
        "ssh reachability probe",
    ("playbooks/roles/infrastructure/proxmox_host_bootstrap/tasks/validation.yml", "Verify pct command works"):
        "read-only host validation",
    ("playbooks/roles/infrastructure/proxmox_host_bootstrap/tasks/validation.yml", "Check installed lxc-pve version"):
        "read-only host validation",
    ("playbooks/roles/infrastructure/proxmox_host_bootstrap/tasks/validation.yml", "Assert lxc-pve meets nested Docker minimum"):
        "assert over the probes above",
    ("playbooks/roles/infrastructure/proxmox_lxc_host_config/tasks/config_file_bind_mounts.yml", "Get current bind mounts"):
        "reads the pct config so check mode can report the diff",
    ("playbooks/roles/infrastructure/proxmox_lxc_host_config/tasks/config_file_wireguard.yml", "Get current WireGuard tun device access"):
        "reads the pct config so check mode can report the diff",
    ("playbooks/roles/infrastructure/proxmox_lxc_host_config/tasks/config_file_nvidia.yml", "Get current NVIDIA GPU configuration lines"):
        "reads the pct config so check mode can report the diff",
    ("playbooks/roles/infrastructure/proxmox_lxc_host_config/tasks/config_file_sysctls.yml", "Get current sysctl and AppArmor configuration"):
        "reads the pct config so check mode can report the diff",
    ("playbooks/roles/infrastructure/proxmox_lxc_host_config/tasks/config_file_idmap.yml", "Get current UID/GID ID mappings"):
        "reads the pct config so check mode can report the diff",
    ("playbooks/roles/provisioning/proxmox_lxc_fleet_preflight/tasks/main.yml", "Verify API observation permission for each targeted LXC"):
        "read-only GET; check mode must not treat an unauditable guest as absent",
}


def check_mode_opt_outs(document: object, relative_path: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    if isinstance(document, dict):
        if document.get("check_mode") is False:
            found.add((relative_path, str(document.get("name", "<unnamed task>"))))
        for child in document.values():
            found |= check_mode_opt_outs(child, relative_path)
    elif isinstance(document, list):
        for child in document:
            found |= check_mode_opt_outs(child, relative_path)
    return found


def test_every_check_mode_opt_out_in_production_roles_is_acknowledged() -> None:
    actual: set[tuple[str, str]] = set()
    for task_file in sorted(ROLES_ROOT.rglob("*.yml")):
        document = yaml.safe_load(task_file.read_text(encoding="utf-8"))
        actual |= check_mode_opt_outs(document, task_file.relative_to(REPO_ROOT).as_posix())

    unacknowledged = sorted(actual - ACKNOWLEDGED_OPT_OUTS.keys())
    assert not unacknowledged, (
        "check_mode: false makes these tasks run for real under ./run.sh --check. "
        "Confirm each one is read-only, then add it to ACKNOWLEDGED_OPT_OUTS with the reason:\n"
        + "\n".join(f"  {path}: {name}" for path, name in unacknowledged)
    )
