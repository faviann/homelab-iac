"""Reconcile the worktree dependencies one live playbook semantically consumes.

`LIVE_OPERATIONS` is the single table pairing each supported playbook with the
collections, external roles, and runtime directories that invocation actually
reaches. The shared live boundary in
`scripts/lib/live-execution.sh` consults it instead of carrying a second copy of
the pairing knowledge, so a declared-but-unconsumed dependency never blocks an
unrelated operation.

How the consumed sets were derived. `playbooks/proxmox-host-prerequisites.yml`
pins `proxmox_validate_api: false`, so the L3 layer alone never resolves
`community.proxmox`; the lifecycle facade's fleet preflight does, for every
intent, which is why the provision-only and plan operations still claim it.
`geerlingguy.docker` is reached only through `config/lxc_docker_runtime`, so
only configure-capable intents claim it. `community.library_inventory_filtering_v1`
is a hard dependency of `community.docker` and travels with it.
`community.crypto` is declared but consumed by nothing, so no operation claims
it; under ADR 0011 that is the intended outcome, not an oversight.

Path resolution uses Ansible's effective configuration in the same working
directory and environment as the following playbook process. This includes
`ANSIBLE_CONFIG`, environment overrides, and Ansible's relative-path expansion.
`collections/requirements.yml` and `requirements/roles.yml` are the only
declaration files, and a consumed dependency they do not pin is an error rather
than a no-op, so a registry typo or a deleted pin surfaces here instead of as a
missing module inside Ansible. An adjacent collection or role takes precedence
over configured paths. Existing roles are reconciled in search order; an absent
role is installed in the last configured directory (normally `.ansible/roles`).
Otherwise collections are installed in the first configured directory, ahead
of later configured paths and Python's collection search paths. Each dependency
is installed by name at its own pin, never through the whole declaration file,
so one operation's install can never be blocked by a role or collection it does
not consume.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ansible.config.manager import ConfigManager
from ansible.plugins.connection.ssh import DOCUMENTATION as SSH_DOCUMENTATION
from ansible.utils.path import unfrackpath
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COLLECTION_REQUIREMENTS = Path("collections/requirements.yml")
ROLE_REQUIREMENTS = Path("requirements/roles.yml")


@dataclass(frozen=True)
class LiveOperation:
    collections: tuple[str, ...]
    roles: tuple[str, ...]
    uses_ssh: bool


class UnsupportedLiveOperation(Exception):
    """The caller asked for a playbook the live-operation registry rejects."""


class DependencyReconciliationError(Exception):
    """A consumed dependency could not be established at its declared version."""


CONFIGURE_COLLECTIONS = (
    "ansible.posix",
    "community.docker",
    "community.library_inventory_filtering_v1",
    "community.proxmox",
)
CONFIGURE_ROLES = ("geerlingguy.docker",)

LIVE_OPERATIONS: dict[str, LiveOperation] = {
    "site.yml": LiveOperation(
        collections=CONFIGURE_COLLECTIONS,
        roles=CONFIGURE_ROLES,
        uses_ssh=True,
    ),
    "playbooks/provision-lxcs.yml": LiveOperation(
        collections=("community.proxmox",),
        roles=(),
        uses_ssh=True,
    ),
    "playbooks/configure-lxcs.yml": LiveOperation(
        collections=CONFIGURE_COLLECTIONS,
        roles=CONFIGURE_ROLES,
        uses_ssh=True,
    ),
    "playbooks/validate-infrastructure.yml": LiveOperation(
        collections=("community.proxmox",),
        roles=(),
        uses_ssh=True,
    ),
    "playbooks/add-ssh-keys-to-lxcs.yml": LiveOperation(
        collections=(),
        roles=(),
        uses_ssh=True,
    ),
    "playbooks/validate-credentials.yml": LiveOperation(
        collections=(),
        roles=(),
        uses_ssh=False,
    ),
    "playbooks/lab-connectivity.yml": LiveOperation(
        collections=(),
        roles=(),
        uses_ssh=True,
    ),
    "playbooks/proxmox_api_check.yml": LiveOperation(
        collections=(),
        roles=(),
        uses_ssh=False,
    ),
}


def select_operation(playbook: str) -> LiveOperation:
    operation = LIVE_OPERATIONS.get(playbook)
    if operation is None:
        raise UnsupportedLiveOperation(f"Unsupported live playbook '{playbook}'")
    return operation


def collection_install_path(
    project_root: Path, config: ConfigManager, playbook: str, name: str
) -> Path:
    adjacent = (project_root / playbook).parent / "collections"
    namespace, collection = name.split(".", 1)
    if (adjacent / "ansible_collections" / namespace / collection).exists():
        return adjacent
    configured = Path(config.get_config_value("COLLECTIONS_PATHS")[0])
    # Ansible accepts either a collection root or its ansible_collections child.
    return configured.parent if configured.name == "ansible_collections" else configured


def role_install_path(
    project_root: Path, config: ConfigManager, playbook: str, name: str
) -> Path:
    configured = [Path(entry) for entry in config.get_config_value("DEFAULT_ROLES_PATH")]
    adjacent = (project_root / playbook).parent / "roles"
    return next(
        (path for path in [adjacent, *configured] if (path / name).exists()),
        configured[-1],
    )


def _declared_versions(path: Path, key: str) -> dict[str, str]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}
    declared: dict[str, str] = {}
    for entry in document.get(key) or []:
        if isinstance(entry, dict) and "name" in entry and "version" in entry:
            declared[str(entry["name"])] = str(entry["version"])
    return declared


def _installed_collection_version(install_path: Path, name: str) -> str | None:
    namespace, collection = name.split(".", 1)
    manifest = (
        install_path / "ansible_collections" / namespace / collection / "MANIFEST.json"
    )
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = document.get("collection_info", {}).get("version")
    return None if version is None else str(version)


def _installed_role_version(roles_path: Path, name: str) -> str | None:
    install_info = roles_path / name / "meta" / ".galaxy_install_info"
    try:
        document = yaml.safe_load(install_info.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    version = document.get("version") if isinstance(document, dict) else None
    return None if version is None else str(version)


def _run_galaxy(
    project_root: Path, playbook: str, dependency: str, arguments: list[str]
) -> None:
    completed = subprocess.run(
        ["uv", "run", "--locked", "ansible-galaxy", *arguments],
        cwd=project_root,
        check=False,
    )
    if completed.returncode != 0:
        raise DependencyReconciliationError(
            f"Live playbook '{playbook}' consumes {dependency}, "
            f"which ansible-galaxy failed to install (exit {completed.returncode})."
        )


def _declared_version(
    declared: dict[str, str], requirements: Path, playbook: str, kind: str, name: str
) -> str:
    version = declared.get(name)
    if version is None:
        raise DependencyReconciliationError(
            f"Live playbook '{playbook}' consumes Ansible {kind} {name}, "
            f"which {requirements} does not pin."
        )
    return version


def _reconcile_collections(
    project_root: Path,
    config: ConfigManager,
    playbook: str,
    names: tuple[str, ...],
) -> None:
    if not names:
        return
    requirements = project_root / COLLECTION_REQUIREMENTS
    declared = _declared_versions(requirements, "collections")
    for name in names:
        version = _declared_version(
            declared, requirements, playbook, "collection", name
        )
        install_path = collection_install_path(project_root, config, playbook, name)
        if _installed_collection_version(install_path, name) == version:
            continue
        _run_galaxy(
            project_root,
            playbook,
            f"Ansible collection {name} {version}",
            [
                "collection",
                "install",
                f"{name}:{version}",
                "-p",
                str(install_path),
                "--force",
            ],
        )
        installed = _installed_collection_version(install_path, name)
        if installed != version:
            raise DependencyReconciliationError(
                f"Live playbook '{playbook}' consumes Ansible collection {name} {version}, "
                f"but {install_path} holds {installed or 'no manifest'} after reconciliation."
            )


def _reconcile_roles(
    project_root: Path,
    config: ConfigManager,
    playbook: str,
    names: tuple[str, ...],
) -> None:
    if not names:
        return
    requirements = project_root / ROLE_REQUIREMENTS
    declared = _declared_versions(requirements, "roles")
    for name in names:
        version = _declared_version(declared, requirements, playbook, "role", name)
        roles_path = role_install_path(project_root, config, playbook, name)
        if _installed_role_version(roles_path, name) == version:
            continue
        _run_galaxy(
            project_root,
            playbook,
            f"Ansible role {name} {version}",
            ["role", "install", "--force", f"{name},{version}", "-p", str(roles_path)],
        )
        installed = _installed_role_version(roles_path, name)
        if installed != version:
            raise DependencyReconciliationError(
                f"Live playbook '{playbook}' consumes Ansible role {name} {version}, "
                f"but {roles_path} holds {installed or 'no install record'} after reconciliation."
            )


def _ensure_control_path_parent(config: ConfigManager, playbook: str) -> None:
    config.initialize_plugin_configuration_definitions(
        "connection", "ssh", yaml.safe_load(SSH_DOCUMENTATION)["options"]
    )
    directory = unfrackpath(
        config.get_config_value(
            "control_path_dir", plugin_type="connection", plugin_name="ssh"
        )
    )
    control_path = config.get_config_value(
        "control_path", plugin_type="connection", plugin_name="ssh"
    )
    parent = (
        Path(control_path % {"directory": directory}).expanduser().parent
        if control_path
        else Path(directory)
    )
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise DependencyReconciliationError(
            f"Live playbook '{playbook}' consumes the SSH control path {control_path}, "
            f"whose parent directory {parent} could not be created: {error}"
        ) from error


def reconcile(playbook: str, *, project_root: Path = PROJECT_ROOT) -> None:
    operation = select_operation(playbook)
    config = ConfigManager()
    lock_path = project_root / ".ansible" / "dependencies.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        _reconcile_collections(project_root, config, playbook, operation.collections)
        _reconcile_roles(project_root, config, playbook, operation.roles)
        if operation.uses_ssh:
            _ensure_control_path_parent(config, playbook)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.live_dependencies")
    parser.add_argument("--playbook", required=True)
    arguments = parser.parse_args(argv)
    try:
        reconcile(arguments.playbook)
    except UnsupportedLiveOperation as error:
        print(error, file=sys.stderr)
        return 2
    except DependencyReconciliationError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
