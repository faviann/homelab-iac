#!/usr/bin/env python3
"""Thin runner for the Ansible-native semantic lifecycle facade fixture."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures"
ASSETS = FIXTURES / "lxc_lifecycle_facade_assets"
INVENTORY = FIXTURES / "lxc_lifecycle_facade_inventory.yml"
PLAYBOOKS = (
    FIXTURES / "lxc_lifecycle_decision_test.yml",
    FIXTURES / "lxc_lifecycle_plan_ephemerality_test.yml",
)
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lxc-lifecycle-facade-") as temp_dir:
        temp_root = Path(temp_dir)
        state_dir = temp_root / "state"
        cache_dir = temp_root / "cache"
        home_dir = temp_root / "home"
        state_dir.mkdir()
        cache_dir.mkdir()
        (home_dir / ".ssh").mkdir(parents=True)

        env = os.environ.copy()
        env["PATH"] = f"{ASSETS / 'bin'}:{env['PATH']}"
        env["LIFECYCLE_TEST_STATE_DIR"] = str(state_dir)
        env["ANSIBLE_ROLES_PATH"] = os.pathsep.join(
            [str(ASSETS / "roles"), str(REPO_ROOT / "playbooks" / "roles")]
        )
        env["ANSIBLE_COLLECTIONS_PATH"] = os.pathsep.join(
            [str(ASSETS / "collections"), str(REPO_ROOT / "collections")]
        )
        env["ANSIBLE_CACHE_PLUGIN_CONNECTION"] = str(cache_dir)
        env["ANSIBLE_VAULT_PASSWORD_FILE"] = str(
            Path.home() / ".ansible" / "vault-pass"
        )
        env["HOME"] = str(home_dir)

        for playbook in PLAYBOOKS:
            proc = subprocess.run(
                [
                    *ANSIBLE_PLAYBOOK,
                    "-i",
                    str(INVENTORY),
                    str(playbook),
                    "-e",
                    f"lifecycle_test_state_dir={state_dir}",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                env=env,
            )
            if proc.returncode != 0:
                print(f"{playbook.name} failed unexpectedly", file=sys.stderr)
                print(f"{proc.stdout}\n{proc.stderr}", file=sys.stderr)
                return 1

    print("ok: lifecycle facade publishes semantic results and plans remain command-local")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
