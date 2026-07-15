#!/usr/bin/env python3
"""Run the LXC lifecycle regression suite: fast feedback or full completion.

Thin runner only: it selects, launches, and reports the existing standalone
launchers. Every lifecycle scenario, input, and assertion stays in the
Ansible fixtures those launchers execute (see ADR 0007).

Fast path (default) — routine agent iteration:
  the semantic lifecycle facade matrix (planning, lifecycle intent,
  persistent destructive policy, result classification, controlled
  execution outcomes) plus the targeted lifecycle planning barrier.
Full path (--full) — completion checks before handoff:
  everything the fast path covers, plus the remaining lifecycle seams,
  including slow host-configuration idempotence sequencing and the real
  role-composition wiring regression.

Both paths use controlled observations only: no live Proxmox, no vault
secrets, no machine-specific credentials.

Measured constraint (issue #28): the fast path runs in about 70s on the
control workstation, above the 30s target. The dominant remaining cost is
the two linear-strategy plan plays of the semantic facade matrix: the
lifecycle planning barrier aggregates every target's planning outcome with
run_once tasks, so those plays cannot use the free strategy, and each of
the facade role's many small tasks pays Ansible's per-task process cost.
Going lower would mean thinning the scenario matrix or moving lifecycle
policy into Python; both are ruled out (ADR 0007).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


TESTS = Path(__file__).resolve().parent
REPO_ROOT = TESTS.parents[1]

# Both fast launchers are internally parallel and fully isolated (per-run
# temp state directories), so the fast path runs them concurrently.
FAST_SCRIPTS = (
    "test_lxc_lifecycle_decision.py",
    "test_lxc_lifecycle_planning_barrier.py",
)

# The rest of the lifecycle set runs sequentially: the host-configuration
# idempotence sequence and wiring regression are heavyweight, and sequential
# execution keeps their timing and failure attribution predictable.
FULL_ONLY_SCRIPTS = (
    "test_lxc_lifecycle_invalid_state.py",
    "test_lxc_lifecycle_guest_bootstrap_contract.py",
    "test_lxc_spec_contract.py",
    "test_lxc_spec_invalid_guest_bootstrap.py",
    "test_lxc_spec_layer_merge.py",
    "test_proxmox_lxc_provision_contract.py",
    "test_proxmox_lxc_lifecycle_configure_check_mode_absent.py",
    "test_lxc_manual_ssh_recovery.py",
    "test_lxc_ssh_key_injector_identity_mismatch.py",
    "test_lxc_fleet_preflight.py",
    "test_proxmox_lxc_host_config_check_mode_missing_config.py",
    "test_proxmox_lxc_host_config_observation_failure.py",
    "test_lxc_lifecycle_wiring.py",
    "test_proxmox_lxc_host_config_result.py",
)


def run_script(script: str) -> tuple[str, int, float, str]:
    start = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(TESTS / script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    wall = time.monotonic() - start
    return script, proc.returncode, wall, f"{proc.stdout}\n{proc.stderr}"


def report(result: tuple[str, int, float, str]) -> bool:
    script, returncode, wall, output = result
    status = "PASS" if returncode == 0 else "FAIL"
    print(f"{status}  {script}  ({wall:.1f}s)", flush=True)
    if returncode != 0:
        print(output, file=sys.stderr, flush=True)
    return returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="run the complete lifecycle regression set, not just fast feedback",
    )
    args = parser.parse_args()

    failed = []
    launched = 0
    with ThreadPoolExecutor(max_workers=len(FAST_SCRIPTS)) as executor:
        for result in executor.map(run_script, FAST_SCRIPTS):
            launched += 1
            if not report(result):
                failed.append(result[0])
    if args.full:
        for script in FULL_ONLY_SCRIPTS:
            launched += 1
            if not report(run_script(script)):
                failed.append(script)

    if failed:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
        return 1

    label = "full lifecycle regression set" if args.full else "fast lifecycle feedback path"
    print(f"ok: {label} passed ({launched} launchers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
