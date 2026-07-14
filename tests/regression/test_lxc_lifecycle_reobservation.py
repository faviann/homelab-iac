#!/usr/bin/env python3
"""Regression test for post-action lifecycle re-observation of runtime state."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = (
    REPO_ROOT
    / "tests"
    / "regression"
    / "fixtures"
    / "lxc_lifecycle_reobservation_test.yml"
)
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lxc-lifecycle-reobservation-") as temp_dir:
        temp_root = Path(temp_dir)

        # Mock pct: report the live container as running so re-observation
        # refreshes the pre-action 'absent' runtime state.
        pct = temp_root / "pct"
        pct.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  status) echo 'status: running' ;;\n"
            "  *) exit 99 ;;\n"
            "esac\n"
        )
        pct.chmod(pct.stat().st_mode | stat.S_IXUSR)

        env = os.environ.copy()
        env["PATH"] = f"{temp_root}:{env['PATH']}"
        proc = subprocess.run(
            [*ANSIBLE_PLAYBOOK, str(PLAYBOOK)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )

        output = f"{proc.stdout}\n{proc.stderr}"
        if proc.returncode != 0:
            print("re-observation playbook failed unexpectedly", file=sys.stderr)
            print(output, file=sys.stderr)
            return 1

    print("ok: post-action re-observation refreshes runtime state before guest bootstrap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
