#!/usr/bin/env python3
"""Run the LXC lifecycle regression suite: fast feedback or full completion.

Thin runner only: it selects, launches, and reports the existing standalone
launchers. Every lifecycle scenario, input, and assertion stays in the
Ansible fixtures those launchers execute (see ADR 0007).

Launchers are the `*_launcher.py` files beside this runner. They are
standalone scripts, not pytest tests: pytest's default collection patterns
are `test_*.py` and `*_test.py`, and a `*_launcher.py` name matches neither,
so the two ownership models never overlap and neither needs suppression.

Fast path (default) — routine agent iteration:
  the semantic lifecycle facade matrix (planning, lifecycle intent,
  persistent destructive policy, result classification, controlled
  execution outcomes) plus the targeted lifecycle planning barrier.
Full path (--full) — completion checks before handoff:
  everything the fast path covers, plus the remaining lifecycle seams,
  including slow host-configuration idempotence sequencing and the real
  role-composition wiring regression. After the fast stage, those seams run
  through a bounded pool (POOL_MAX_WORKERS) with a private fact-cache
  namespace per launcher, except the SERIAL_ONLY_SCRIPTS pair, which stays
  sequential. Report order therefore follows completion, not registration.
Targeted path (--only FILENAME, repeatable) — focused remediation:
  registered launchers run sequentially in the supplied order. Add
  --fail-fast to stop scheduling selected launchers after the first failure.
  With --full, fail-fast still lets the concurrent fast launchers finish and
  then never starts the full-only phase; a failure inside that phase stops
  scheduling new launchers while in-flight ones finish and are reported.

Both paths use controlled observations only: no live Proxmox, no vault
secrets, no machine-specific credentials.

Lifecycle planning keeps compilation and semantic plan construction in
independently scheduled Ansible plays. Fleet preflight and the all-target
planning barrier run only after their preceding target-local phase completes;
production execution remains linear. This preserves the full Ansible-native
scenario matrix while avoiding target-local planner task waves at the
targeted-set coordination seams (issue #44).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable, Mapping, Sequence


TESTS = Path(__file__).resolve().parent
REPO_ROOT = TESTS.parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "ansible"
FIXTURE_ENVIRONMENT = {
    "ANSIBLE_INVENTORY": str(FIXTURE_ROOT / "inventory.yml"),
    "ANSIBLE_VAULT_PASSWORD_FILE": str(FIXTURE_ROOT / "vault-pass"),
}

# Both fast launchers are internally parallel and isolated by their own per-run
# temp state directories, so the fast path runs them concurrently. They share
# the run-level fact-cache namespace rather than taking private ones: that is
# safe only because exactly one of the two writes to it (the decision launcher
# sets its own ANSIBLE_CACHE_PLUGIN_CONNECTION). A third fast launcher that
# inherits the run-level namespace would need pooled_environment() too.
FAST_SCRIPTS = (
    "lxc_lifecycle_decision_launcher.py",
    "lxc_lifecycle_planning_barrier_launcher.py",
)

# The rest of the lifecycle set runs only under --full. Most of it is
# scheduled through a bounded pool (see POOLED_SCRIPTS); the launchers named in
# SERIAL_ONLY_SCRIPTS stay sequential.
FULL_ONLY_SCRIPTS = (
    "lifecycle_run_lock_launcher.py",
    "inspect_command_launcher.py",
    "recover_command_launcher.py",
    "lxc_lifecycle_invalid_state_launcher.py",
    "lxc_lifecycle_guest_bootstrap_contract_launcher.py",
    "lxc_spec_contract_launcher.py",
    "proxmox_lxc_provision_contract_launcher.py",
    "proxmox_lxc_lifecycle_configure_check_mode_absent_launcher.py",
    "proxmox_lxc_lifecycle_observation_status_launcher.py",
    "lxc_manual_ssh_recovery_launcher.py",
    "proxmox_host_ssh_enrollment_launcher.py",
    "proxmox_host_ssh_trust_launcher.py",
    "lxc_ssh_key_injector_identity_mismatch_launcher.py",
    "lxc_fleet_preflight_launcher.py",
    "proxmox_lxc_host_config_check_mode_missing_config_launcher.py",
    "proxmox_lxc_host_config_observation_failure_launcher.py",
    "proxmox_lxc_host_config_readiness_deadline_launcher.py",
    "lxc_docker_runtime_daemon_options_launcher.py",
    "lxc_nvidia_runtime_repository_launcher.py",
    "lxc_lifecycle_wiring_launcher.py",
    "proxmox_lxc_host_config_result_launcher.py",
    "hawser_standard_remote_default_launcher.py",
    "controller_prerequisite_fact_cache_launcher.py",
)

# Both carry deliberate timing discrimination. Issue #319 challenged each under
# representative pool load and both held, but they stay sequential initially by
# decision, not by lack of evidence.
SERIAL_ONLY_SCRIPTS = (
    "lifecycle_run_lock_launcher.py",
    "proxmox_lxc_host_config_readiness_deadline_launcher.py",
)

# Derived, never hardcoded: a launcher added to FULL_ONLY_SCRIPTS is scheduled
# into the pool unless it is explicitly excluded above.
POOLED_SCRIPTS = tuple(
    script for script in FULL_ONLY_SCRIPTS if script not in SERIAL_ONLY_SCRIPTS
)

# Issue #319 measured this bound end to end (658.8s serial -> 399.4s bounded on
# the reference workstation) and validated no other value: no worker-count
# search was run and the bound is deliberately not derived from CPU count.
POOL_MAX_WORKERS = 2

REGISTERED_SCRIPTS = FAST_SCRIPTS + FULL_ONLY_SCRIPTS

LauncherResult = tuple[str, int, float, str]
Launcher = Callable[[str, Mapping[str, str]], LauncherResult]


def run_script(script: str, environment: Mapping[str, str]) -> LauncherResult:
    """Run one launcher with an explicitly supplied environment overlay.

    The overlay is passed to the child rather than written into this process's
    os.environ: concurrently scheduled launchers need distinct fact-cache
    namespaces, and a process-global namespace cannot provide that.
    """
    start = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(TESTS / script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, **environment},
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


def pooled_environment(
    environment: Mapping[str, str], cache_root: Path, script: str
) -> dict[str, str]:
    """Give one pooled launcher a fact-cache namespace no sibling shares.

    The run-level namespace is correct while launchers run one at a time; two
    launchers sharing one process would otherwise write into the same cache.
    Every namespace lives under the run's temporary root, so it is removed with
    it — on success, on failure, and on a fail-fast exit.
    """
    return {
        **environment,
        "ANSIBLE_CACHE_PLUGIN_CONNECTION": str(
            cache_root / f"fact-cache-{script.removesuffix('.py')}"
        ),
    }


def run_serially(
    scripts: Sequence[str],
    *,
    launcher: Launcher,
    environment: Mapping[str, str],
    fail_fast: bool,
) -> tuple[list[str], int]:
    """Run scripts one at a time in the supplied order, sharing one namespace."""
    failed: list[str] = []
    launched = 0
    for script in scripts:
        launched += 1
        if not report(launcher(script, environment)):
            failed.append(script)
            if fail_fast:
                break
    return failed, launched


def run_pooled(
    scripts: Sequence[str],
    *,
    launcher: Launcher,
    environment: Mapping[str, str],
    cache_root: Path,
    fail_fast: bool,
    max_workers: int = POOL_MAX_WORKERS,
) -> tuple[list[str], int]:
    """Run scripts through a pool of at most max_workers concurrent launchers.

    Completion order is not the registration order, so reports are emitted as
    each launcher finishes — always whole and from this thread only, never
    interleaved with a sibling's output. Under fail_fast the first observed
    failure stops scheduling; launchers already in flight finish and report.
    """
    failed: list[str] = []
    launched = 0
    pending = iter(scripts)
    in_flight: dict[Future[LauncherResult], str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:

        def schedule() -> None:
            while len(in_flight) < max_workers:
                script = next(pending, None)
                if script is None:
                    return
                future = executor.submit(
                    launcher,
                    script,
                    pooled_environment(environment, cache_root, script),
                )
                in_flight[future] = script

        schedule()
        scheduling = True
        while in_flight:
            done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in done:
                script = in_flight.pop(future)
                launched += 1
                if not report(future.result()):
                    failed.append(script)
                    if fail_fast:
                        scheduling = False
            if scheduling:
                schedule()
    return failed, launched


def run_regressions(
    *,
    full: bool,
    fail_fast: bool = False,
    only: Sequence[str] = (),
    launcher: Launcher = run_script,
    environment: Mapping[str, str],
    cache_root: Path,
) -> int:
    if only:
        failed, launched = run_serially(
            only, launcher=launcher, environment=environment, fail_fast=fail_fast
        )
        if failed:
            print(f"failed: {', '.join(failed)}", file=sys.stderr)
            return 1
        print(f"ok: targeted lifecycle regression set passed ({launched} launchers)")
        return 0

    failed: list[str] = []
    launched = 0
    with ThreadPoolExecutor(max_workers=len(FAST_SCRIPTS)) as executor:
        for result in executor.map(
            lambda script: launcher(script, environment), FAST_SCRIPTS
        ):
            launched += 1
            if not report(result):
                failed.append(result[0])
    if failed and fail_fast:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    if full:
        pool_failed, pool_launched = run_pooled(
            POOLED_SCRIPTS,
            launcher=launcher,
            environment=environment,
            cache_root=cache_root,
            fail_fast=fail_fast,
        )
        failed += pool_failed
        launched += pool_launched
        if not (failed and fail_fast):
            serial_failed, serial_launched = run_serially(
                SERIAL_ONLY_SCRIPTS,
                launcher=launcher,
                environment=environment,
                fail_fast=fail_fast,
            )
            failed += serial_failed
            launched += serial_launched

    if failed:
        ordered = sorted(failed, key=REGISTERED_SCRIPTS.index)
        print(f"failed: {', '.join(ordered)}", file=sys.stderr)
        return 1

    label = "full lifecycle regression set" if full else "fast lifecycle feedback path"
    print(f"ok: {label} passed ({launched} launchers)")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    launcher: Launcher = run_script,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="run the complete lifecycle regression set, not just fast feedback",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="FILENAME",
        help="run only this registered launcher (repeatable)",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop scheduling new launchers after a failure",
    )
    args = parser.parse_args(argv)
    if args.only and args.full:
        parser.error("--only cannot be combined with --full")
    unknown_scripts = [script for script in args.only if script not in REGISTERED_SCRIPTS]
    if unknown_scripts:
        parser.error(
            f"unknown lifecycle launcher: {unknown_scripts[0]}; "
            f"registered launchers: {', '.join(REGISTERED_SCRIPTS)}"
        )

    with tempfile.TemporaryDirectory(prefix="lxc-lifecycle-cache-") as temp_dir:
        cache_root = Path(temp_dir)
        # Keep documented direct runner invocations credential-free until the
        # supported targeted validation command replaces them. Under
        # ./validate.sh these are the same fixture values already inherited.
        #
        # Fixtures add fake hosts (e.g. s1_portal) that fact caching would
        # otherwise persist for up to the production TTL. Redirect the jsonfile
        # cache per run instead of forcing memory so within-run caching
        # semantics stay production-like while .ansible/cache stays untouched
        # (issue #89). The overlay is handed to each launcher explicitly rather
        # than written into os.environ, so pooled launchers can be given
        # private namespaces off this same root.
        environment = {
            **FIXTURE_ENVIRONMENT,
            "ANSIBLE_CACHE_PLUGIN_CONNECTION": str(cache_root / "fact-cache"),
        }
        return run_regressions(
            full=args.full,
            fail_fast=args.fail_fast,
            only=args.only,
            launcher=launcher,
            environment=environment,
            cache_root=cache_root,
        )


if __name__ == "__main__":
    raise SystemExit(main())
