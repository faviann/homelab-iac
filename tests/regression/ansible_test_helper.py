"""Shared construction of credential-free Ansible regression environments."""

from __future__ import annotations

import os
import socket
import socketserver
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/ansible"
FIXTURE_INVENTORY = FIXTURE_ROOT / "inventory.yml"
FIXTURE_VAULT_PASSWORD_FILE = FIXTURE_ROOT / "vault-pass"
# A playbook that outlives its caller loses its stdout reader, and the free
# strategy then spins forever on a task it failed to queue. Die with the caller.
ANSIBLE_PLAYBOOK = ["setpriv", "--pdeathsig", "TERM", "uv", "run", "--locked", "ansible-playbook"]
SSHD = Path("/usr/sbin/sshd")

# Runs the fleet lease's remote command locally with /run rewritten to a temp
# dir, so no test reaches the real Proxmox host.
FAKE_PROXMOX_SSH = """#!/bin/bash
printf '%s\\n' "$@" >"$FAKE_SSH_ARGV"
lock="$HOME/.ansible/homelab-iac-lifecycle.lock"
flock --nonblock "$lock" true && { echo "ssh ran without the machine-local lock" >&2; exit 99; }
for fd in /proc/$$/fd/* /proc/$PPID/fd/*; do
    [[ "$(readlink "$fd")" == "$lock" ]] && { echo "ssh or its coproc inherited the machine-local lock" >&2; exit 98; }
done
case "${FAKE_SSH_PROXMOX:-free}" in
    unreachable) echo "ssh: connect to host proxmox.lan port 22: No route to host" >&2; exit 255 ;;
    untrusted) echo "Host key verification failed." >&2; exit 255 ;;
esac
remote=${!#}
exec bash -c "${remote//\\/run\\//$FAKE_SSH_FLEET_DIR/}"
"""


def fake_proxmox_ssh(bin_dir: Path, fleet_dir: Path, proxmox: str = "free") -> dict[str, str]:
    fleet_dir.mkdir(parents=True, exist_ok=True)
    fake_ssh = bin_dir / "ssh"
    fake_ssh.write_text(FAKE_PROXMOX_SSH, encoding="utf-8")
    fake_ssh.chmod(0o755)
    return {
        "FAKE_SSH_ARGV": str(fleet_dir / "ssh-argv"),
        "FAKE_SSH_FLEET_DIR": str(fleet_dir),
        "FAKE_SSH_PROXMOX": proxmox,
    }


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


def ansible_playbook_command(
    *arguments: str,
    supplies_own_inventory: bool = False,
) -> list[str]:
    """Return a locked playbook command under the validation fixture boundary."""
    if (
        not supplies_own_inventory
        and os.environ.get("ANSIBLE_INVENTORY") != str(FIXTURE_INVENTORY)
    ):
        raise AssertionError(
            "ANSIBLE_INVENTORY is outside the fixture environment; "
            "run this test through ./validate.sh tests"
        )
    if os.environ.get("ANSIBLE_VAULT_PASSWORD_FILE") != str(
        FIXTURE_VAULT_PASSWORD_FILE
    ):
        raise AssertionError(
            "ANSIBLE_VAULT_PASSWORD_FILE is outside the fixture environment; "
            "run this test through ./validate.sh tests"
        )
    return [*ANSIBLE_PLAYBOOK, *arguments]


def write_fleet_key(
    home: Path,
    *,
    name: str = "proxmox_lxc",
    passphrase: str = "",
) -> Path:
    """Generate a throwaway fleet key under a fixture ``HOME``."""
    private_key = home / ".ansible" / "ssh" / name
    private_key.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", passphrase, "-f", str(private_key),
         "-C", "regression-fixture"],
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    return private_key


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


@contextmanager
def local_sshd(root: Path) -> Iterator[int]:
    """Run an unprivileged sshd on 127.0.0.1 that trusts ``root/authorized_keys``.

    The caller writes that file, before or while the server runs: sshd reads it
    on every login. Yields the listening port.
    """
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(root / "host_key")],
        check=True,
        capture_output=True,
    )
    port = free_port()
    (root / "sshd_config").write_text(SSHD_CONFIG.format(port=port, root=root))
    with (root / "sshd.log").open("w", encoding="utf-8") as log:
        sshd = subprocess.Popen(
            [str(SSHD), "-D", "-e", "-f", str(root / "sshd_config")],
            stdout=subprocess.DEVNULL,
            stderr=log,
        )
        try:
            wait_for_port(port)
            yield port
        finally:
            sshd.terminate()
            sshd.wait()


class _SshPortHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        return


@contextmanager
def local_ssh_port() -> Iterator[int]:
    """Bind a listening port so a trust probe fails on authentication, not reachability."""
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SshPortHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
