"""Credential consumers load the vault."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from ansible.parsing.vault import VaultLib, VaultSecret
import pytest
import yaml

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_TOKEN = "controlled-api-token-value"


@pytest.mark.parametrize("credential_state", ["valid", "missing", "placeholder", "wrong-passphrase"])
def test_api_consumer_checks_credentials_before_effects(
    tmp_path: Path, credential_state: str,
) -> None:
    password = tmp_path / "vault-pass"
    password.write_text("controlled-vault-password\n", encoding="utf-8")
    credentials = {
        "vault_proxmox_api_user": "controlled-user@pam",
        "vault_proxmox_api_token_id": "controlled-token-id",
        "vault_proxmox_api_token_secret": FIXTURE_TOKEN,
    }
    if credential_state == "missing":
        del credentials["vault_proxmox_api_token_secret"]
    elif credential_state == "placeholder":
        credentials["vault_proxmox_api_token_secret"] = "<REPLACE_ME>"
    vault = VaultLib([("default", VaultSecret(b"controlled-vault-password"))])
    (tmp_path / "vault.yml").write_bytes(vault.encrypt(yaml.safe_dump(credentials)))
    if credential_state == "wrong-passphrase":
        password.write_text("incorrect-fixture-password\n", encoding="utf-8")

    inventory = tmp_path / "inventory.yml"
    inventory.write_text(yaml.safe_dump({
        "all": {"hosts": {"consumer": {
            "ansible_connection": "local",
            "proxmox_api_user": "{{ vault_proxmox_api_user }}",
            "proxmox_api_token_id": "{{ vault_proxmox_api_token_id }}",
            "proxmox_api_token_secret": "{{ vault_proxmox_api_token_secret }}",
            "unselected_service_secret": "{{ vault_unselected_service_secret }}",
        }}},
    }), encoding="utf-8")
    effect = tmp_path / "effect"
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "consumer",
        "gather_facts": False,
        "tasks": [
            {"ansible.builtin.include_tasks": str(
                REPO_ROOT / "playbooks/tasks/proxmox_api_credentials.yml"
            )},
            {"ansible.builtin.copy": {"content": "effect", "dest": str(effect)}},
        ],
    }]), encoding="utf-8")
    command = ansible_playbook_command(supplies_own_inventory=True)
    result = subprocess.run(
        [*command, "-i", str(inventory), str(playbook), "-vvv", "--diff"],
        cwd=REPO_ROOT,
        env={**os.environ, "ANSIBLE_VAULT_PASSWORD_FILE": str(password)},
        capture_output=True, text=True, timeout=30,
    )
    output = result.stdout + result.stderr
    assert FIXTURE_TOKEN not in output
    assert "controlled-user@pam" not in output
    assert "controlled-token-id" not in output
    if credential_state == "valid":
        assert result.returncode == 0, output
        assert effect.exists()
    else:
        assert result.returncode != 0, output
        assert "Proxmox API credentials require" in output
        assert not effect.exists()
