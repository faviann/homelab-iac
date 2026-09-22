#!/usr/bin/env python3
"""Regression test for the explicit Proxmox host SSH enrollment transition."""

from __future__ import annotations

import json
import os
import secrets
import select
import stat
import subprocess
import sys
import tempfile
import termios
import time
from dataclasses import dataclass
from pathlib import Path

from ansible_test_helper import (
    ansible_playbook_command,
    local_ssh_port,
    write_controller_identity,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "playbooks" / "enroll-proxmox-host-ssh.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)
TARGET = "root@127.0.0.1"
PROMPT = f"Password for {TARGET}".encode()

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

# Key authentication succeeds only for the selected private identity against the
# intended target, and only once that target trusts it.
SSH_STUB = """#!/bin/sh
case " $* " in *" -i {private} "*) ;; *) exit 255 ;; esac
case " $* " in *" {target} "*) ;; *) exit 255 ;; esac
[ -e '{trusted}' ] || exit 255
"""

# Records the password sshpass was handed and every live process whose
# arguments contain it, including Ansible's own module wrapper.
SSHPASS_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> '{requests}'
case "$1" in
  -d) IFS= read -r password; shift 2 ;;
  -p) password="$2"; shift 2 ;;
  -e) password="$SSHPASS"; shift ;;
esac
printf '%s\\n' "$password" | tee -a '{passwords}' > '{passwords}.pattern'
grep -lsaFf '{passwords}.pattern' /proc/[0-9]*/cmdline >> '{exposed}'
exec "$@" < /dev/null
"""

# ssh-copy-id owns the authorized_keys mutation; the stub only decides whether
# the request named the selected identity and target, and then grants trust.
SSH_COPY_ID_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> '{requests}'
identity=
for arg in "$@"; do
  [ "$previous" = -i ] && identity="${{arg%.pub}}"
  previous="$arg"
done
[ "$identity" = '{private}' ] && [ "$arg" = '{target}' ] || exit 1
{grant}
"""


@dataclass
class Run:
    returncode: int
    output: str
    prompted: bool
    passwords: list[str]
    requests: list[str]
    exposed: list[str]


def run_in_terminal(command: list[str], env: dict[str, str], password: str) -> tuple[int, str, bool]:
    """Run as an operator would, typing the password only when prompted.

    ansible.builtin.pause reads only from a controlling terminal in the
    foreground, so the playbook gets a pseudo-terminal of its own.
    """
    controller, terminal = os.openpty()
    process = subprocess.Popen(
        ["setsid", "--ctty", *command],
        cwd=REPO_ROOT,
        env=env,
        stdin=terminal,
        stdout=terminal,
        stderr=terminal,
    )
    os.close(terminal)
    output = bytearray()
    prompted = False
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            if select.select([controller], [], [], 0.1)[0]:
                try:
                    chunk = os.read(controller, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
            # Ansible switches the terminal to no-echo only after showing the
            # prompt, then discards pending input, so type after both.
            if (
                not prompted
                and PROMPT in output
                and not termios.tcgetattr(controller)[3] & termios.ECHO
            ):
                time.sleep(0.5)
                os.write(controller, password.encode() + b"\r")
                prompted = True
        else:
            process.kill()
        returncode = process.wait()
    finally:
        os.close(controller)
    return returncode, output.decode(errors="replace"), prompted


def enrollment_run(
    temp_root: Path,
    home: Path,
    ssh_port: int,
    name: str,
    *,
    password: str,
    already_trusted: bool,
    grants_trust: bool = True,
) -> Run:
    """Run the real enrollment playbook from the given starting trust state."""
    run_root = temp_root / name
    run_root.mkdir()
    private = home / ".ansible" / "ssh" / "proxmox_lxc"
    trusted = run_root / "trusted"
    if already_trusted:
        trusted.touch()

    passwords = run_root / "passwords.log"
    requests = run_root / "requests.log"
    exposed = run_root / "exposed.log"
    fields = {
        "private": private,
        "target": TARGET,
        "trusted": trusted,
        "requests": requests,
        "passwords": passwords,
        "exposed": exposed,
        "grant": f": > '{trusted}'" if grants_trust else "",
    }
    for stub, body in (
        ("ssh", SSH_STUB),
        ("sshpass", SSHPASS_STUB),
        ("ssh-copy-id", SSH_COPY_ID_STUB),
    ):
        path = run_root / stub
        path.write_text(body.format(**fields))
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
    returncode, output, prompted = run_in_terminal(
        [
            *ANSIBLE_PLAYBOOK,
            str(PLAYBOOK),
            "-e",
            "prerequisite_target_pattern=proxmox_api",
            # The role default is 22, which an unprivileged fixture cannot bind,
            # and check_ssh really waits on the port before probing trust.
            "-e",
            f"proxmox_ssh_port={ssh_port}",
            # Module arguments and the module's command line are echoed at this
            # level, so no_log is what keeps the password out of the transcript
            # rather than Ansible's terseness.
            "-vvvv",
        ],
        env,
        password,
    )
    log = lambda path: (  # noqa: E731
        path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    )
    return Run(returncode, output, prompted, log(passwords), log(requests), log(exposed))


def main() -> int:
    with (
        tempfile.TemporaryDirectory(prefix="proxmox-host-ssh-enrollment-") as temp_dir,
        local_ssh_port() as ssh_port,
    ):
        temp_root = Path(temp_dir)
        home = temp_root / "home"
        write_controller_identity(home)
        public_key = (home / ".ansible" / "ssh" / "proxmox_lxc.pub").read_text().strip()
        # No single quote, so a shell-quoted copy still contains it verbatim.
        # The random tail keeps the process scan from matching anything else.
        password = f'fixture $(false) "x" {secrets.token_hex(8)}'

        untrusted = enrollment_run(
            temp_root, home, ssh_port, "untrusted", password=password, already_trusted=False
        )
        if untrusted.returncode != 0 or not untrusted.prompted or not untrusted.requests:
            print(
                "explicit enrollment did not establish key-based trust for the "
                "selected identity on the intended target",
                file=sys.stderr,
            )
            print(untrusted.output, file=sys.stderr)
            return 1
        if untrusted.passwords != [password]:
            print("the target did not receive the typed password verbatim", file=sys.stderr)
            return 1
        if untrusted.exposed or any(password in request for request in untrusted.requests):
            print("the password was placed in process arguments", file=sys.stderr)
            return 1
        # Ansible prints results as JSON, which escapes the password's quotes.
        disclosed = (password, json.dumps(password)[1:-1], public_key.split()[1])
        if any(form in untrusted.output for form in disclosed):
            print("enrollment disclosed the password or the key material", file=sys.stderr)
            return 1

        unverified = enrollment_run(
            temp_root,
            home,
            ssh_port,
            "unverified",
            password=password,
            already_trusted=False,
            grants_trust=False,
        )
        if unverified.returncode == 0:
            print(
                "enrollment reported success although the selected identity "
                "still cannot authenticate",
                file=sys.stderr,
            )
            return 1

        trusted = enrollment_run(
            temp_root, home, ssh_port, "trusted", password=password, already_trusted=True
        )
        if trusted.returncode != 0 or trusted.prompted or trusted.requests or trusted.passwords:
            print(
                "enrollment did not stay a no-op when the target already trusts "
                "the selected identity",
                file=sys.stderr,
            )
            print(trusted.output, file=sys.stderr)
            return 1

    print(
        "ok: explicit Proxmox host enrollment prompts, installs the selected "
        "identity, verifies it, and does nothing once trusted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
