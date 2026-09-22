#!/usr/bin/env python3
"""Regression test for the explicit Proxmox host SSH enrollment transition."""

from __future__ import annotations

import base64
import json
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

# Deliberately balanced. An unbalanced payload only makes a vulnerable shell
# fail to parse, which is indistinguishable from any other breakage; this one
# closes the caller's quoting, runs, and reopens it, so a shell that reads it
# leaves the canary behind and carries on. Every character is legal in a key
# comment and in a password.
HOSTILE = "fixture '$({command})' \"x\" end"

# The target trusts the selected identity only once it has been enrolled, so
# both stubs read one marker: key authentication fails until enrollment writes
# it. That is the whole simulated state.
SSH_STUB = """#!/bin/sh
[ -f '{marker}' ] || exit 255
exit 0
"""

# Records the password it was handed and the request it carried, so the test
# can compare both against what it supplied. Anything that is not the bare
# reachability probe is enrollment, whatever shape it takes, so this stays out
# of the way of how the key is actually carried.
SSHPASS_STUB = """#!/bin/sh
printf '%s\\n' "$SSHPASS" >> '{passwords}'
printf '%s\\n' "$*" | tr '\\n' ' ' >> '{requests}'
printf '\\n' >> '{requests}'
case "$*" in
    *' true') ;;
    *) : > '{marker}'; printf 'CHANGED=1\\n' ;;
esac
exit 0
"""


def enrollment_run(
    temp_root: Path,
    home: Path,
    ssh_port: int,
    name: str,
    *,
    password: str,
    already_trusted: bool,
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
    """Run the real enrollment playbook from the given starting trust state."""
    run_root = temp_root / name
    run_root.mkdir()
    marker = run_root / "trusted"
    if already_trusted:
        marker.touch()
    passwords = run_root / "passwords.log"
    requests = run_root / "requests.log"
    for stub, body in (
        ("ssh", SSH_STUB.format(marker=marker)),
        (
            "sshpass",
            SSHPASS_STUB.format(
                passwords=passwords,
                requests=requests,
                marker=marker,
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
            # Extra vars outrank the registered prompt result, so the operator's
            # answer can be supplied without a tty and without a production seam.
            "-e",
            json.dumps({"proxmox_root_password": {"user_input": password}}),
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
    log = lambda path: (  # noqa: E731
        path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    )
    return result, log(passwords), log(requests)


def main() -> int:
    with (
        tempfile.TemporaryDirectory(prefix="proxmox-host-ssh-enrollment-") as temp_dir,
        local_ssh_port() as ssh_port,
    ):
        temp_root = Path(temp_dir)
        home = temp_root / "home"
        key_canary = temp_root / "key-comment-was-evaluated"
        password_canary = temp_root / "password-was-evaluated"
        comment = HOSTILE.format(command=f"touch {key_canary}")
        password = HOSTILE.format(command=f"touch {password_canary}")

        write_controller_identity(home, comment=comment)
        public_key = Path(f"{home}/.ansible/ssh/proxmox_lxc.pub").read_text().strip()
        # The request has to carry the selected key to the target. Plain text
        # and base64 are both fine; what matters is that it arrives unaltered.
        carried = (public_key, base64.b64encode(public_key.encode()).decode())

        untrusted, passwords, requests = enrollment_run(
            temp_root,
            home,
            ssh_port,
            "untrusted",
            password=password,
            already_trusted=False,
        )
        untrusted_output = f"{untrusted.stdout}\n{untrusted.stderr}"
        # Checked first: an evaluated substitution is the specific defect here,
        # and it also corrupts what the target receives, so the coarser checks
        # below would otherwise report it as a plain enrollment failure.
        if key_canary.exists() or password_canary.exists():
            print(
                "a shell evaluated the key comment or the password instead of "
                "passing it through literally",
                file=sys.stderr,
            )
            return 1
        if not passwords or set(passwords) != {password}:
            print(
                f"the target received {len(set(passwords))} distinct passwords, "
                "not the one supplied verbatim",
                file=sys.stderr,
            )
            return 1
        if any(password in request for request in requests):
            print(
                "the password was placed in the process arguments rather than "
                "the environment",
                file=sys.stderr,
            )
            return 1
        enrolling = [
            request
            for request in requests
            if any(form in request for form in carried)
            and "root@127.0.0.1" in request
        ]
        # Success is the playbook's own closing key-authentication check, which
        # the stub grants only because enrollment ran.
        if untrusted.returncode != 0 or not enrolling:
            print(
                "explicit enrollment did not establish key-based trust for the "
                "selected identity on the intended target",
                file=sys.stderr,
            )
            print(untrusted_output, file=sys.stderr)
            return 1
        if password in untrusted_output or any(
            form in untrusted_output for form in carried
        ):
            print("enrollment disclosed the password or the key material", file=sys.stderr)
            return 1

        trusted, trusted_passwords, trusted_requests = enrollment_run(
            temp_root,
            home,
            ssh_port,
            "trusted",
            password=password,
            already_trusted=True,
        )
        trusted_output = f"{trusted.stdout}\n{trusted.stderr}"
        if trusted.returncode != 0 or trusted_requests or trusted_passwords:
            print(
                "enrollment did not stay a no-op when the target already trusts "
                "the selected identity",
                file=sys.stderr,
            )
            print(trusted_output, file=sys.stderr)
            return 1

    print(
        "ok: explicit Proxmox host enrollment establishes trust once, treats the "
        "password and key comment literally, and then does nothing"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
