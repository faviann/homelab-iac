#!/usr/bin/env python3
"""Regression test: Proxmox trust means the selected identity itself authenticates.

Runs the real ordinary prerequisite playbook with the real ssh client against an
unprivileged real sshd, so only the credential that actually logs in decides.
"""

from __future__ import annotations

import getpass
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ansible_test_helper import ansible_playbook_command, write_controller_identity


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "playbooks" / "proxmox-host-prerequisites.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)
SSHD = Path("/usr/sbin/sshd")
UNTRUSTED = "selected controller SSH identity is not trusted"

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

SSHD_CONFIG = """
Port {port}
ListenAddress 127.0.0.1
HostKey {root}/host_key
PidFile {root}/sshd.pid
AuthorizedKeysFile {root}/authorized_keys
StrictModes no
UsePAM no
PasswordAuthentication no
KbdInteractiveAuthentication no
"""

# ssh reads ~/.ssh/config from the passwd home, which a fixture must not touch.
# This stands in for it: the operator's ssh_config, applied first, so any -F the
# caller passes still takes precedence as it would over the real file.
SSH_WRAPPER = """#!/bin/sh
exec '{ssh}' -F '{operator_config}' -o UserKnownHostsFile='{root}/known_hosts' "$@"
"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_for_port(port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"sshd did not start listening on port {port}")


def main() -> int:
    if not SSHD.exists():
        print(f"this regression needs a real sshd at {SSHD}", file=sys.stderr)
        return 1
    real_ssh = shutil.which("ssh")
    user = getpass.getuser()

    # A short root keeps ControlPath sockets under the Unix socket length limit.
    with tempfile.TemporaryDirectory(prefix="pxtrust-", dir="/tmp") as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        canonical = write_controller_identity(home)
        other = write_controller_identity(root / "elsewhere")
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(root / "host_key")],
            check=True,
            capture_output=True,
        )
        port = free_port()
        (root / "sshd_config").write_text(SSHD_CONFIG.format(port=port, root=root))
        (root / "inventory.yml").write_text(INVENTORY)
        operator_config = root / "operator_ssh_config"
        wrapper_dir = root / "bin"
        wrapper_dir.mkdir()
        wrapper = wrapper_dir / "ssh"
        wrapper.write_text(
            SSH_WRAPPER.format(ssh=real_ssh, operator_config=operator_config, root=root)
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{wrapper_dir}:{env['PATH']}"
        env["HOMELAB_IAC_LIFECYCLE_WRAPPER"] = "1"
        env["ANSIBLE_INVENTORY"] = str(root / "inventory.yml")
        env["ANSIBLE_COLLECTIONS_PATH"] = str(root / "empty-collections")
        env["ANSIBLE_COLLECTIONS_SCAN_SYS_PATH"] = "false"
        env.pop("SSH_AUTH_SOCK", None)

        def run_prerequisites(
            authorized: Path, operator_ssh_config: str
        ) -> subprocess.CompletedProcess[str]:
            (root / "authorized_keys").write_text(authorized.with_suffix(".pub").read_text())
            operator_config.write_text(operator_ssh_config)
            return subprocess.run(
                [
                    *ANSIBLE_PLAYBOOK,
                    str(PLAYBOOK),
                    "-e",
                    "prerequisite_target_pattern=proxmox_api",
                    "-e",
                    f"proxmox_ssh_port={port}",
                    "-e",
                    f"proxmox_ssh_user={user}",
                    "-e",
                    "proxmox_validate_pct=false",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                env=env,
            )

        sshd = subprocess.Popen(
            [str(SSHD), "-D", "-e", "-f", str(root / "sshd_config")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_port(port)

            named = run_prerequisites(other, f"Host *\n  IdentityFile {other}\n")
            if named.returncode == 0 or UNTRUSTED not in named.stdout:
                print(
                    "the trust probe accepted an unrelated identity that ssh_config "
                    "named, although the target does not trust the selected one",
                    file=sys.stderr,
                )
                print(f"{named.stdout}\n{named.stderr}", file=sys.stderr)
                return 1

            shared_config = (
                "Host *\n"
                "  ControlMaster auto\n"
                f"  ControlPath {root}/%C\n"
                "  ControlPersist 60\n"
            )
            operator_config.write_text(shared_config)
            master = subprocess.run(
                [
                    str(wrapper),
                    "-i",
                    str(other),
                    "-o",
                    "IdentitiesOnly=yes",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-p",
                    str(port),
                    f"{user}@127.0.0.1",
                    "true",
                ],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                env=env,
            )
            if master.returncode != 0:
                print(
                    f"fixture could not open a shared connection:\n{master.stderr}",
                    file=sys.stderr,
                )
                return 1
            shared = run_prerequisites(other, shared_config)
            subprocess.run(
                [str(wrapper), "-O", "exit", "-p", str(port), f"{user}@127.0.0.1"],
                capture_output=True,
                env=env,
            )
            if shared.returncode == 0 or UNTRUSTED not in shared.stdout:
                print(
                    "the trust probe reused a connection another identity "
                    "authenticated instead of logging in with the selected one",
                    file=sys.stderr,
                )
                print(f"{shared.stdout}\n{shared.stderr}", file=sys.stderr)
                return 1

            trusted = run_prerequisites(canonical, "")
            if trusted.returncode != 0:
                print(
                    "the trust probe refused the selected identity although the "
                    "target trusts it",
                    file=sys.stderr,
                )
                print(f"{trusted.stdout}\n{trusted.stderr}", file=sys.stderr)
                return 1
        finally:
            sshd.terminate()
            sshd.wait()

    print(
        "ok: Proxmox trust holds only when the selected identity itself "
        "authenticates to the configured target"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
