#!/usr/bin/env python3
"""Regression test for lifecycle decision and publish boundary scenarios."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "lxc_lifecycle_decision_test.yml"
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


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

    print("ok: lifecycle decision and publish boundary scenarios passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())