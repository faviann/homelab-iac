#!/usr/bin/env python3
"""Regression for busy-check deferral through the production lifecycle facade."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures"
ASSETS = FIXTURES / "lxc_busy_check_assets"
FACADE_ASSETS = FIXTURES / "lxc_lifecycle_facade_assets"
INVENTORY = FIXTURES / "lxc_busy_check_inventory.yml"
PLAYBOOK = FIXTURES / "lxc_busy_check_test.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lxc-busy-check-") as temp_dir:
        state_dir = Path(temp_dir)
        docker_log = state_dir / "docker.log"
        docker_log.write_text("", encoding="utf-8")

        env = os.environ.copy()
        env["PATH"] = f"{ASSETS / 'bin'}:{FACADE_ASSETS / 'bin'}:{env['PATH']}"
        env["LIFECYCLE_TEST_STATE_DIR"] = str(state_dir)
        env["BUSY_CHECK_DOCKER_LOG"] = str(docker_log)
        env["HOMELAB_IAC_LIFECYCLE_WRAPPER"] = "1"
        env["ANSIBLE_ROLES_PATH"] = os.pathsep.join(
            [str(ASSETS / "roles"), str(FACADE_ASSETS / "roles"), str(REPO_ROOT / "playbooks" / "roles")]
        )
        env["ANSIBLE_COLLECTIONS_PATH"] = os.pathsep.join(
            [str(FACADE_ASSETS / "collections"), str(REPO_ROOT / "collections")]
        )
        proc = subprocess.run(
            [
                *ANSIBLE_PLAYBOOK,
                "-i",
                str(INVENTORY),
                str(PLAYBOOK),
                "-e",
                f"lifecycle_test_state_dir={state_dir}",
                "-e",
                f"busy_check_repo_root={REPO_ROOT}",
                "-e",
                f"lxc_busy_check_deferral_file={state_dir / 'deferrals'}",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        if proc.returncode != 0:
            print("busy-check deferral regression failed", file=sys.stderr)
            print(f"{proc.stdout}\n{proc.stderr}", file=sys.stderr)
            return 1

    print("ok: busy checks defer busy stacks and their host steps, and nothing else")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
