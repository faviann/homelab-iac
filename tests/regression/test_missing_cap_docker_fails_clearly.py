#!/usr/bin/env python3
"""Regression test for a clear missing-cap_docker failure."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "missing_cap_docker_test.yml"
ANSIBLE_PLAYBOOK = REPO_ROOT / ".ansible" / "venv" / "bin" / "ansible-playbook"


def main() -> int:
    if not ANSIBLE_PLAYBOOK.exists():
        print(f"missing ansible-playbook at {ANSIBLE_PLAYBOOK}", file=sys.stderr)
        return 1

    proc = subprocess.run(
        [str(ANSIBLE_PLAYBOOK), str(PLAYBOOK)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    output = f"{proc.stdout}\n{proc.stderr}"

    if proc.returncode == 0:
        print("playbook succeeded unexpectedly", file=sys.stderr)
        print(output, file=sys.stderr)
        return 1

    expected_markers = ["cap_docker", "docker_user", "docker_uid", "docker_gid"]
    if not any(marker in output for marker in expected_markers):
        print("failure message did not identify missing Docker capability inputs", file=sys.stderr)
        print(output, file=sys.stderr)
        return 1

    print("ok: missing cap_docker fails clearly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())