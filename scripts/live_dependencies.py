"""Reconcile the repository dependencies consumed by one live playbook.

The registry is deliberately small and explicit. Each supported live playbook
names only the collections and external roles it reaches. Dependencies install
into the repository-owned paths configured by ``ansible.cfg`` and are verified
at their exact declared pins before Ansible starts.

``community.crypto`` is declared but consumed by no live operation. The Docker
role is reached only by configure-capable lifecycle operations. The lifecycle
preflight consumes ``community.proxmox`` for every lifecycle intent.

An SSH-consuming operation also requires the machine-global controller SSH
identity. This module verifies that identity and never creates, restores, or
replaces it.
"""

from __future__ import annotations

import argparse
import enum
import fcntl
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COLLECTION_REQUIREMENTS = Path("collections/requirements.yml")
ROLE_REQUIREMENTS = Path("requirements/roles.yml")
COLLECTIONS_PATH = Path("collections")
ROLES_PATH = Path(".ansible/roles")
SSH_CONTROL_PATH_PARENT = Path(".ansible/cp")
CONTROLLER_IDENTITY_RELATIVE_PATH = Path(".ansible/ssh/proxmox_lxc")


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
    "site.yml": LiveOperation(CONFIGURE_COLLECTIONS, CONFIGURE_ROLES, True),
    "playbooks/provision-lxcs.yml": LiveOperation(
        ("community.proxmox",), (), True
    ),
    "playbooks/configure-lxcs.yml": LiveOperation(
        CONFIGURE_COLLECTIONS, CONFIGURE_ROLES, True
    ),
    "playbooks/validate-infrastructure.yml": LiveOperation(
        ("community.proxmox",), (), True
    ),
    "playbooks/add-ssh-keys-to-lxcs.yml": LiveOperation((), (), True),
    "playbooks/enroll-proxmox-host-ssh.yml": LiveOperation((), (), True),
    "playbooks/validate-credentials.yml": LiveOperation((), (), False),
    "playbooks/lab-connectivity.yml": LiveOperation((), (), True),
    "playbooks/proxmox_api_check.yml": LiveOperation((), (), False),
}


def select_operation(playbook: str) -> LiveOperation:
    operation = LIVE_OPERATIONS.get(playbook)
    if operation is None:
        raise UnsupportedLiveOperation(f"Unsupported live playbook '{playbook}'")
    return operation


def _declared_versions(path: Path, key: str) -> dict[str, str]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}
    return {
        str(entry["name"]): str(entry["version"])
        for entry in document.get(key) or []
        if isinstance(entry, dict) and "name" in entry and "version" in entry
    }


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


def _installed_role_version(install_path: Path, name: str) -> str | None:
    install_info = install_path / name / "meta" / ".galaxy_install_info"
    try:
        document = yaml.safe_load(install_info.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    version = document.get("version") if isinstance(document, dict) else None
    return None if version is None else str(version)


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


def _reconcile_collections(
    project_root: Path, playbook: str, names: tuple[str, ...]
) -> None:
    if not names:
        return
    requirements = project_root / COLLECTION_REQUIREMENTS
    install_path = project_root / COLLECTIONS_PATH
    declared = _declared_versions(requirements, "collections")
    for name in names:
        version = _declared_version(
            declared, requirements, playbook, "collection", name
        )
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
                f"Live playbook '{playbook}' consumes Ansible collection "
                f"{name} {version}, but {install_path} holds "
                f"{installed or 'no manifest'} after reconciliation."
            )


def _reconcile_roles(
    project_root: Path, playbook: str, names: tuple[str, ...]
) -> None:
    if not names:
        return
    requirements = project_root / ROLE_REQUIREMENTS
    install_path = project_root / ROLES_PATH
    declared = _declared_versions(requirements, "roles")
    for name in names:
        version = _declared_version(declared, requirements, playbook, "role", name)
        if _installed_role_version(install_path, name) == version:
            continue
        _run_galaxy(
            project_root,
            playbook,
            f"Ansible role {name} {version}",
            ["role", "install", "--force", f"{name},{version}", "-p", str(install_path)],
        )
        installed = _installed_role_version(install_path, name)
        if installed != version:
            raise DependencyReconciliationError(
                f"Live playbook '{playbook}' consumes Ansible role {name} {version}, "
                f"but {install_path} holds {installed or 'no install record'} "
                "after reconciliation."
            )


class ControllerIdentity(enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    INCONSISTENT = "inconsistent"


CONTROLLER_IDENTITY_CREATION = (
    "mkdir -p -m 700 ~/.ansible/ssh && ssh-keygen -t ed25519 -N '' -f "
    "~/.ansible/ssh/proxmox_lxc -C ansible-control@$(hostname)"
)

CONTROLLER_IDENTITY_GUIDANCE = (
    "Restore the previously trusted private key and its .pub from your own "
    "backup of this controller; minting a new identity loses the trust the "
    "fleet already grants, and managed hosts will still reject it. On a first "
    f"controller, create one explicitly: {CONTROLLER_IDENTITY_CREATION}. Neither "
    "restoring nor creating enrolls trust on managed infrastructure; "
    "./recover.sh proxmox-host-ssh enrolls the Proxmox host and "
    "./recover.sh ssh-keys enrolls existing LXCs."
)


def _classify_controller_identity(private_key: Path) -> ControllerIdentity:
    if not private_key.is_file():
        return ControllerIdentity.ABSENT
    public_key = private_key.with_name(f"{private_key.name}.pub")
    try:
        declared_lines = public_key.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ControllerIdentity.INCONSISTENT
    # ssh_key_shared enrolls this file whole, so a second key line would reach
    # authorized_keys on every managed host without ever being derived from the
    # private key. The comment field is the operator's, so only the key type
    # and material are compared.
    declared = [line.split() for line in declared_lines if line.strip()]
    if len(declared) != 1:
        return ControllerIdentity.INCONSISTENT
    # -P '' supplies the passphrase, so a protected key fails instead of
    # prompting. Closing stdin is not enough: ssh-keygen reaches for SSH_ASKPASS
    # and then /dev/tty, and would stall the live boundary on either. The
    # captured output never reaches the operator.
    derived = subprocess.run(
        ["ssh-keygen", "-y", "-P", "", "-f", str(private_key)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if derived.returncode != 0 or derived.stdout.split()[:2] != declared[0][:2]:
        return ControllerIdentity.INCONSISTENT
    return ControllerIdentity.PRESENT


def _require_controller_identity(playbook: str) -> None:
    private_key = Path.home() / CONTROLLER_IDENTITY_RELATIVE_PATH
    state = _classify_controller_identity(private_key)
    if state is ControllerIdentity.PRESENT:
        return
    if state is ControllerIdentity.ABSENT:
        condition = f"the controller SSH identity at {private_key}, which is absent"
    else:
        condition = (
            f"the controller SSH identity at {private_key}, which is "
            f"inconsistent: {private_key}.pub must be readable and hold "
            f"exactly the one public key this private key derives"
        )
    raise DependencyReconciliationError(
        f"Live playbook '{playbook}' consumes {condition}. This is a "
        "controller-identity problem on this machine, not a managed-host "
        f"trust failure. {CONTROLLER_IDENTITY_GUIDANCE}"
    )


def _ensure_ssh_control_path_parent(project_root: Path, playbook: str) -> None:
    parent = project_root / SSH_CONTROL_PATH_PARENT
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise DependencyReconciliationError(
            f"Live playbook '{playbook}' requires SSH control-path directory "
            f"{parent}, which could not be created: {error}"
        ) from error


def reconcile(playbook: str, *, project_root: Path = PROJECT_ROOT) -> None:
    operation = select_operation(playbook)
    if operation.collections or operation.roles:
        lock_path = project_root / ".ansible/dependencies.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Read-only live operations share the lifecycle lock and may otherwise
        # run ansible-galaxy concurrently against the same worktree paths.
        with lock_path.open("a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            _reconcile_collections(project_root, playbook, operation.collections)
            _reconcile_roles(project_root, playbook, operation.roles)
    if operation.uses_ssh:
        _require_controller_identity(playbook)
        _ensure_ssh_control_path_parent(project_root, playbook)


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
