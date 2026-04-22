#!/usr/bin/env python3
"""Regression test for missing required stack_vars during stack sync render."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "stack_sync_missing_required_stack_vars_test.yml"
ANSIBLE_PLAYBOOK = REPO_ROOT / ".ansible" / "venv" / "bin" / "ansible-playbook"


def main() -> int:
    if not ANSIBLE_PLAYBOOK.exists():
        print(f"missing ansible-playbook at {ANSIBLE_PLAYBOOK}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="stack-sync-missing-required-stack-vars-") as temp_root:
        env = os.environ.copy()
        env["ANSIBLE_LOCAL_TEMP"] = temp_root
        env["TMPDIR"] = temp_root
        proc = subprocess.run(
            [
                str(ANSIBLE_PLAYBOOK),
                str(PLAYBOOK),
                "-e",
                f"temp_root={temp_root}",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )

    output = f"{proc.stdout}\n{proc.stderr}"

    if proc.returncode == 0:
        print("expected playbook to fail when required stack vars are missing", file=sys.stderr)
        print(output, file=sys.stderr)
        return 1

    markers = ["stack_vars", "komga_password"]
    missing = [marker for marker in markers if marker not in output]
    has_failure_kind = ("undefined" in output) or ("has no attribute" in output)
    if missing or not has_failure_kind:
        print("playbook failed, but not with the expected missing stack vars output", file=sys.stderr)
        if missing:
            print(f"missing fragments: {missing}", file=sys.stderr)
        if not has_failure_kind:
            print("missing failure kind marker: undefined or has no attribute", file=sys.stderr)
        print(output, file=sys.stderr)
        return 1

    print("ok: missing required stack vars fail clearly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
