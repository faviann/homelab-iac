#!/usr/bin/env python3
"""Regression test for the explicit Proxmox host SSH enrollment transition."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from ansible_test_helper import (
    ansible_playbook_command,
    local_ssh_port,
    write_controller_identity,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "playbooks" / "enroll-proxmox-host-ssh.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)

# Only what the production inventory itself defines. proxmox_host,
# proxmox_ssh_user, and proxmox_ssh_connect_timeout stay on the role's own
# defaults, so a task reading them from outside the role fails here exactly as
# it would on a real run.
INVENTORY = """
all:
  vars:
    proxmox_api_host: 127.0.0.1
  children:
    proxmox_api:
      hosts:
        proxmox_api_controller:
          ansible_connection: local
          ansible_python_interpreter: "{{ ansible_playbook_python }}"
"""


def main() -> int:
    with (
        tempfile.TemporaryDirectory(prefix="proxmox-host-ssh-enrollment-") as temp_dir,
        local_ssh_port() as ssh_port,
    ):
        temp_root = Path(temp_dir)
        home = temp_root / "home"
        write_controller_identity(home)

        # Trust already established, so the run must reach its end without
        # entering the password-driven enrollment path.
        ssh = temp_root / "ssh"
        ssh.write_text("#!/bin/sh\nexit 0\n")
        ssh.chmod(ssh.stat().st_mode | stat.S_IXUSR)

        inventory = temp_root / "inventory.yml"
        inventory.write_text(INVENTORY, encoding="utf-8")

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{temp_root}:{env['PATH']}"
        env["HOMELAB_IAC_LIFECYCLE_WRAPPER"] = "1"
        env["ANSIBLE_INVENTORY"] = str(inventory)
        env["ANSIBLE_COLLECTIONS_PATH"] = str(temp_root / "empty-collections")
        env["ANSIBLE_COLLECTIONS_SCAN_SYS_PATH"] = "false"
        result = subprocess.run(
            [
                *ANSIBLE_PLAYBOOK,
                str(PLAYBOOK),
                "-e",
                "prerequisite_target_pattern=proxmox_api",
                # The role default is 22, which an unprivileged fixture cannot
                # bind, and check_ssh really waits on the port before probing.
                "-e",
                f"proxmox_ssh_port={ssh_port}",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=env,
        )

    output = f"{result.stdout}\n{result.stderr}"
    # pause writes its prompt to the tty, not stdout, and sshpass is a declared
    # system prerequisite, so the password path leaves no trace of its own here.
    # The skipped include is the observable that it was never entered.
    if result.returncode != 0 or "Prompt for Proxmox host password" in output:
        print(
            "enrollment did not complete against an already-trusted target "
            "without password-driven enrollment",
            file=sys.stderr,
        )
        print(output, file=sys.stderr)
        return 1

    print("ok: Proxmox host enrollment resolves its own connection defaults")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
