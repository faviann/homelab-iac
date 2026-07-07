#!/usr/bin/env python3
"""Regression test for overmind Postgres database and role bootstrap."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "overmind_postgres_bootstrap_test.yml"
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="overmind-postgres-bootstrap-") as temp_root:
        proc = subprocess.run(
            [*ANSIBLE_PLAYBOOK, str(PLAYBOOK), "-e", f"temp_root={temp_root}"],
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

    print("ok: overmind Postgres bootstrap is re-runnable and docker-exec scoped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
