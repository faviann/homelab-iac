#!/usr/bin/env python3
"""Regression test for proxmox_lxc_host_config boundary results."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "proxmox_lxc_host_config_test.yml"
ANSIBLE_PLAYBOOK = REPO_ROOT / ".ansible" / "venv" / "bin" / "ansible-playbook"


def main() -> int:
    if not ANSIBLE_PLAYBOOK.exists():
        print(f"missing ansible-playbook at {ANSIBLE_PLAYBOOK}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="proxmox-lxc-host-config-") as temp_root:
        proc = subprocess.run(
            [str(ANSIBLE_PLAYBOOK), str(PLAYBOOK), "-e", f"temp_root={temp_root}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )

    output = f"{proc.stdout}\n{proc.stderr}"

    if proc.returncode != 0:
        print("playbook failed unexpectedly", file=sys.stderr)
        print(output, file=sys.stderr)
        return 1

    print("ok: proxmox_lxc_host_config reports component changes and restart state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())