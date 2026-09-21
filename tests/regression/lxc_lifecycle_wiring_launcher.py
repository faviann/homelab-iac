#!/usr/bin/env python3
"""Regression for the production lifecycle facade's real role composition."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures"
ASSETS = FIXTURES / "lxc_lifecycle_facade_assets"
INVENTORY = FIXTURES / "lxc_lifecycle_wiring_inventory.yml"
PLAYBOOK = FIXTURES / "lxc_lifecycle_wiring_test.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lxc-lifecycle-wiring-") as temp_dir:
        state_dir = Path(temp_dir)
        for vmid in (7201, 7202):
            (state_dir / f"{vmid}.state").write_text("absent", encoding="utf-8")
            (state_dir / f"{vmid}.release").write_text("12", encoding="utf-8")
            (state_dir / f"{vmid}.events").write_text("", encoding="utf-8")
            (state_dir / f"{vmid}.conf").write_text("", encoding="utf-8")

        env = os.environ.copy()
        env["PATH"] = f"{ASSETS / 'bin'}:{env['PATH']}"
        env["LIFECYCLE_TEST_STATE_DIR"] = str(state_dir)
        env["LIFECYCLE_WIRING_REAL_ROLES"] = "1"
        env["HOMELAB_IAC_LIFECYCLE_WRAPPER"] = "1"
        env["ANSIBLE_ROLES_PATH"] = os.pathsep.join(
            [str(ASSETS / "roles"), str(REPO_ROOT / "playbooks" / "roles")]
        )
        env["ANSIBLE_COLLECTIONS_PATH"] = os.pathsep.join(
            [str(ASSETS / "collections"), str(REPO_ROOT / "collections")]
        )
        command = [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(INVENTORY),
            str(PLAYBOOK),
            "--limit",
            "wiring_target,wiring_peer",
            "-e",
            f"lifecycle_test_state_dir={state_dir}",
        ]
        rejected = subprocess.run(
            [*command, "-e", "lifecycle_wiring_peer_token=<REPLACE_ME>"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        rejected_output = f"{rejected.stdout}\n{rejected.stderr}"
        if (
            rejected.returncode == 0
            or "Proxmox API credentials require" not in rejected_output
            or "Lifecycle planning failed for wiring_peer" not in rejected_output
            or any((state_dir / f"{vmid}.events").read_text() for vmid in (7201, 7202))
        ):
            print("credential failure bypassed the lifecycle planning barrier", file=sys.stderr)
            print(rejected_output, file=sys.stderr)
            return 1

        proc = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        output = f"{proc.stdout}\n{proc.stderr}"
        events = {
            vmid: (state_dir / f"{vmid}.events").read_text(encoding="utf-8").splitlines()
            for vmid in (7201, 7202)
        }
        expected_events = {
            "api_reconciliation",
            "container_transition",
            "host_reconciliation",
            "runtime_refresh",
            "release_refresh",
            "access_restoration",
        }
        wiring_tasks = (
            "Compile and normalize the layered LXC specification",
            "Run fleet preflight after every target contract was compiled",
            "Compose semantic lifecycle plan",
            "Execute host-side actions",
            "Re-observe current state after provisioning and host reconciliation",
            "Restore guest access after re-observation",
            "Publish lifecycle results",
            "Aggregate lifecycle summary facts from host results",
            "Assert production lifecycle summary includes every targeted LXC",
        )
        if (
            proc.returncode != 0
            or any(set(host_events) != expected_events for host_events in events.values())
            or not all(task in output for task in wiring_tasks)
        ):
            print("lifecycle role composition is disconnected", file=sys.stderr)
            print(f"events={events!r}\n{output}", file=sys.stderr)
            return 1

    print("ok: lifecycle role composition keeps every facade stage connected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
