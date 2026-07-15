#!/usr/bin/env python3
"""Regression for the production lifecycle facade's real role composition."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures"
ASSETS = FIXTURES / "lxc_lifecycle_facade_assets"
INVENTORY = FIXTURES / "lxc_lifecycle_wiring_inventory.yml"
PLAYBOOK = FIXTURES / "lxc_lifecycle_wiring_test.yml"
PRODUCTION_PLAYBOOK = REPO_ROOT / "playbooks" / "lifecycle-lxcs.yml"
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lxc-lifecycle-wiring-") as temp_dir:
        state_dir = Path(temp_dir)
        (state_dir / "7201.state").write_text("stopped", encoding="utf-8")
        (state_dir / "7201.release").write_text("12", encoding="utf-8")
        (state_dir / "7201.events").write_text("", encoding="utf-8")

        env = os.environ.copy()
        env["PATH"] = f"{ASSETS / 'bin'}:{env['PATH']}"
        env["LIFECYCLE_TEST_STATE_DIR"] = str(state_dir)
        env["ANSIBLE_ROLES_PATH"] = os.pathsep.join(
            [str(ASSETS / "roles"), str(REPO_ROOT / "playbooks" / "roles")]
        )
        env["ANSIBLE_COLLECTIONS_PATH"] = os.pathsep.join(
            [str(ASSETS / "collections"), str(REPO_ROOT / "collections")]
        )
        proc = subprocess.run(
            [
                *ANSIBLE_PLAYBOOK,
                "-i",
                str(INVENTORY),
                str(PLAYBOOK),
                "-e",
                f"lifecycle_test_state_dir={state_dir}",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        limited_hosts = subprocess.run(
            [
                *ANSIBLE_PLAYBOOK,
                "-i",
                str(INVENTORY),
                str(PRODUCTION_PLAYBOOK),
                "--limit",
                "wiring_target",
                "--list-hosts",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        output = f"{proc.stdout}\n{proc.stderr}"
        limited_closeout = limited_hosts.stdout.split(
            "Ensure lifecycle summary facts exist on localhost", maxsplit=1
        )[-1]
        events = (state_dir / "7201.events").read_text(encoding="utf-8").splitlines()
        expected_events = {
            "api_reconciliation",
            "container_transition",
            "host_reconciliation",
            "runtime_refresh",
            "release_refresh",
            "access_restoration",
            "guest_configuration",
        }
        wiring_tasks = (
            "Compile desired LXC specification",
            "Run fleet preflight after every target contract was compiled",
            "Decide lifecycle actions",
            "Execute host-side actions",
            "Re-observe current state after provisioning and host reconciliation",
            "Restore guest access after re-observation",
            "Publish lifecycle results",
        )
        if (
            proc.returncode != 0
            or limited_hosts.returncode != 0
            or "Ensure lifecycle summary facts exist on localhost"
            not in limited_hosts.stdout
            or "hosts (1)" not in limited_closeout
            or "wiring_target" not in limited_closeout
            or set(events) != expected_events
            or not all(task in output for task in wiring_tasks)
        ):
            print("lifecycle role composition is disconnected", file=sys.stderr)
            print(f"events={events!r}\n{output}", file=sys.stderr)
            return 1

    print("ok: lifecycle role composition keeps every facade stage connected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
