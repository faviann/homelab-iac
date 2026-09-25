#!/usr/bin/env python3
"""Credential-free regressions for the workstation origin firewall tasks."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "regression" / "fixtures"
PLAYBOOK = FIXTURE_ROOT / "workstation_origin_firewall.yml"
INVENTORY = FIXTURE_ROOT / "workstation_origin_firewall_inventory.yml"
STUB_ROOT = FIXTURE_ROOT / "workstation_origin_firewall_assets"
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)


def run_playbook(
    temp_root: str, stub_state: str, *extra_args: str
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PATH"] = f"{STUB_ROOT / 'bin'}:{environment['PATH']}"
    environment["WORKSTATION_ORIGIN_FIREWALL_STUB_STATE"] = stub_state
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


def test_workstation_origin_firewall_second_convergence_is_idempotent() -> None:
    with tempfile.TemporaryDirectory(prefix="workstation-origin-firewall-idempotency-") as temp_root:
        temp_path = Path(temp_root)
        stub_state_path = temp_path / "stub-state"
        stub_state_path.mkdir()
        stub_state = str(stub_state_path)
        first = run_playbook(temp_root, stub_state)

        first_output = f"{first.stdout}\n{first.stderr}"
        assert first.returncode == 0, first_output
        assert "failed=0" in first_output, first_output
        assert "Restart workstation origin firewall" in first_output, first_output
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


def test_workstation_origin_firewall_unresolved_origin_keeps_existing_firewall() -> None:
    with tempfile.TemporaryDirectory(prefix="workstation-origin-firewall-resolution-") as temp_root:
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
            '{"workstation_origin_firewall_allowed_hosts": ["broken-portal"]}',
        )

        output = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0, output
        assert "could not resolve any IPv4 address" in output, output
        assert nft_path.read_text(encoding="utf-8") == "existing origin rules\n"
        assert service_path.read_text(encoding="utf-8") == "existing origin service\n"
        assert sorted(path.name for path in stub_state_path.iterdir()) == [], output
