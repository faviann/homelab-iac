from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_PROBE = REPO_ROOT / "playbooks" / "tasks" / "probe_lxc_release.yml"
LIFECYCLE_INSPECT = (
    REPO_ROOT
    / "playbooks"
    / "roles"
    / "provisioning"
    / "proxmox_lxc_lifecycle"
    / "tasks"
    / "inspect.yml"
)
LIFECYCLE_REOBSERVE = LIFECYCLE_INSPECT.with_name("reobserve.yml")
LIFECYCLE_RELEASE_OBSERVATION = LIFECYCLE_INSPECT.with_name("observe_release.yml")


def test_release_probe_parsing_lives_in_shared_task() -> None:
    shared = SHARED_PROBE.read_text(encoding="utf-8")
    inspect = LIFECYCLE_INSPECT.read_text(encoding="utf-8")
    reobserve = LIFECYCLE_REOBSERVE.read_text(encoding="utf-8")
    release_observation = LIFECYCLE_RELEASE_OBSERVATION.read_text(encoding="utf-8")

    assert "/etc/os-release" in shared
    assert "regex_findall('([0-9]+)')" in shared
    assert "observe_release.yml" in inspect
    assert "observe_release.yml" in reobserve
    assert "proxmox_lifecycle_release_probe_tasks_file" in release_observation
    assert 'exec_command: ". /etc/os-release' not in inspect
    assert 'exec_command: ". /etc/os-release' not in reobserve
    assert 'exec_command: ". /etc/os-release' not in release_observation
