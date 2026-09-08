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


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures"
INVENTORY = FIXTURES / "lxc_fleet_preflight_inventory.yml"
VALIDATION_PREREQUISITE_INVENTORY = (
    FIXTURES / "lxc_validation_prerequisite_inventory.yml"
)
PLAYBOOK = FIXTURES / "lxc_fleet_preflight_test.yml"
ROLE_INTERFACE_INVENTORY = FIXTURES / "lxc_fleet_preflight_interface_inventory.yml"
ROLE_INTERFACE_PLAYBOOK = FIXTURES / "lxc_fleet_preflight_interface_test.yml"
STANDALONE_PLAYBOOK = FIXTURES / "lxc_standalone_validation_test.yml"
MISSING_HOSTNAME_PLAYBOOK = FIXTURES / "lxc_fleet_missing_hostname_test.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)
FIXTURE_COLLECTIONS = (
    REPO_ROOT
    / "tests/regression/fixtures/lxc_lifecycle_facade_assets/collections"
)
DUMMY_API_USER = "dummy@pam"
DUMMY_API_TOKEN_ID = "dummy-token"
DUMMY_API_TOKEN_SECRET = "<REPLACE_ME>"
COMMON_OBSERVATION = [
    {"vmid": 5101, "name": "target-a", "node": "pve-a", "status": "stopped"},
    {"vmid": 5102, "name": "target-b", "node": "pve-b", "status": "stopped"},
    {
        "vmid": 5105,
        "name": "release-problem",
        "node": "pve-a",
        "status": "stopped",
    },
]


def run_module_query_case(
    *, limit: str, fail: bool = False, check_mode: bool = False
) -> bool:
    with tempfile.TemporaryDirectory(prefix="lxc-fleet-module-") as temp_dir:
        observation = Path(temp_dir) / "observation.json"
        expected_arguments = {
            "api_host": "api.invalid",
            "api_port": 8006,
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
            "proxmox_api_host": "api.invalid",
            "proxmox_api_port": 8006,
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
        if proc.returncode == 0 and calls == [json.dumps({"check_mode": check_mode})]:
            return True
    print(f"module query case {limit!r} fail={fail} check={check_mode} failed", file=sys.stderr)
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
    cases = (
        "target_conflict,conflict_peer",
        "hostname_conflict",
        "shared_problem_a,shared_problem_b",
    )
    if not all(run_case(case) for case in cases):
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
        run_module_query_case(limit="target_a,target_b"),
        run_module_query_case(limit="target_a,target_b", check_mode=True),
        run_module_query_case(limit="access_target,access_peer", fail=True),
    )):
        return 1

    missing_hostname = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(INVENTORY),
            str(MISSING_HOSTNAME_PLAYBOOK),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if missing_hostname.returncode != 0:
        print("incomplete hostname reservations were not aggregated", file=sys.stderr)
        print(f"{missing_hostname.stdout}\n{missing_hostname.stderr}", file=sys.stderr)
        return 1

    normal_tasks = subprocess.run(
        [*ANSIBLE_PLAYBOOK, "-i", str(INVENTORY), "site.yml", "--list-tasks"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    site_documents = yaml.safe_load((REPO_ROOT / "site.yml").read_text(encoding="utf-8"))
    if (
        any(
            document.get("ansible.builtin.import_playbook")
            == "playbooks/validate-infrastructure.yml"
            or "validation" in document.get("tags", [])
            for document in site_documents
        )
        or normal_tasks.returncode != 0
        or "Run aggregate standalone lifecycle validation" in normal_tasks.stdout
        or "Build the effective LXC specification" not in normal_tasks.stdout
    ):
        print("site.yml still exposes standalone validation or lost lifecycle routing", file=sys.stderr)
        print(f"normal route:\n{normal_tasks.stdout}\n{normal_tasks.stderr}", file=sys.stderr)
        return 1

    missing_domain = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(VALIDATION_PREREQUISITE_INVENTORY),
            str(STANDALONE_PLAYBOOK),
            "--limit",
            "missing_domain",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "HOMELAB_IAC_LIFECYCLE_WRAPPER": "1"},
    )
    missing_domain_output = f"{missing_domain.stdout}\n{missing_domain.stderr}"
    if (
        missing_domain.returncode == 0
        or "missing `default_domain`" not in missing_domain_output
        or "missing_domain" not in missing_domain_output
        or "Controlled shared Fleet preflight problem." not in missing_domain_output
    ):
        print("site validation did not aggregate missing default_domain", file=sys.stderr)
        print(missing_domain_output, file=sys.stderr)
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
            "target_conflict,release_problem",
            "--check",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    aggregate_output = f"{proc.stdout}\n{proc.stderr}"
    aggregate_fragments = (
        "Standalone lifecycle validation found",
        "Target identity conflict",
        "VMID 5199",
        "Guest release observation is required",
        "release_problem",
    )
    if proc.returncode == 0 or not all(
        fragment in aggregate_output for fragment in aggregate_fragments
    ):
        print("standalone validation did not aggregate all problems", file=sys.stderr)
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
