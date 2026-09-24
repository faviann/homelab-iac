#!/usr/bin/env python3
"""Thin runner for fleet preflight behavior through the lifecycle facade."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from ansible_test_helper import ansible_playbook_command
from proxmox_api_fixture import (
    COMMON_OBSERVATION,
    generate_localhost_certificate,
    local_proxmox_server,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures"
INVENTORY = FIXTURES / "lxc_fleet_preflight_inventory.yml"
PLAYBOOK = FIXTURES / "lxc_fleet_preflight_test.yml"
ROLE_INTERFACE_INVENTORY = FIXTURES / "lxc_fleet_preflight_interface_inventory.yml"
ROLE_INTERFACE_PLAYBOOK = FIXTURES / "lxc_fleet_preflight_interface_test.yml"
STANDALONE_PLAYBOOK = FIXTURES / "lxc_standalone_validation_test.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)
FIXTURE_COLLECTIONS = (
    REPO_ROOT
    / "tests/regression/fixtures/lxc_lifecycle_facade_assets/collections"
)
DUMMY_API_USER = "dummy@pam"
DUMMY_API_TOKEN_ID = "dummy-token"
DUMMY_API_TOKEN_SECRET = "<REPLACE_ME>"


def run_module_query_case(
    *, limit: str, fail: bool = False, check_mode: bool = False,
    deny_audit: bool = False,
) -> bool:
    with tempfile.TemporaryDirectory(prefix="lxc-fleet-module-") as temp_dir:
        temp_root = Path(temp_dir)
        observation = temp_root / "observation.json"
        certificate = temp_root / "certificate.pem"
        private_key = temp_root / "private-key.pem"
        generate_localhost_certificate(certificate, private_key)
        with local_proxmox_server(
            certificate,
            private_key,
            denied_audit_paths=("/vms/5103",) if deny_audit else (),
        ) as server:
            expected_arguments = {
                "api_host": "127.0.0.1",
                "api_port": server.server_address[1],
                "api_user": DUMMY_API_USER,
                "api_token_id": DUMMY_API_TOKEN_ID,
                "api_token_secret": DUMMY_API_TOKEN_SECRET,
                "validate_certs": False,
                "node": None,
                "type": "lxc",
            }
            observation.write_text(
                json.dumps({
                    "proxmox_vms": COMMON_OBSERVATION,
                    "fail": fail,
                    "expected_arguments": expected_arguments,
                }),
                encoding="utf-8",
            )
            extra_vars = {
                "proxmox_fleet_observation_override": None,
                "proxmox_api_host": "127.0.0.1",
                "proxmox_api_port": server.server_address[1],
                "proxmox_api_user": DUMMY_API_USER,
                "proxmox_api_token_id": DUMMY_API_TOKEN_ID,
                "proxmox_api_token_secret": DUMMY_API_TOKEN_SECRET,
                "proxmox_default_node": "pve-a",
                "proxmox_verify_ssl": False,
            }
            command = [
                *ANSIBLE_PLAYBOOK, "-i", str(INVENTORY), str(PLAYBOOK),
                "--limit", limit, "--extra-vars", json.dumps(extra_vars),
            ]
            if check_mode:
                command.append("--check")
            proc = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                env={**os.environ, "LIFECYCLE_PROXMOX_OBSERVATION": str(observation)},
            )
        calls_path = observation.with_suffix(".calls")
        calls = (
            calls_path.read_text(encoding="utf-8").splitlines()
            if calls_path.exists() else []
        )
        output = f"{proc.stdout}\n{proc.stderr}"
        expected_calls = [] if deny_audit else [json.dumps({"check_mode": check_mode})]
        if (
            proc.returncode == 0
            and calls == expected_calls
            and len(server.requested_paths) == 2
            and not any(value in output for value in (
                DUMMY_API_USER, DUMMY_API_TOKEN_ID, DUMMY_API_TOKEN_SECRET
            ))
        ):
            return True
    print(f"module query case {limit!r} fail={fail} check={check_mode} deny_audit={deny_audit} failed", file=sys.stderr)
    print(f"{proc.stdout}\n{proc.stderr}", file=sys.stderr)
    return False


def run_case(limit: str) -> bool:
    env = os.environ.copy()
    command = [
        *ANSIBLE_PLAYBOOK,
        "-i",
        str(INVENTORY),
        str(PLAYBOOK),
        "--limit",
        limit,
    ]
    proc = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode == 0:
        return True

    print(f"fleet preflight case {limit!r} failed unexpectedly", file=sys.stderr)
    print(f"{proc.stdout}\n{proc.stderr}", file=sys.stderr)
    return False


def run_regressions() -> int:
    # VMID and hostname conflicts share one run: each is owned by its own
    # target, so either detector failing leaves that target blocked, not
    # planning_failed, and the other target's evidence is unaffected.
    if not run_case("target_conflict,conflict_peer,hostname_conflict"):
        return 1

    role_interface = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(ROLE_INTERFACE_INVENTORY),
            str(ROLE_INTERFACE_PLAYBOOK),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if role_interface.returncode != 0:
        print("fleet preflight role interface seam failed", file=sys.stderr)
        print(f"{role_interface.stdout}\n{role_interface.stderr}", file=sys.stderr)
        return 1

    if not all((
        run_module_query_case(limit="target_a,target_b", check_mode=True),
        run_module_query_case(limit="access_target,access_peer", fail=True),
        run_module_query_case(limit="access_target,access_peer", deny_audit=True),
    )):
        return 1

    site_documents = yaml.safe_load((REPO_ROOT / "site.yml").read_text(encoding="utf-8"))
    if any(
        document.get("ansible.builtin.import_playbook")
        == "playbooks/validate-infrastructure.yml"
        or "validation" in document.get("tags", [])
        for document in site_documents
    ):
        print("site.yml still exposes standalone validation", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env["HOMELAB_IAC_LIFECYCLE_WRAPPER"] = "1"
    proc = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(INVENTORY),
            str(STANDALONE_PLAYBOOK),
            "--limit",
            "target_conflict,release_problem,target_a",
            "--check",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    aggregate_output = f"{proc.stdout}\n{proc.stderr}"
    # Search only the aggregate report, so a fragment printed by an earlier
    # rescued task cannot stand in for a problem the aggregate dropped.
    aggregate_report = aggregate_output.partition("Standalone lifecycle validation found")[2]
    aggregate_fragments = (
        "VMID 5199",  # targeted VMID conflict
        "Guest release observation is required",  # target-local planning problem
        "'a_missing_vmid_hostname_owner' has no VMID",  # incomplete VMID
        "null_hostname_reservation",  # incomplete hostname
        "empty_hostname_reservation",  # incomplete hostname
        "hostname 'target-a'",  # conflict with a VMID-less reservation
        "missing `default_domain` in inventory/host_vars/missing_domain.yml",  # ordinary configuration failure
    )
    missing = [fragment for fragment in aggregate_fragments if fragment not in aggregate_report]
    if proc.returncode == 0 or missing:
        print(f"standalone validation did not aggregate: {missing}", file=sys.stderr)
        print(aggregate_output, file=sys.stderr)
        return 1

    print("ok: fleet preflight shares observations and standalone validation aggregates problems")
    return 0


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lxc-fleet-vault-") as temp_dir:
        # ansible.cfg names a vault password file that must exist, but the
        # fixture decrypts nothing: a placeholder keeps the run credential-free.
        vault_placeholder = Path(temp_dir) / "vault-pass"
        vault_placeholder.write_text(
            "unused-fixture-placeholder\n", encoding="utf-8"
        )
        previous_vault_password_file = os.environ.get("ANSIBLE_VAULT_PASSWORD_FILE")
        previous_collections_path = os.environ.get("ANSIBLE_COLLECTIONS_PATH")
        os.environ["ANSIBLE_VAULT_PASSWORD_FILE"] = str(vault_placeholder)
        os.environ["ANSIBLE_COLLECTIONS_PATH"] = str(FIXTURE_COLLECTIONS)
        try:
            return run_regressions()
        finally:
            if previous_vault_password_file is None:
                os.environ.pop("ANSIBLE_VAULT_PASSWORD_FILE", None)
            else:
                os.environ["ANSIBLE_VAULT_PASSWORD_FILE"] = previous_vault_password_file
            if previous_collections_path is None:
                os.environ.pop("ANSIBLE_COLLECTIONS_PATH", None)
            else:
                os.environ["ANSIBLE_COLLECTIONS_PATH"] = previous_collections_path


if __name__ == "__main__":
    raise SystemExit(main())
