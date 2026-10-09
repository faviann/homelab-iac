#!/usr/bin/env python3
"""Regression: a guest created in this run is configured by its observed IPv4.

The inventory names each guest by a DNS name no resolver answers, as the LAN
resolver does for a fresh lease. The lifecycle learns the address from the
Proxmox host double and configures the first guest over a real ssh session to
it. The second guest never obtains an address and fails by vmid, not by name
resolution. The fixture playbook asserts both outcomes.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ansible_test_helper import (
    SSHD,
    ansible_playbook_command,
    local_sshd,
    write_controller_identity,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures"
ASSETS = FIXTURES / "lxc_lifecycle_facade_assets"
INVENTORY = FIXTURES / "proxmox_lxc_lifecycle_created_guest_inventory.yml"
PLAYBOOK = FIXTURES / "proxmox_lxc_lifecycle_created_guest_test.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)
ADDRESSED = 7301
UNADDRESSED = 7302


def main() -> int:
    if not SSHD.exists():
        print(f"this regression needs a real sshd at {SSHD}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="pxcreate-") as temp_dir:
        root = Path(temp_dir)
        state_dir = root / "state"
        cache_dir = root / "cache"
        home = root / "home"
        state_dir.mkdir()
        cache_dir.mkdir()
        identity = write_controller_identity(home)
        (root / "authorized_keys").write_text(identity.with_suffix(".pub").read_text())
        for vmid in (ADDRESSED, UNADDRESSED):
            (state_dir / f"{vmid}.state").write_text("absent", encoding="utf-8")
            (state_dir / f"{vmid}.release").write_text("12", encoding="utf-8")
            (state_dir / f"{vmid}.events").write_text("", encoding="utf-8")
            (state_dir / f"{vmid}.conf").write_text("", encoding="utf-8")
        (state_dir / f"{ADDRESSED}.address").write_text("127.0.0.1\n", encoding="utf-8")

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{ASSETS / 'bin'}:{env['PATH']}"
        env["LIFECYCLE_TEST_STATE_DIR"] = str(state_dir)
        env["ANSIBLE_ROLES_PATH"] = os.pathsep.join(
            [str(ASSETS / "roles"), str(REPO_ROOT / "playbooks" / "roles")]
        )
        env["ANSIBLE_COLLECTIONS_PATH"] = os.pathsep.join(
            [str(ASSETS / "collections"), str(REPO_ROOT / "collections")]
        )
        env["ANSIBLE_CACHE_PLUGIN_CONNECTION"] = str(cache_dir)
        env.pop("SSH_AUTH_SOCK", None)

        # ansible.cfg multiplexes into this repo-relative directory; the live boundary creates it.
        (REPO_ROOT / ".ansible" / "cp").mkdir(mode=0o700, parents=True, exist_ok=True)

        with local_sshd(root) as port:
            proc = subprocess.run(
                [
                    *ANSIBLE_PLAYBOOK,
                    "-i",
                    str(INVENTORY),
                    str(PLAYBOOK),
                    "-e",
                    f"lifecycle_test_state_dir={state_dir}",
                    "-e",
                    f"lifecycle_ssh_port={port}",
                    "-e",
                    f"lifecycle_ssh_user={getpass.getuser()}",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        if proc.returncode != 0:
            print("the lifecycle fixture did not publish the expected results", file=sys.stderr)
            sshd_log = (root / "sshd.log").read_text(encoding="utf-8")
            print(f"{proc.stdout}\n{proc.stderr}\nsshd:\n{sshd_log}", file=sys.stderr)
            return 1

    print(
        "ok: a created guest is configured by its observed IPv4 address, and one "
        "without an address fails by vmid"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
