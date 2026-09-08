#!/usr/bin/env python3
"""Regression test for authoritative Proxmox LXC host configuration."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures"
ANSIBLE_PLAYBOOK = ansible_playbook_command()

# The exhaustive authoritative/reorder/reduction sequence runs once, under a
# single locale. Only the comparison seams are locale-sensitive, and they are
# reached by any converged reconciliation, so the alternate locale runs the
# narrow converged fixture instead of repeating unrelated lifecycle
# transitions.
SCENARIOS = (
    ("C.UTF-8", FIXTURES / "proxmox_lxc_host_config_test.yml"),
    ("en_US.UTF-8", FIXTURES / "proxmox_lxc_host_config_locale_test.yml"),
)


def main() -> int:
    for locale_name, playbook in SCENARIOS:
        env = os.environ.copy()
        env.update(LANG=locale_name, LC_ALL=locale_name)

        with tempfile.TemporaryDirectory(prefix="proxmox-lxc-host-config-") as temp_root:
            proc = subprocess.run(
                [*ANSIBLE_PLAYBOOK, str(playbook), "-e", f"temp_root={temp_root}"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                env=env,
            )

        output = f"{proc.stdout}\n{proc.stderr}"

        if proc.returncode != 0:
            print(
                f"{playbook.name} failed unexpectedly under {locale_name}",
                file=sys.stderr,
            )
            print(output, file=sys.stderr)
            return 1

    print(
        "ok: proxmox_lxc_host_config is authoritative and reorder-safe under "
        "C.UTF-8, and its managed comparisons stay converged under en_US.UTF-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
