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

# The target trusts the selected identity only once it has been appended, so
# both stubs read one marker: key authentication fails until the append creates
# it. That is the whole simulated state.
SSH_STUB = """#!/bin/sh
[ -f '{marker}' ] || exit 255
exit 0
"""

# Only the append establishes trust. The existence check and the permission
# fixup also name authorized_keys, so the redirect is what distinguishes them.
APPEND = ">> /root/.ssh/authorized_keys"

SSHPASS_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> '{log}'
case "$*" in
    *'{append}'*) : > '{marker}' ;;
    *'grep -qxF'*) [ -f '{marker}' ] || exit 1 ;;
esac
exit 0
"""


def enrollment_run(
    temp_root: Path, home: Path, ssh_port: int, name: str, *, already_trusted: bool
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the real enrollment playbook from the given starting trust state."""
    run_root = temp_root / name
    run_root.mkdir()
    marker = run_root / "trusted"
    if already_trusted:
        marker.touch()
    password_calls = run_root / "password-calls.log"
    for stub, body in (
        ("ssh", SSH_STUB.format(marker=marker)),
        (
            "sshpass",
            SSHPASS_STUB.format(
                log=password_calls, marker=marker, append=APPEND
            ),
        ),
    ):
        path = run_root / stub
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    inventory = run_root / "inventory.yml"
    inventory.write_text(INVENTORY, encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{run_root}:{env['PATH']}"
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
            # The role default is 22, which an unprivileged fixture cannot bind,
            # and check_ssh really waits on the port before probing trust.
            "-e",
            f"proxmox_ssh_port={ssh_port}",
            # Task arguments are echoed at this level, so no_log is what keeps
            # the key out of the transcript rather than Ansible's own terseness.
            "-v",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=env,
    )
    calls = (
        password_calls.read_text(encoding="utf-8").splitlines()
        if password_calls.exists()
        else []
    )
    return result, calls


def main() -> int:
    with (
        tempfile.TemporaryDirectory(prefix="proxmox-host-ssh-enrollment-") as temp_dir,
        local_ssh_port() as ssh_port,
    ):
        temp_root = Path(temp_dir)
        home = temp_root / "home"
        public_key = Path(f"{write_controller_identity(home)}.pub").read_text().strip()

        untrusted, enrolling_calls = enrollment_run(
            temp_root, home, ssh_port, "untrusted", already_trusted=False
        )
        untrusted_output = f"{untrusted.stdout}\n{untrusted.stderr}"
        enrolled = [
            call for call in enrolling_calls if APPEND in call and public_key in call
        ]
        # Success is the playbook's own closing key-authentication check, which
        # the stub grants only because the append happened.
        if (
            untrusted.returncode != 0
            or not enrolled
            or not all("root@127.0.0.1" in call for call in enrolled)
        ):
            print(
                "explicit enrollment did not establish key-based trust for the "
                "selected identity on the intended target",
                file=sys.stderr,
            )
            print(untrusted_output, file=sys.stderr)
            return 1
        if public_key in untrusted_output:
            print("enrollment disclosed the selected key material", file=sys.stderr)
            return 1

        trusted, trusted_calls = enrollment_run(
            temp_root, home, ssh_port, "trusted", already_trusted=True
        )
        trusted_output = f"{trusted.stdout}\n{trusted.stderr}"
        if trusted.returncode != 0 or trusted_calls:
            print(
                "enrollment did not stay a no-op when the target already trusts "
                "the selected identity",
                file=sys.stderr,
            )
            print(trusted_output, file=sys.stderr)
            return 1

    print(
        "ok: explicit Proxmox host enrollment establishes trust once and then "
        "does nothing"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
