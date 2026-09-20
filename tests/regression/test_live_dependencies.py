"""Each live operation reconciles what it consumes, and nothing else."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.live_dependencies import (  # noqa: E402
    LIVE_OPERATIONS,
    DependencyReconciliationError,
    UnsupportedLiveOperation,
    reconcile,
)

PUBLIC_COMMANDS = ("run.sh", "inspect.sh", "recover.sh")
PLAYBOOK_TOKEN = re.compile(r"site\.yml|playbooks/[A-Za-z0-9_-]+\.yml")
ANSIBLE_CFG = """[defaults]
collections_path = collections
roles_path = playbooks/roles:.ansible/roles

[ssh_connection]
control_path = .ansible/cp/%%h-%%p-%%r
"""

FAKE_UV = """#!/usr/bin/env python3
import os
import sys

arguments = sys.argv[1:]
while arguments and arguments[0] in ("run", "--locked"):
    arguments.pop(0)
os.execvp(arguments[0], arguments)
"""

# Writes whatever version GALAXY_INSTALLS_VERSION names, so a test can stage an
# installer that "succeeds" while leaving the wrong version behind.
FAKE_GALAXY = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
Path(os.environ["GALAXY_LOG"]).open("a").write(" ".join(arguments) + "\\n")
if os.environ.get("GALAXY_EXIT"):
    raise SystemExit(int(os.environ["GALAXY_EXIT"]))

install_path = Path(arguments[arguments.index("-p") + 1])
if arguments[0] == "collection":
    name, version = arguments[2].split(":")
    version = os.environ.get("GALAXY_INSTALLS_VERSION", version)
    namespace, collection = name.split(".", 1)
    manifest = install_path / "ansible_collections" / namespace / collection
    manifest.mkdir(parents=True, exist_ok=True)
    (manifest / "MANIFEST.json").write_text(
        json.dumps({"collection_info": {"version": version}}), encoding="utf-8"
    )
else:
    import re

    requirements = Path(arguments[arguments.index("-r") + 1]).read_text(encoding="utf-8")
    for name, declared in re.findall(
        r"name:\\s*(\\S+)\\s*\\n\\s*version:\\s*(\\S+)", requirements
    ):
        version = os.environ.get("GALAXY_INSTALLS_VERSION", declared)
        meta = install_path / name / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / ".galaxy_install_info").write_text(
            f"version: {version}\\n", encoding="utf-8"
        )
"""


def declared(relative: str, key: str) -> dict[str, str]:
    document = yaml.safe_load((REPO_ROOT / relative).read_text(encoding="utf-8"))
    return {entry["name"]: str(entry["version"]) for entry in document[key]}


@pytest.fixture
def fixture_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "ansible.cfg").write_text(ANSIBLE_CFG, encoding="utf-8")

    fixture_bin = tmp_path / "bin"
    fixture_bin.mkdir()
    for name, source in (("uv", FAKE_UV), ("ansible-galaxy", FAKE_GALAXY)):
        executable = fixture_bin / name
        executable.write_text(source, encoding="utf-8")
        executable.chmod(0o755)

    monkeypatch.setenv("PATH", f"{fixture_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GALAXY_LOG", str(tmp_path / "galaxy.log"))
    monkeypatch.setenv(
        "HOMELAB_IAC_COLLECTION_REQUIREMENTS", str(project_root / "collections.yml")
    )
    monkeypatch.setenv("HOMELAB_IAC_ROLE_REQUIREMENTS", str(project_root / "roles.yml"))
    monkeypatch.delenv("ANSIBLE_COLLECTIONS_PATH", raising=False)
    monkeypatch.delenv("ANSIBLE_ROLES_PATH", raising=False)
    return project_root


def declare(project_root: Path, collections: dict[str, str], roles: dict[str, str]) -> None:
    (project_root / "collections.yml").write_text(
        yaml.safe_dump(
            {"collections": [{"name": name, "version": v} for name, v in collections.items()]}
        ),
        encoding="utf-8",
    )
    (project_root / "roles.yml").write_text(
        yaml.safe_dump({"roles": [{"name": name, "version": v} for name, v in roles.items()]}),
        encoding="utf-8",
    )


def install_collection(project_root: Path, name: str, version: str) -> None:
    namespace, collection = name.split(".", 1)
    manifest = (
        project_root / "collections" / "ansible_collections" / namespace / collection
    )
    manifest.mkdir(parents=True)
    (manifest / "MANIFEST.json").write_text(
        json.dumps({"collection_info": {"version": version}}), encoding="utf-8"
    )


def installed_collection(project_root: Path, name: str) -> str:
    namespace, collection = name.split(".", 1)
    manifest = (
        project_root
        / "collections"
        / "ansible_collections"
        / namespace
        / collection
        / "MANIFEST.json"
    )
    return json.loads(manifest.read_text(encoding="utf-8"))["collection_info"]["version"]


def galaxy_invocations() -> list[str]:
    log = Path(os.environ["GALAXY_LOG"])
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_registry_covers_exactly_the_publicly_reachable_live_playbooks() -> None:
    reachable = {
        token
        for command in PUBLIC_COMMANDS
        for token in PLAYBOOK_TOKEN.findall(
            (REPO_ROOT / command).read_text(encoding="utf-8")
        )
    }
    assert reachable == set(LIVE_OPERATIONS)
    for playbook in LIVE_OPERATIONS:
        assert (REPO_ROOT / playbook).is_file()


def test_every_consumed_dependency_is_declared_with_an_exact_pin() -> None:
    """An undeclared name reconciles to nothing, so a typo must fail here."""
    collections = declared("collections/requirements.yml", "collections")
    roles = declared("requirements/roles.yml", "roles")
    for operation in LIVE_OPERATIONS.values():
        assert set(operation.collections) <= set(collections)
        assert set(operation.roles) <= set(roles)


def test_docker_role_is_claimed_only_by_configure_capable_operations() -> None:
    assert LIVE_OPERATIONS["playbooks/provision-lxcs.yml"].roles == ()
    for playbook in ("site.yml", "playbooks/configure-lxcs.yml"):
        assert "geerlingguy.docker" in LIVE_OPERATIONS[playbook].roles

    for playbook in ("playbooks/validate-credentials.yml", "playbooks/proxmox_api_check.yml"):
        operation = LIVE_OPERATIONS[playbook]
        assert operation.collections == ()
        assert operation.roles == ()
        assert operation.uses_ssh is False


def test_unsupported_pair_is_rejected_before_any_reconciliation(
    fixture_project: Path,
) -> None:
    with pytest.raises(UnsupportedLiveOperation) as failure:
        reconcile("control-node", "site.yml", project_root=fixture_project)
    assert "Unsupported prerequisite layers 'control-node'" in str(failure.value)
    assert "site.yml" in str(failure.value)
    assert galaxy_invocations() == []


def test_missing_consumed_collection_is_installed_at_the_declared_version(
    fixture_project: Path,
) -> None:
    declare(fixture_project, {"community.proxmox": "2.0.0"}, {})

    reconcile(
        "control-node,proxmox-host",
        "playbooks/provision-lxcs.yml",
        project_root=fixture_project,
    )

    assert installed_collection(fixture_project, "community.proxmox") == "2.0.0"
    assert galaxy_invocations() == [
        "collection install community.proxmox:2.0.0 "
        f"-p {fixture_project / 'collections'} --force"
    ]


def test_drifting_consumed_collection_is_forced_to_the_declared_version(
    fixture_project: Path,
) -> None:
    declare(fixture_project, {"community.proxmox": "2.0.0"}, {})
    install_collection(fixture_project, "community.proxmox", "1.6.0")

    reconcile(
        "control-node,proxmox-host",
        "playbooks/provision-lxcs.yml",
        project_root=fixture_project,
    )

    assert installed_collection(fixture_project, "community.proxmox") == "2.0.0"
    assert "--force" in galaxy_invocations()[0]


def test_matching_consumed_collection_is_left_alone(fixture_project: Path) -> None:
    declare(fixture_project, {"community.proxmox": "2.0.0"}, {})
    install_collection(fixture_project, "community.proxmox", "2.0.0")

    reconcile(
        "control-node,proxmox-host",
        "playbooks/provision-lxcs.yml",
        project_root=fixture_project,
    )

    assert galaxy_invocations() == []


def test_install_that_leaves_the_wrong_version_fails_naming_the_playbook(
    fixture_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    declare(fixture_project, {"community.proxmox": "2.0.0"}, {})
    monkeypatch.setenv("GALAXY_INSTALLS_VERSION", "1.6.0")

    with pytest.raises(DependencyReconciliationError) as failure:
        reconcile(
            "control-node,proxmox-host",
            "playbooks/provision-lxcs.yml",
            project_root=fixture_project,
        )

    message = str(failure.value)
    assert "playbooks/provision-lxcs.yml" in message
    assert "community.proxmox 2.0.0" in message
    assert "1.6.0" in message


def test_failing_installer_fails_naming_the_playbook(
    fixture_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    declare(fixture_project, {"community.proxmox": "2.0.0"}, {})
    monkeypatch.setenv("GALAXY_EXIT", "3")

    with pytest.raises(DependencyReconciliationError) as failure:
        reconcile(
            "control-node,proxmox-host",
            "playbooks/provision-lxcs.yml",
            project_root=fixture_project,
        )

    assert "playbooks/provision-lxcs.yml" in str(failure.value)
    assert "community.proxmox 2.0.0" in str(failure.value)


def test_consumed_external_role_is_reconciled_and_verified(
    fixture_project: Path,
) -> None:
    declare(
        fixture_project,
        {name: "9.9.9" for name in LIVE_OPERATIONS["site.yml"].collections},
        {"geerlingguy.docker": "7.9.0"},
    )
    for name in LIVE_OPERATIONS["site.yml"].collections:
        install_collection(fixture_project, name, "9.9.9")

    reconcile("control-node,proxmox-host", "site.yml", project_root=fixture_project)

    install_info = (
        fixture_project
        / ".ansible"
        / "roles"
        / "geerlingguy.docker"
        / "meta"
        / ".galaxy_install_info"
    )
    assert "version: 7.9.0" in install_info.read_text(encoding="utf-8")


def test_unconsumed_dependency_drift_does_not_block_the_operation(
    fixture_project: Path,
) -> None:
    """The acceptance criterion: shared declarations are not a shared contract."""
    declare(
        fixture_project,
        {"community.proxmox": "2.0.0", "community.crypto": "3.3.0"},
        {"geerlingguy.docker": "7.9.0"},
    )
    install_collection(fixture_project, "community.proxmox", "2.0.0")
    install_collection(fixture_project, "community.crypto", "0.0.1")

    reconcile(
        "control-node,proxmox-host",
        "playbooks/provision-lxcs.yml",
        project_root=fixture_project,
    )

    assert galaxy_invocations() == []
    assert installed_collection(fixture_project, "community.crypto") == "0.0.1"


def test_api_only_operation_needs_neither_declarations_nor_a_control_path(
    fixture_project: Path,
) -> None:
    reconcile(
        "control-node", "playbooks/proxmox_api_check.yml", project_root=fixture_project
    )

    assert galaxy_invocations() == []
    assert not (fixture_project / ".ansible" / "cp").exists()


def test_ssh_operation_creates_the_configured_control_path_parent(
    fixture_project: Path,
) -> None:
    reconcile(
        "control-node", "playbooks/lab-connectivity.yml", project_root=fixture_project
    )

    control_path_parent = fixture_project / ".ansible" / "cp"
    assert control_path_parent.is_dir()
    assert control_path_parent.stat().st_mode & 0o777 == 0o700


def test_live_path_never_directs_the_caller_to_the_retired_bootstrap() -> None:
    live_sources = [
        REPO_ROOT / "scripts" / "live_dependencies.py",
        REPO_ROOT / "scripts" / "lib" / "live-execution.sh",
        REPO_ROOT / "playbooks" / "controller-prerequisites.yml",
        REPO_ROOT / "playbooks" / "proxmox-host-prerequisites.yml",
        *(REPO_ROOT / command for command in PUBLIC_COMMANDS),
    ]
    for source in live_sources:
        assert "setup.sh bootstrap" not in source.read_text(encoding="utf-8"), source


def test_shared_live_boundary_delegates_the_pairing_decision(
    tmp_path: Path,
) -> None:
    boundary = (REPO_ROOT / "scripts" / "lib" / "live-execution.sh").read_text(
        encoding="utf-8"
    )
    assert "scripts.live_dependencies" in boundary
    assert "$prerequisite_layers:$playbook" not in boundary

    script = tmp_path / "boundary.sh"
    script.write_text(
        "set -euo pipefail\n"
        f"source {REPO_ROOT / 'scripts/lib/live-execution.sh'}\n"
        'run_live_playbook shared control-node playbooks/configure-lxcs.yml\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert (
        "Unsupported prerequisite layers 'control-node' for live playbook "
        "'playbooks/configure-lxcs.yml'" in result.stderr
    )
