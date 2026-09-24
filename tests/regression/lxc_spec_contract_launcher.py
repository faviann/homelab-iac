#!/usr/bin/env python3
"""Regression test for LXC contract compilation: layer precedence, slices, and
rejection of a contract without a guest-bootstrap public key."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "lxc_spec_contract_test.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command()


def main() -> int:
    proc = subprocess.run(
        [*ANSIBLE_PLAYBOOK, str(PLAYBOOK)],
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

    print("ok: compiled LXC contract preserves precedence and slices, and rejects a keyless contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())