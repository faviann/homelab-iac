#!/usr/bin/env python3
"""Grammar and boundary coverage for the non-live validation command."""

from __future__ import annotations

import fcntl
import json
import os
import shlex
import signal
import shutil
import subprocess
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "validate.sh"
FIXTURE_INVENTORY = str(REPO_ROOT / "tests/fixtures/ansible/inventory.yml")
FIXTURE_VAULT_PASSWORD_FILE = str(REPO_ROOT / "tests/fixtures/ansible/vault-pass")
OPERATOR_MARKER = "operator-secret-marker-4f2b"


def validation_environment(
    tmp_path: Path, *, fail_at: int = 0, sentinel_mode: int = 0o600
) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env python3
import fcntl
import json
import os
import sys
from pathlib import Path

capture = Path(os.environ["VALIDATE_TEST_CAPTURE"])
with (capture.with_suffix(".lock")).open("w", encoding="utf-8") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    commands = []
    if capture.exists():
        commands = json.loads(capture.read_text(encoding="utf-8"))
    commands.append({
        "argv": sys.argv[1:],
        "cache_connection": os.environ.get("ANSIBLE_CACHE_PLUGIN_CONNECTION"),
        "inventory": os.environ.get("ANSIBLE_INVENTORY"),
        "lifecycle_marker": os.environ.get("HOMELAB_IAC_LIFECYCLE_WRAPPER"),
        "vault_password_file": os.environ.get("ANSIBLE_VAULT_PASSWORD_FILE"),
    })
    capture.write_text(json.dumps(commands), encoding="utf-8")
    fcntl.flock(lock, fcntl.LOCK_UN)
if len(commands) == int(os.environ.get("VALIDATE_TEST_FAIL_AT", "0")):
    raise SystemExit(41)
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    env = os.environ.copy()
    env.pop("HOMELAB_IAC_LIFECYCLE_WRAPPER", None)
    env.update(
        {
            "ANSIBLE_INVENTORY": operator_sentinel(
                tmp_path, "inventory", sentinel_mode
            ),
            "ANSIBLE_VAULT_PASSWORD_FILE": operator_sentinel(
                tmp_path, "vault-pass", sentinel_mode
            ),
            "HOME": str(tmp_path / "home"),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "VALIDATE_TEST_CAPTURE": str(tmp_path / "commands.json"),
            "VALIDATE_TEST_FAIL_AT": str(fail_at),
        }
    )
    return env


def handoff_environment(
    tmp_path: Path,
    *,
    lifecycle_status: int = 0,
    pytest_status: int = 0,
    wait_phase: str = "none",
    interrupt_during_startup: bool = False,
    pytest_completes_before_failure: bool = False,
) -> dict[str, str]:
    bin_dir = tmp_path / "handoff-bin"
    bin_dir.mkdir()
    state_dir = tmp_path / "handoff-state"
    state_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        r'''#!/usr/bin/env python3
import json
import os
import signal
import sys
import time
from pathlib import Path


state = Path(os.environ["VALIDATE_TEST_STATE"])
events = state / "events.jsonl"
phase = "lint"
if any(item.endswith("run_lxc_lifecycle_regressions.py") for item in sys.argv):
    phase = "lifecycle"
elif "pytest" in sys.argv:
    phase = "pytest"


def record(kind: str) -> None:
    with events.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "kind": kind,
                    "phase": phase,
                    "pid": os.getpid(),
                    "pgid": os.getpgid(0),
                    "cache": os.environ.get("ANSIBLE_CACHE_PLUGIN_CONNECTION"),
                    "time": time.monotonic(),
                }
            )
            + "\n"
        )


def stop(signum: int, _frame: object) -> None:
    record(f"signal:{signum}")
    raise SystemExit(128 + signum)


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
record("start")

if phase == "lint":
    record("done")
    raise SystemExit(0)

(state / f"{phase}.started").touch()
if os.environ.get("VALIDATE_TEST_WAIT_PHASE") in {phase, "both"}:
    deadline = time.monotonic() + 10
    while not (state / "release").exists():
        if time.monotonic() >= deadline:
            raise SystemExit(88)
        time.sleep(0.01)

status = int(os.environ[f"VALIDATE_TEST_{phase.upper()}_STATUS"])
record("done")
print(f"fake-{phase}-output", flush=True)
raise SystemExit(status)
''',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    if interrupt_during_startup or pytest_completes_before_failure:
        real_setsid = shutil.which("setsid")
        assert real_setsid is not None
        fake_setsid = bin_dir / "setsid"
        marker = shlex.quote(str(state_dir / "setsid.started"))
        if interrupt_during_startup:
            script = f'''#!/usr/bin/env bash
set -euo pipefail
marker={marker}
if [[ "$*" == *pytest* ]]; then
    touch "$marker"
    parent_pid="$(ps -o ppid= -p "$$" | tr -d ' ')"
    kill -STOP "$parent_pid"
    sleep 1
fi
exec {shlex.quote(real_setsid)} "$@"
'''
        else:
            completed_marker = shlex.quote(str(state_dir / "pytest.completed"))
            script = f'''#!/usr/bin/env bash
set -euo pipefail
completed_marker={completed_marker}
if [[ "$*" == *pytest* ]]; then
    parent_pid="$(ps -o ppid= -p "$$" | tr -d ' ')"
    kill -STOP "$parent_pid"
    {shlex.quote(real_setsid)} --wait "$@" &
    child_pid="$!"
    if wait "$child_pid"; then
        child_status=0
    else
        child_status="$?"
    fi
    touch "$completed_marker"
    {{ sleep 0.1; kill -CONT "$parent_pid"; }} >/dev/null 2>&1 &
    disown
    exit "$child_status"
fi
exec {shlex.quote(real_setsid)} "$@"
'''
        fake_setsid.write_text(script, encoding="utf-8")
        fake_setsid.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "ANSIBLE_INVENTORY": operator_sentinel(tmp_path, "inventory"),
            "ANSIBLE_VAULT_PASSWORD_FILE": operator_sentinel(
                tmp_path, "vault-pass"
            ),
            "HOME": str(tmp_path / "home"),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "VALIDATE_TEST_STATE": str(state_dir),
            "VALIDATE_TEST_LIFECYCLE_STATUS": str(lifecycle_status),
            "VALIDATE_TEST_PYTEST_STATUS": str(pytest_status),
            "VALIDATE_TEST_WAIT_PHASE": wait_phase,
        }
    )
    return env


def handoff_events(tmp_path: Path) -> list[dict[str, object]]:
    events = tmp_path / "handoff-state/events.jsonl"
    if not events.exists():
        return []
    return [json.loads(line) for line in events.read_text().splitlines()]


def wait_for_handoff_marker(tmp_path: Path, marker: str) -> None:
    path = tmp_path / f"handoff-state/{marker}"
    deadline = time.monotonic() + 5
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {marker}")
        time.sleep(0.01)


def wait_for_process_stopped(process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 5
    while True:
        result = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(process.pid)],
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip().startswith("T"):
            return
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for validate.sh to stop")
        time.sleep(0.01)


def assert_handoff_process_groups_gone(tmp_path: Path) -> None:
    for event in handoff_events(tmp_path):
        if event["phase"] in {"lifecycle", "pytest"} and event["kind"] == "start":
            deadline = time.monotonic() + 2
            while True:
                try:
                    os.killpg(int(event["pgid"]), signal.SIGCONT)
                except ProcessLookupError:
                    break
                if time.monotonic() >= deadline:
                    pytest.fail(f"process group {event['pgid']} still exists")
                time.sleep(0.01)


def operator_sentinel(tmp_path: Path, name: str, mode: int = 0o600) -> str:
    """An operator input the command must neither read nor disclose.

    Two modes detect two different faults. At ``0o600`` the file reads like a
    real operator's inventory or vault-password file, so a disclosing read
    surfaces the marker in the command's own output. At ``0o000`` any
    unguarded read fails instead, aborting the command and showing up as a
    non-zero exit even when nothing is printed.
    """
    sentinel = tmp_path / f"operator-{name}"
    sentinel.write_text(f"{OPERATOR_MARKER}\n", encoding="utf-8")
    sentinel.chmod(mode)
    return str(sentinel)


def run_validation(
    env: dict[str, str],
    cwd: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(RUNNER), *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def captured_commands(tmp_path: Path) -> list[dict[str, object]]:
    capture = tmp_path / "commands.json"
    if not capture.exists():
        return []
    return json.loads(capture.read_text(encoding="utf-8"))


def child_kind(argv: list[str]) -> str:
    if "ansible-lint" in argv:
        return "lint"
    if any(item.endswith("run_lxc_lifecycle_regressions.py") for item in argv):
        return "lifecycle"
    if "stack_update_policy" in argv:
        return "stack"
    if "pytest" in argv:
        return "tests"
    return f"unrecognized:{' '.join(argv)}"


def child_kinds(commands: list[dict[str, object]]) -> list[str]:
    return [child_kind(entry["argv"]) for entry in commands]


def child_options(argv: list[str], marker: str) -> list[str]:
    """The arguments the command forwarded after the child it selected."""
    for index, item in enumerate(argv):
        if item == marker or item.endswith(marker):
            return argv[index + 1 :]
    raise AssertionError(f"{marker} missing from {argv}")


def assert_validation_caches_were_removed(
    commands: list[dict[str, object]], expected_count: int = 1
) -> None:
    cache_connections = {entry["cache_connection"] for entry in commands}
    assert len(cache_connections) == expected_count
    for cache_connection in cache_connections:
        assert isinstance(cache_connection, str)
        assert not Path(cache_connection).exists()


def assert_fixture_environment(
    commands: list[dict[str, object]], expected_cache_count: int = 1
) -> None:
    assert commands
    for entry in commands:
        assert entry["argv"][:2] == ["run", "--locked"]
        assert entry["inventory"] == FIXTURE_INVENTORY
        assert entry["vault_password_file"] == FIXTURE_VAULT_PASSWORD_FILE
        assert entry["lifecycle_marker"] is None
    assert_validation_caches_were_removed(commands, expected_cache_count)


# --- AC1 / AC6: the no-argument comprehensive handoff run -------------------


def test_no_argument_run_is_the_comprehensive_non_live_handoff_validation(
    tmp_path: Path,
) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, tmp_path)

    assert result.returncode == 0, result.stderr
    commands = captured_commands(tmp_path)
    kinds = child_kinds(commands)
    assert kinds[0] == "lint"
    assert set(kinds[1:]) == {"lifecycle", "tests"}
    lifecycle_command = next(
        command for command in commands if child_kind(command["argv"]) == "lifecycle"
    )
    assert child_options(lifecycle_command["argv"], "run_lxc_lifecycle_regressions.py") == [
        "--full"
    ]
    assert_fixture_environment(commands, expected_cache_count=3)
    assert not (Path(env["HOME"]) / ".ansible/homelab-iac-lifecycle.lock").exists()


def test_no_argument_handoff_overlaps_only_after_lint(
    tmp_path: Path,
) -> None:
    env = handoff_environment(tmp_path, wait_phase="both")
    process = subprocess.Popen(
        [str(RUNNER)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        wait_for_handoff_marker(tmp_path, "lifecycle.started")
        wait_for_handoff_marker(tmp_path, "pytest.started")
        events = handoff_events(tmp_path)
        kinds = [(event["phase"], event["kind"]) for event in events]
        assert kinds.index(("lint", "done")) < kinds.index(("lifecycle", "start"))
        assert kinds.index(("lint", "done")) < kinds.index(("pytest", "start"))
        caches = {
            event["cache"]
            for event in events
            if event["phase"] in {"lifecycle", "pytest"}
        }
        assert len(caches) == 2

        (tmp_path / "handoff-state/release").touch()
        stdout, stderr = process.communicate(timeout=10)

        assert process.returncode == 0, stderr
        assert "fake-lifecycle-output" in stdout
        assert "fake-pytest-output" in stdout
        assert all(not Path(cache).exists() for cache in caches)
        assert_handoff_process_groups_gone(tmp_path)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_lifecycle_failure_terminates_and_reports_the_pytest_sibling(
    tmp_path: Path,
) -> None:
    env = handoff_environment(tmp_path, lifecycle_status=41, wait_phase="pytest")

    result = run_validation(env, REPO_ROOT)

    assert result.returncode == 41
    assert "validate.sh: lifecycle failed (exit 41)" in result.stderr
    assert "validate.sh: pytest terminated after lifecycle failure (exit 143)" in result.stderr
    assert "validate.sh: pytest failed" not in result.stderr
    events = handoff_events(tmp_path)
    lifecycle_done = next(
        event for event in events if event["phase"] == "lifecycle" and event["kind"] == "done"
    )
    pytest_signal = next(
        event
        for event in events
        if event["phase"] == "pytest" and event["kind"] == "signal:15"
    )
    assert float(pytest_signal["time"]) - float(lifecycle_done["time"]) < 0.5
    assert_handoff_process_groups_gone(tmp_path)


def test_pytest_failure_terminates_and_reports_the_lifecycle_sibling(
    tmp_path: Path,
) -> None:
    env = handoff_environment(tmp_path, pytest_status=43, wait_phase="lifecycle")

    result = run_validation(env, REPO_ROOT)

    assert result.returncode == 43
    assert "validate.sh: lifecycle terminated after pytest failure (exit 143)" in result.stderr
    assert "validate.sh: lifecycle failed" not in result.stderr
    assert "validate.sh: pytest failed (exit 43)" in result.stderr
    events = handoff_events(tmp_path)
    pytest_done = next(
        event for event in events if event["phase"] == "pytest" and event["kind"] == "done"
    )
    lifecycle_signal = next(
        event
        for event in events
        if event["phase"] == "lifecycle" and event["kind"] == "signal:15"
    )
    assert float(lifecycle_signal["time"]) - float(pytest_done["time"]) < 0.5
    assert_handoff_process_groups_gone(tmp_path)


def test_handoff_preserves_both_organic_failures_observed_before_cleanup(
    tmp_path: Path,
) -> None:
    env = handoff_environment(
        tmp_path,
        lifecycle_status=41,
        pytest_status=43,
        pytest_completes_before_failure=True,
    )

    result = run_validation(env, REPO_ROOT)

    assert result.returncode in {41, 43}
    assert "validate.sh: lifecycle failed (exit 41)" in result.stderr
    assert "validate.sh: pytest failed (exit 43)" in result.stderr
    assert "terminated after" not in result.stderr
    assert (tmp_path / "handoff-state/pytest.completed").exists()
    assert_handoff_process_groups_gone(tmp_path)


def test_handoff_signal_during_partial_startup_reaps_the_started_group(
    tmp_path: Path,
) -> None:
    env = handoff_environment(tmp_path, interrupt_during_startup=True)
    process = subprocess.Popen(
        [str(RUNNER)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        wait_for_handoff_marker(tmp_path, "setsid.started")
        wait_for_process_stopped(process)
        os.kill(process.pid, signal.SIGCONT)
        os.kill(process.pid, signal.SIGINT)
        process.wait(timeout=10)

        assert process.returncode == 130
        assert not (tmp_path / "handoff-state/pytest.started").exists()
        assert_handoff_process_groups_gone(tmp_path)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


@pytest.mark.parametrize(
    ("signal_number", "expected_returncode"),
    [(signal.SIGINT, 130), (signal.SIGTERM, 143)],
)
def test_handoff_signal_cleanup_reaps_both_phase_process_groups(
    tmp_path: Path, signal_number: int, expected_returncode: int
) -> None:
    env = handoff_environment(tmp_path, wait_phase="both")
    process = subprocess.Popen(
        [str(RUNNER)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        wait_for_handoff_marker(tmp_path, "lifecycle.started")
        wait_for_handoff_marker(tmp_path, "pytest.started")
        os.kill(process.pid, signal_number)
        process.wait(timeout=10)

        assert process.returncode == expected_returncode
        assert_handoff_process_groups_gone(tmp_path)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


@pytest.mark.parametrize("fail_at", [1])
def test_no_argument_run_propagates_a_gate_failure_and_stops(
    tmp_path: Path, fail_at: int
) -> None:
    env = validation_environment(tmp_path, fail_at=fail_at)

    result = run_validation(env, REPO_ROOT)

    assert result.returncode == 41
    commands = captured_commands(tmp_path)
    assert child_kinds(commands) == ["lint", "lifecycle", "tests"][:fail_at]
    assert_validation_caches_were_removed(commands)


# --- AC8: grammar and exit convention --------------------------------------


def test_help_exits_zero_and_names_every_operation(tmp_path: Path) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, "--help")

    assert result.returncode == 0, result.stderr
    output = f"{result.stdout}\n{result.stderr}"
    for operation in ("lint", "lifecycle", "tests", "stack"):
        assert operation in output
    assert captured_commands(tmp_path) == []


@pytest.mark.parametrize(
    "arguments",
    [
        ("bogus",),
        ("--bogus",),
        ("lint", "--bogus"),
        ("lifecycle", "--bogus"),
        ("tests", "--bogus"),
        ("stack", "--bogus"),
    ],
)
def test_unknown_operation_or_option_is_invalid_usage(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, *arguments)

    assert result.returncode == 2, result.stdout
    assert captured_commands(tmp_path) == []


# --- AC2 / AC3 / AC4: the targeted feedback operations ----------------------


def test_lint_runs_repo_wide_lint_alone(tmp_path: Path) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, "lint")

    assert result.returncode == 0, result.stderr
    commands = captured_commands(tmp_path)
    assert child_kinds(commands) == ["lint"]
    assert child_options(commands[0]["argv"], "ansible-lint") == []


def test_lint_rejects_a_path_argument(tmp_path: Path) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, "lint", "playbooks")

    assert result.returncode == 2, result.stdout
    assert captured_commands(tmp_path) == []


def test_lifecycle_runs_the_fast_path_by_default(tmp_path: Path) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, "lifecycle")

    assert result.returncode == 0, result.stderr
    commands = captured_commands(tmp_path)
    assert child_kinds(commands) == ["lifecycle"]
    assert child_options(commands[0]["argv"], "run_lxc_lifecycle_regressions.py") == []


@pytest.mark.parametrize(
    ("arguments", "forwarded"),
    [
        (("--full",), ["--full"]),
        (
            ("--only", "lxc_lifecycle_decision_launcher.py"),
            ["--only", "lxc_lifecycle_decision_launcher.py"],
        ),
        (
            (
                "--only",
                "lxc_lifecycle_decision_launcher.py",
                "--only",
                "lifecycle_run_lock_launcher.py",
            ),
            [
                "--only",
                "lxc_lifecycle_decision_launcher.py",
                "--only",
                "lifecycle_run_lock_launcher.py",
            ],
        ),
        (("--fail-fast",), ["--fail-fast"]),
        (("--full", "--fail-fast"), ["--full", "--fail-fast"]),
    ],
)
def test_lifecycle_forwards_every_supported_selection(
    tmp_path: Path, arguments: tuple[str, ...], forwarded: list[str]
) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, "lifecycle", *arguments)

    assert result.returncode == 0, result.stderr
    commands = captured_commands(tmp_path)
    assert child_kinds(commands) == ["lifecycle"]
    assert (
        child_options(commands[0]["argv"], "run_lxc_lifecycle_regressions.py")
        == forwarded
    )


def test_lifecycle_rejects_only_combined_with_full(tmp_path: Path) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(
        env,
        REPO_ROOT,
        "lifecycle",
        "--full",
        "--only",
        "lxc_lifecycle_decision_launcher.py",
    )

    assert result.returncode == 2, result.stdout
    assert captured_commands(tmp_path) == []


def test_tests_runs_the_whole_suite_without_a_target(tmp_path: Path) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, "tests")

    assert result.returncode == 0, result.stderr
    commands = captured_commands(tmp_path)
    assert child_kinds(commands) == ["tests"]
    assert child_options(commands[0]["argv"], "pytest") == []


@pytest.mark.parametrize(
    "target",
    [
        "tests/regression/test_validate_command.py",
        "tests/regression/test_validate_command.py"
        "::test_lint_runs_repo_wide_lint_alone",
    ],
)
def test_tests_forwards_an_in_tree_target(tmp_path: Path, target: str) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, "tests", target)

    assert result.returncode == 0, result.stderr
    commands = captured_commands(tmp_path)
    assert child_kinds(commands) == ["tests"]
    assert child_options(commands[0]["argv"], "pytest") == [target]


@pytest.mark.parametrize("target", ["validate.sh", "../outside/test_x.py"])
def test_tests_rejects_a_target_outside_the_test_tree(
    tmp_path: Path, target: str
) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, "tests", target)

    assert result.returncode == 2, result.stdout
    assert captured_commands(tmp_path) == []


@pytest.mark.parametrize(
    "paths",
    [(), ("stacks/workstation/mcp-auth-proxy", "stacks/workstation/another")],
)
def test_stack_requires_exactly_one_stack_path(
    tmp_path: Path, paths: tuple[str, ...]
) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, "stack", *paths)

    assert result.returncode == 2, result.stdout
    assert captured_commands(tmp_path) == []


def test_stack_validates_exactly_the_named_stack(tmp_path: Path) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(
        env, REPO_ROOT, "stack", "stacks/workstation/mcp-auth-proxy"
    )

    assert result.returncode == 0, result.stderr
    commands = captured_commands(tmp_path)
    assert child_kinds(commands) == ["stack"]
    argv = commands[0]["argv"]
    assert argv[argv.index("python") + 1] == "-B"
    options = child_options(argv, "validate")
    assert options[:2] == ["--repository-root", "."]
    assert options[-1] == "stacks/workstation/mcp-auth-proxy"


@pytest.mark.parametrize(
    "arguments",
    [
        ("lint", "--bogus:--help"),
        ("lifecycle", "--fail-fast:--help"),
        ("tests", "validate.sh:--help"),
        ("tests", "/etc/passwd:--help"),
    ],
)
def test_a_help_suffixed_argument_is_still_judged_by_its_own_branch(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, *arguments)

    assert result.returncode == 2, result.stdout
    assert captured_commands(tmp_path) == []


def test_a_help_suffixed_stack_path_stays_a_stack_path(tmp_path: Path) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, "stack", "stacks/a/b:--help")

    assert result.returncode == 0, result.stderr
    commands = captured_commands(tmp_path)
    assert child_kinds(commands) == ["stack"]
    assert commands[0]["argv"][-1] == "stacks/a/b:--help"


@pytest.mark.parametrize(
    "operation", ["lint", "lifecycle", "tests", "stack"]
)
def test_help_after_any_operation_exits_zero(
    tmp_path: Path, operation: str
) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, operation, "--help")

    assert result.returncode == 0, result.stderr
    assert "lifecycle" in f"{result.stdout}\n{result.stderr}"
    assert captured_commands(tmp_path) == []


@pytest.mark.parametrize("target", ["", "::test_foo"])
def test_an_unusable_test_target_reports_the_commands_own_usage_error(
    tmp_path: Path, target: str
) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, "tests", target)

    assert result.returncode == 2, result.stdout
    assert result.stderr.startswith("validate.sh: test target outside tests/")
    assert "realpath" not in result.stderr
    assert captured_commands(tmp_path) == []


# --- AC5: the stack update policy machine interface ------------------------


def run_real_validation(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(RUNNER), *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=120,
    )


def test_stack_reports_a_valid_policy_as_schema_versioned_json() -> None:
    result = run_real_validation("stack", "stacks/workstation/mcp-auth-proxy")

    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["schema_version"] == 1
    assert document["valid"] is True
    assert "stacks/workstation/mcp-auth-proxy" in result.stderr


# The frozen validation surface for issue #213 names stacks/overmind/overmind
# as the invalid-contract instance: its stack.yaml carries no `updates:`
# section today, so validation reports it as invalid. If that stack ever gains
# an update policy, move this case to another genuinely invalid stack rather
# than weakening the assertions.
@pytest.mark.parametrize(
    "path",
    [
        "stacks/overmind/overmind",
        "stacks/workstation/no-such-stack-for-validation",
    ],
)
def test_stack_reports_an_invalid_contract_on_stderr_and_exits_non_zero(
    path: str,
) -> None:
    result = run_real_validation("stack", path)

    assert result.returncode != 0
    document = json.loads(result.stdout)
    assert document["schema_version"] == 1
    assert document["valid"] is False
    assert document["errors"]
    diagnostic = document["errors"][0]["message"]
    assert diagnostic in result.stderr


# --- AC7 / AC10: the fixture environment and agent safety ------------------


OPERATION_ENTRY_POINTS = [
    (),
    ("lint",),
    ("lifecycle",),
    ("tests",),
    ("stack", "stacks/workstation/mcp-auth-proxy"),
]


@pytest.mark.parametrize("arguments", OPERATION_ENTRY_POINTS)
def test_every_operation_runs_under_the_fixture_environment(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    env = validation_environment(tmp_path)

    result = run_validation(env, REPO_ROOT, *arguments)

    assert result.returncode == 0, result.stderr
    assert_fixture_environment(
        captured_commands(tmp_path), expected_cache_count=3 if not arguments else 1
    )


@pytest.mark.parametrize("arguments", OPERATION_ENTRY_POINTS)
@pytest.mark.parametrize("sentinel_mode", [0o600, 0o000])
def test_every_operation_is_agent_safe(
    tmp_path: Path, arguments: tuple[str, ...], sentinel_mode: int
) -> None:
    if sentinel_mode == 0o000 and os.geteuid() == 0:
        pytest.skip(
            "root bypasses mode bits, so an unreadable sentinel cannot detect "
            "a silent read"
        )
    env = validation_environment(tmp_path, sentinel_mode=sentinel_mode)

    result = run_validation(env, REPO_ROOT, *arguments)

    # A readable sentinel catches a disclosing read through the marker
    # assertions; an unreadable one catches a silent read, which fails and
    # aborts the command before it can exit 0.
    assert result.returncode == 0, result.stderr
    assert OPERATOR_MARKER not in result.stdout
    assert OPERATOR_MARKER not in result.stderr
    for kind in child_kinds(captured_commands(tmp_path)):
        assert kind in {"lint", "lifecycle", "tests", "stack"}


# --- AC9: grammar coverage replaces the exact-argv pinning -----------------


def test_this_module_covers_the_grammar_instead_of_pinning_a_full_child_argv() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    retired_pinning = "VALIDATION_" + "COMMANDS"

    assert retired_pinning not in source
    for grammar_test in (
        "test_no_argument_run_is_the_comprehensive_non_live_handoff_validation",
        "test_no_argument_run_propagates_a_gate_failure_and_stops",
        "test_help_exits_zero_and_names_every_operation",
        "test_unknown_operation_or_option_is_invalid_usage",
        "test_lifecycle_forwards_every_supported_selection",
        "test_lifecycle_rejects_only_combined_with_full",
        "test_tests_rejects_a_target_outside_the_test_tree",
        "test_stack_requires_exactly_one_stack_path",
        "test_every_operation_runs_under_the_fixture_environment",
        "test_every_operation_is_agent_safe",
    ):
        assert grammar_test in globals()
