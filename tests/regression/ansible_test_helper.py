"""Shared construction of credential-free Ansible regression environments."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/ansible"
FIXTURE_INVENTORY = FIXTURE_ROOT / "inventory.yml"
FIXTURE_VAULT_PASSWORD_FILE = FIXTURE_ROOT / "vault-pass"
ANSIBLE_PLAYBOOK = ["uv", "run", "--locked", "ansible-playbook"]


def ansible_playbook_command(
    *arguments: str,
    supplies_own_inventory: bool = False,
) -> list[str]:
    """Return a locked playbook command under the validation fixture boundary."""
    if (
        not supplies_own_inventory
        and os.environ.get("ANSIBLE_INVENTORY") != str(FIXTURE_INVENTORY)
    ):
        raise AssertionError(
            "ANSIBLE_INVENTORY is outside the fixture environment; "
            "run this test through ./validate.sh tests"
        )
    if os.environ.get("ANSIBLE_VAULT_PASSWORD_FILE") != str(
        FIXTURE_VAULT_PASSWORD_FILE
    ):
        raise AssertionError(
            "ANSIBLE_VAULT_PASSWORD_FILE is outside the fixture environment; "
            "run this test through ./validate.sh tests"
        )
    return [*ANSIBLE_PLAYBOOK, *arguments]


def write_controller_identity(home: Path, *, name: str = "proxmox_lxc") -> Path:
    """Generate a throwaway controller identity under a fixture ``HOME``."""
    private_key = home / ".ansible" / "ssh" / name
    private_key.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private_key),
         "-C", "regression-fixture"],
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    return private_key
