#!/usr/bin/env python3
"""Credential-free regressions for the shared origin firewall role."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from ansible_test_helper import ansible_playbook_command
from jinja2 import Environment, FileSystemLoader, StrictUndefined


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "regression" / "fixtures"
PLAYBOOK = FIXTURE_ROOT / "origin_firewall.yml"
INVENTORY = FIXTURE_ROOT / "origin_firewall_inventory.yml"
STUB_ROOT = FIXTURE_ROOT / "origin_firewall_assets"
TEMPLATES = REPO_ROOT / "playbooks/roles/config/lxc_origin_firewall/templates"
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)


def run_playbook(
    temp_root: str, stub_state: str, *extra_args: str
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PATH"] = f"{STUB_ROOT / 'bin'}:{environment['PATH']}"
    environment["ORIGIN_FIREWALL_STUB_STATE"] = stub_state
    command = [
        "unshare",
        "-Ur",
        *ANSIBLE_PLAYBOOK,
        "-i",
        str(INVENTORY),
        str(PLAYBOOK),
        "-f",
        "1",
        "-e",
        f"temp_root={temp_root}",
        *extra_args,
    ]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_lxc_origin_firewall_second_convergence_is_idempotent() -> None:
    with tempfile.TemporaryDirectory(prefix="origin-firewall-idempotency-") as temp_root:
        temp_path = Path(temp_root)
        stub_state_path = temp_path / "stub-state"
        stub_state_path.mkdir()
        stub_state = str(stub_state_path)
        first = run_playbook(temp_root, stub_state)

        first_output = f"{first.stdout}\n{first.stderr}"
        assert first.returncode == 0, first_output
        assert "failed=0" in first_output, first_output
        assert "Reload origin firewall" in first_output, first_output
        assert (stub_state_path / "apt").exists(), first_output
        assert (stub_state_path / "systemd").exists(), first_output
        assert (stub_state_path / "validated-rules").exists(), first_output

        nft_path = temp_path / "etc/nftables.d/custom-origin.nft"
        service_path = temp_path / "etc/systemd/system/custom-origin-firewall.service"
        assert nft_path.is_file(), first_output
        assert service_path.is_file(), first_output
        assert "elements = { 4001, 9119, 18789, 8788 }" in nft_path.read_text(encoding="utf-8")
        assert f"ExecStart=/usr/sbin/nft -f {nft_path}" in service_path.read_text(encoding="utf-8")

        second = run_playbook(temp_root, stub_state)

    second_output = f"{second.stdout}\n{second.stderr}"
    assert second.returncode == 0, second_output
    assert "changed=0" in second_output, second_output
    assert "failed=0" in second_output, second_output


def test_lxc_origin_firewall_unresolved_origin_keeps_existing_firewall() -> None:
    with tempfile.TemporaryDirectory(prefix="origin-firewall-resolution-") as temp_root:
        temp_path = Path(temp_root)
        stub_state_path = temp_path / "stub-state"
        stub_state_path.mkdir()
        nft_path = temp_path / "etc/nftables.d/custom-origin.nft"
        service_path = temp_path / "etc/systemd/system/custom-origin-firewall.service"
        nft_path.parent.mkdir(parents=True)
        service_path.parent.mkdir(parents=True)
        nft_path.write_text("existing origin rules\n", encoding="utf-8")
        service_path.write_text("existing origin service\n", encoding="utf-8")

        result = run_playbook(
            temp_root,
            str(stub_state_path),
            "-e",
            '{"lxc_origin_firewall_allowed_hosts": ["broken-portal"]}',
        )

        output = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0, output
        assert "could not resolve any IPv4 address" in output, output
        assert nft_path.read_text(encoding="utf-8") == "existing origin rules\n"
        assert service_path.read_text(encoding="utf-8") == "existing origin service\n"
        assert sorted(path.name for path in stub_state_path.iterdir()) == [], output


def test_reload_replaces_the_live_table_in_place() -> None:
    # Reconfiguration goes through ExecReload so the table is never deleted
    # outside the load transaction. The reload must also replace the old
    # allowlist rather than merge into it.
    templates = Environment(
        loader=FileSystemLoader(TEMPLATES), undefined=StrictUndefined, keep_trailing_newline=True
    )
    with tempfile.TemporaryDirectory(prefix="origin-firewall-reload-") as temp_root:
        rules_path = Path(temp_root) / "origin.nft"
        unit = templates.get_template("origin-firewall.service.j2").render(
            lxc_origin_firewall_nft_path=str(rules_path)
        )
        commands = dict(line.split("=", 1) for line in unit.splitlines() if line.startswith("Exec"))
        assert "ExecReload" in commands, unit

        def rules(address: str) -> str:
            return templates.get_template("origin-firewall.nft.j2").render(
                lxc_origin_firewall_protected_ports=[5900],
                lxc_origin_firewall_allowed_ipv4=[address],
            )

        new_rules = Path(temp_root) / "new.nft"
        rules_path.write_text(rules("192.0.2.10"), encoding="utf-8")
        new_rules.write_text(rules("192.0.2.20"), encoding="utf-8")
        script = (
            f"{commands['ExecStart']} && cp {new_rules} {rules_path} && {commands['ExecReload']}"
            " && /usr/sbin/nft list table inet origin_firewall"
        )
        result = subprocess.run(
            ["unshare", "-Urn", "sh", "-c", script], capture_output=True, text=True
        )

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, output
    assert "192.0.2.20" in result.stdout, output
    assert "192.0.2.10" not in result.stdout, output
