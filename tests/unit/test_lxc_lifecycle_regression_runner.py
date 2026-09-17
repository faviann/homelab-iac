"""Execution-boundary tests for the lifecycle regression runner."""

from __future__ import annotations

import contextlib
import importlib.util
import os
from pathlib import Path
import threading
from types import ModuleType
from typing import Mapping

import pytest


RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / "regression"
    / "run_lxc_lifecycle_regressions.py"
)


def load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "lxc_lifecycle_regression_runner", RUNNER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def passing_result(script: str) -> tuple[str, int, float, str]:
    return script, 0, 0.0, ""


def recording_launcher(launched: list[str]):
    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        launched.append(script)
        return passing_result(script)

    return launch


def test_only_selects_registered_launchers_in_supplied_order() -> None:
    runner = load_runner()
    launched: list[str] = []
    selected = [runner.FULL_ONLY_SCRIPTS[0], runner.FAST_SCRIPTS[1]]

    assert runner.main(
        [argument for script in selected for argument in ("--only", script)],
        launcher=recording_launcher(launched),
    ) == 0
    assert launched == selected


@pytest.mark.parametrize(
    "target",
    [
        "lxc_docker_runtime_daemon_options_launcher.py",
        "lxc_nvidia_runtime_repository_launcher.py",
        "lxc_spec_invalid_guest_bootstrap_launcher.py",
    ],
)
def test_expensive_ansible_launcher_is_registered_once_as_full_only(
    target: str,
) -> None:
    runner = load_runner()
    launched: list[str] = []

    assert runner.FULL_ONLY_SCRIPTS.count(target) == 1
    assert target not in runner.FAST_SCRIPTS
    assert runner.REGISTERED_SCRIPTS.count(target) == 1

    assert runner.main(
        ["--only", target], launcher=recording_launcher(launched)
    ) == 0
    assert launched == [target]


def test_only_and_full_are_rejected_before_launch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = load_runner()
    launched: list[str] = []

    with pytest.raises(SystemExit) as error:
        runner.main(
            ["--full", "--only", runner.FAST_SCRIPTS[0]],
            launcher=recording_launcher(launched),
        )

    assert error.value.code == 2
    assert launched == []
    assert "--only cannot be combined with --full" in capsys.readouterr().err


def test_unknown_launcher_is_rejected_with_registered_names(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = load_runner()
    launched: list[str] = []

    with pytest.raises(SystemExit) as error:
        runner.main(["--only", "missing.py"], launcher=recording_launcher(launched))

    stderr = capsys.readouterr().err
    assert error.value.code == 2
    assert launched == []
    assert "unknown lifecycle launcher: missing.py" in stderr
    assert runner.FAST_SCRIPTS[0] in stderr
    assert runner.FULL_ONLY_SCRIPTS[-1] in stderr


def test_scheduling_classes_partition_the_registry() -> None:
    runner = load_runner()
    classes = (
        runner.FAST_SCRIPTS,
        runner.POOLED_SCRIPTS,
        runner.SERIAL_ONLY_SCRIPTS,
    )

    scheduled = [script for scheduling_class in classes for script in scheduling_class]

    assert sorted(scheduled) == sorted(runner.REGISTERED_SCRIPTS)
    assert len(set(scheduled)) == len(scheduled)
    for script in runner.REGISTERED_SCRIPTS:
        assert sum(script in scheduling_class for scheduling_class in classes) == 1


def test_serial_exclusions_are_never_scheduled_into_the_pool() -> None:
    runner = load_runner()
    pooled: list[str] = []

    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        if environment["ANSIBLE_CACHE_PLUGIN_CONNECTION"].endswith(
            f"fact-cache-{script.removesuffix('.py')}"
        ):
            pooled.append(script)
        return passing_result(script)

    assert runner.main(["--full"], launcher=launch) == 0
    assert set(runner.SERIAL_ONLY_SCRIPTS).isdisjoint(pooled)
    assert sorted(pooled) == sorted(runner.POOLED_SCRIPTS)
    for excluded in runner.SERIAL_ONLY_SCRIPTS:
        assert excluded in runner.FULL_ONLY_SCRIPTS


def test_pool_runs_at_the_bound_and_never_above_it() -> None:
    runner = load_runner()
    # Pinned, not read-and-trusted: 2 is the value issue #319 measured, and no
    # other bound has evidence behind it. The assertions below only prove the
    # pool honours whatever bound is configured, so changing it has to be a
    # deliberate edit here too.
    assert runner.POOL_MAX_WORKERS == 2
    bound = runner.POOL_MAX_WORKERS
    reached_bound = threading.Event()
    gave_up = threading.Event()
    guard = threading.Lock()
    concurrency = {"active": 0, "peak": 0}

    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        if script not in runner.POOLED_SCRIPTS:
            return passing_result(script)
        with guard:
            concurrency["active"] += 1
            concurrency["peak"] = max(concurrency["peak"], concurrency["active"])
            if concurrency["active"] >= bound:
                reached_bound.set()
        # Hold the slot until the pool has been seen running at its bound, so a
        # pool that only ever ran one launcher at a time would fail this test.
        # A serialized pool can never set the event, so the first launcher to
        # time out waives the wait for the rest: the test still fails, but in
        # seconds rather than once every pooled launcher has waited in turn.
        if not gave_up.is_set() and not reached_bound.wait(timeout=2):
            gave_up.set()
        with guard:
            concurrency["active"] -= 1
        return passing_result(script)

    assert runner.main(["--full"], launcher=launch) == 0
    assert reached_bound.is_set()
    assert concurrency["peak"] == bound


def test_full_fail_fast_finishes_running_fast_launchers_without_starting_full_only() -> None:
    runner = load_runner()
    launched: list[str] = []

    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        launched.append(script)
        return script, int(script == runner.FAST_SCRIPTS[0]), 0.0, "failure"

    assert runner.main(["--full", "--fail-fast"], launcher=launch) == 1
    assert set(launched) == set(runner.FAST_SCRIPTS)
    assert not set(launched).intersection(runner.FULL_ONLY_SCRIPTS)


def test_full_fail_fast_stops_pool_scheduling_but_reports_in_flight_launchers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = load_runner()
    launched: list[str] = []
    reported: list[str] = []
    failing_script = runner.POOLED_SCRIPTS[0]
    failure_reported = threading.Event()

    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        launched.append(script)
        if script in runner.POOLED_SCRIPTS and script != failing_script:
            # Hold every pooled sibling until the failure has been reported, so
            # the run cannot race ahead of the stop point: only the failure can
            # complete first, and scheduling must already have stopped by the
            # time anything else finishes. Without this the assertions below
            # would depend on how fast the collecting thread happens to be.
            failure_reported.wait(timeout=10)
        return script, int(script == failing_script), 0.0, "failure"

    original_report = runner.report

    def record(result: tuple[str, int, float, str]) -> bool:
        reported.append(result[0])
        outcome = original_report(result)
        if result[0] == failing_script:
            failure_reported.set()
        return outcome

    runner.report = record

    assert runner.main(["--full", "--fail-fast"], launcher=launch) == 1

    pooled_launched = [script for script in launched if script in runner.POOLED_SCRIPTS]
    # Exactly the first wave ran: the failure plus the one sibling already in
    # flight beside it. Every later candidate was never scheduled.
    assert sorted(pooled_launched) == sorted(
        runner.POOLED_SCRIPTS[: runner.POOL_MAX_WORKERS]
    )
    # The in-flight sibling still finished and was reported, not abandoned.
    assert set(pooled_launched).issubset(reported)
    assert set(runner.SERIAL_ONLY_SCRIPTS).isdisjoint(launched)
    assert f"failed: {failing_script}" in capsys.readouterr().err


def test_targeted_fail_fast_stops_after_first_failure() -> None:
    runner = load_runner()
    selected = list(runner.REGISTERED_SCRIPTS[:3])
    launched: list[str] = []

    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        launched.append(script)
        return script, int(script == selected[1]), 0.0, "failure"

    arguments = [
        argument for script in selected for argument in ("--only", script)
    ]
    assert runner.main([*arguments, "--fail-fast"], launcher=launch) == 1
    assert launched == selected[:2]


def test_default_fast_path_starts_both_launchers_concurrently() -> None:
    runner = load_runner()
    both_started = threading.Barrier(len(runner.FAST_SCRIPTS))
    launched: list[str] = []

    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        launched.append(script)
        both_started.wait(timeout=2)
        return passing_result(script)

    assert runner.main([], launcher=launch) == 0
    assert set(launched) == set(runner.FAST_SCRIPTS)


def test_full_path_without_fail_fast_aggregates_all_launcher_results(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = load_runner()
    launched: list[str] = []
    failing_scripts = {
        runner.FAST_SCRIPTS[0],
        runner.POOLED_SCRIPTS[1],
    }

    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        launched.append(script)
        return script, int(script in failing_scripts), 0.0, "failure"

    assert runner.main(["--full"], launcher=launch) == 1
    # Pool completion order is nondeterministic, so the run is accounted for by
    # membership and count, not by sequence.
    assert set(launched[: len(runner.FAST_SCRIPTS)]) == set(runner.FAST_SCRIPTS)
    assert sorted(launched) == sorted(runner.REGISTERED_SCRIPTS)
    assert launched[-len(runner.SERIAL_ONLY_SCRIPTS) :] == list(
        runner.SERIAL_ONLY_SCRIPTS
    )
    # The failure line stays in registration order whatever the completion order.
    assert (
        f"failed: {runner.FAST_SCRIPTS[0]}, {runner.POOLED_SCRIPTS[1]}"
        in capsys.readouterr().err
    )


def test_full_path_ok_line_counts_every_registered_launcher(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = load_runner()

    assert runner.main(
        ["--full"], launcher=lambda script, environment: passing_result(script)
    ) == 0
    assert (
        f"ok: full lifecycle regression set passed "
        f"({len(runner.REGISTERED_SCRIPTS)} launchers)"
    ) in capsys.readouterr().out


def test_pooled_launchers_get_private_fact_cache_namespaces_serial_paths_share_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_runner()
    operator_cache = "/operator-cache-that-must-not-be-written"
    monkeypatch.setenv("ANSIBLE_CACHE_PLUGIN_CONNECTION", operator_cache)
    namespaces: dict[str, str] = {}

    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        namespaces[script] = environment["ANSIBLE_CACHE_PLUGIN_CONNECTION"]
        # The process-global namespace is never mutated, so it cannot leak
        # between concurrently scheduled launchers.
        assert os.environ["ANSIBLE_CACHE_PLUGIN_CONNECTION"] == operator_cache
        return passing_result(script)

    assert runner.main(["--full"], launcher=launch) == 0

    pooled = {namespaces[script] for script in runner.POOLED_SCRIPTS}
    assert len(pooled) == len(runner.POOLED_SCRIPTS)
    serial = {
        namespaces[script]
        for script in runner.FAST_SCRIPTS + runner.SERIAL_ONLY_SCRIPTS
    }
    assert len(serial) == 1
    assert serial.isdisjoint(pooled)
    assert operator_cache not in pooled | serial
    assert os.environ["ANSIBLE_CACHE_PLUGIN_CONNECTION"] == operator_cache


def test_per_launcher_cache_namespaces_are_removed_when_the_run_ends() -> None:
    runner = load_runner()
    namespaces: list[Path] = []

    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        namespace = Path(environment["ANSIBLE_CACHE_PLUGIN_CONNECTION"])
        namespace.mkdir(parents=True, exist_ok=True)
        (namespace / "fact.json").write_text("{}")
        namespaces.append(namespace)
        return script, int(script == runner.POOLED_SCRIPTS[0]), 0.0, "failure"

    assert runner.main(["--full", "--fail-fast"], launcher=launch) == 1
    assert namespaces
    assert not [namespace for namespace in namespaces if namespace.exists()]


def test_targeted_launchers_inherit_validation_fixture_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_runner()
    fixture_root = RUNNER_PATH.parents[1] / "fixtures" / "ansible"
    original_vault = str(fixture_root / "vault-pass")
    original_inventory = str(fixture_root / "inventory.yml")
    original_cache_connection = "/operator-cache-that-must-not-be-written"
    monkeypatch.setenv("ANSIBLE_VAULT_PASSWORD_FILE", original_vault)
    monkeypatch.setenv("ANSIBLE_INVENTORY", original_inventory)
    monkeypatch.setenv("ANSIBLE_CACHE_PLUGIN_CONNECTION", original_cache_connection)

    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        assert environment["ANSIBLE_VAULT_PASSWORD_FILE"] == original_vault
        assert environment["ANSIBLE_INVENTORY"] == original_inventory
        assert environment["ANSIBLE_CACHE_PLUGIN_CONNECTION"] != (
            original_cache_connection
        )
        return passing_result(script)

    assert runner.main(
        ["--only", runner.FULL_ONLY_SCRIPTS[0]], launcher=launch
    ) == 0
    assert os.environ["ANSIBLE_VAULT_PASSWORD_FILE"] == original_vault
    assert os.environ["ANSIBLE_INVENTORY"] == original_inventory
    assert os.environ["ANSIBLE_CACHE_PLUGIN_CONNECTION"] == original_cache_connection


def test_direct_runner_replaces_operator_ansible_environment_with_repo_fixtures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_runner()
    fixture_root = RUNNER_PATH.parents[1] / "fixtures" / "ansible"
    operator_vault = "/operator/vault-password-that-must-not-be-read"
    operator_inventory = "/operator/inventory-that-must-not-be-read"
    monkeypatch.setenv("ANSIBLE_VAULT_PASSWORD_FILE", operator_vault)
    monkeypatch.setenv("ANSIBLE_INVENTORY", operator_inventory)

    def launch(
        script: str, environment: Mapping[str, str]
    ) -> tuple[str, int, float, str]:
        assert environment["ANSIBLE_VAULT_PASSWORD_FILE"] == str(
            fixture_root / "vault-pass"
        )
        assert environment["ANSIBLE_INVENTORY"] == str(
            fixture_root / "inventory.yml"
        )
        return passing_result(script)

    assert runner.main(
        ["--only", runner.FULL_ONLY_SCRIPTS[0]], launcher=launch
    ) == 0
    assert os.environ["ANSIBLE_VAULT_PASSWORD_FILE"] == operator_vault
    assert os.environ["ANSIBLE_INVENTORY"] == operator_inventory


def test_registry_matches_the_launcher_named_files() -> None:
    runner = load_runner()
    launcher_files = sorted(
        path.name for path in RUNNER_PATH.parent.glob("*_launcher.py")
    )

    assert sorted(runner.REGISTERED_SCRIPTS) == launcher_files
