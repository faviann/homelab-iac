from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_PROBE = REPO_ROOT / "playbooks" / "tasks" / "probe_lxc_release.yml"
VALIDATION_TASKS = REPO_ROOT / "playbooks" / "tasks" / "proxmox_validation.yml"
LIFECYCLE_INSPECT = (
    REPO_ROOT
    / "playbooks"
    / "roles"
    / "provisioning"
    / "proxmox_lxc_lifecycle"
    / "tasks"
    / "inspect.yml"
)


def test_release_probe_parsing_lives_in_shared_task() -> None:
    shared = SHARED_PROBE.read_text(encoding="utf-8")
    validation = VALIDATION_TASKS.read_text(encoding="utf-8")
    inspect = LIFECYCLE_INSPECT.read_text(encoding="utf-8")

    assert "/etc/os-release" in shared
    assert "regex_findall('([0-9]+)')" in shared
    assert "probe_lxc_release.yml" in validation
    assert "probe_lxc_release.yml" in inspect
    assert 'exec_command: ". /etc/os-release' not in validation
    assert 'exec_command: ". /etc/os-release' not in inspect
