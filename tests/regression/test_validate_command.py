#!/usr/bin/env python3
"""Grammar and boundary coverage for the non-live validation command."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest


# This module covers signal cleanup, timed supervision, and checkout boundaries.
pytestmark = pytest.mark.serial

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "validate.sh"
FIXTURE_INVENTORY = str(REPO_ROOT / "tests/fixtures/ansible/inventory.yml")
FIXTURE_VAULT_PASSWORD_FILE = str(REPO_ROOT / "tests/fixtures/ansible/vault-pass")
OPERATOR_MARKER = "operator-secret-marker-4f2b"


def validation_environment(
    tmp_path: Path, *, fail_lint: bool = False, sentinel_mode: int = 0o600
) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

capture = Path(os.environ["VALIDATE_TEST_CAPTURE"])
with capture.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({
        "argv": sys.argv[1:],
        "cache_connection": os.environ.get("ANSIBLE_CACHE_PLUGIN_CONNECTION"),
        "inventory": os.environ.get("ANSIBLE_INVENTORY"),
        "lifecycle_marker": os.environ.get("HOMELAB_IAC_LIFECYCLE_WRAPPER"),
        "vault_password_file": os.environ.get("ANSIBLE_VAULT_PASSWORD_FILE"),
    }) + "\\n")

phase = ""
if any(item.endswith("run_lxc_lifecycle_regressions.py") for item in sys.argv):
    phase = "lifecycle"
elif "pytest" in sys.argv:
    phase = "pytest"
pytest_lane = "serial"
if phase == "pytest" and "-m" in sys.argv:
    marker_index = sys.argv.index("-m")
    if (
        marker_index + 1 < len(sys.argv)
        and sys.argv[marker_index + 1] == "not serial"
    ):
        pytest_lane = "parallel"
if state_dir := os.environ.get("VALIDATE_TEST_HANDOFF_STATE"):
    if phase:
        state = Path(state_dir)
        (state / f"{phase}.started").write_text(str(os.getpgid(0)))
        while not (state / "release").exists():
            time.sleep(0.01)
        status_name = (
            f"VALIDATE_TEST_{pytest_lane.upper()}_STATUS"
            if phase == "pytest"
            else f"VALIDATE_TEST_{phase.upper()}_STATUS"
        )
        status = int(
            os.environ.get(
                status_name, os.environ[f"VALIDATE_TEST_{phase.upper()}_STATUS"]
            )
        )
        if status == 0 or (
            phase == "pytest"
            and os.environ["VALIDATE_TEST_LIFECYCLE_STATUS"] != "0"
        ):
            time.sleep(0.2)
        print(f"fake-{phase}-output", flush=True)
        raise SystemExit(status)
if os.environ["VALIDATE_TEST_FAIL_LINT"] == "1" and "ansible-lint" in sys.argv:
    raise SystemExit(41)
if phase == "pytest":
    status_name = f"VALIDATE_TEST_{pytest_lane.upper()}_STATUS"
    raise SystemExit(
        int(os.environ.get(status_name, os.environ["VALIDATE_TEST_PYTEST_STATUS"]))
    )
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    env = os.environ.copy()
    env.pop("HOMELAB_IAC_LIFECYCLE_WRAPPER", None)
    env.pop("VALIDATE_TESTS_SERIAL", None)
    env.pop("VALIDATE_JUNIT_REPORT_DIR", None)
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
            "VALIDATE_TEST_FAIL_LINT": "1" if fail_lint else "0",
            "VALIDATE_TEST_PYTEST_STATUS": "0",
            "VALIDATE_TEST_SERIAL_STATUS": "0",
            "VALIDATE_TEST_PARALLEL_STATUS": "0",
        }
    )
    return env


def handoff_environment(
    tmp_path: Path,
    *,
    lifecycle_status: int = 0,
    pytest_status: int = 0,
) -> dict[str, str]:
    state_dir = tmp_path / "handoff-state"
    state_dir.mkdir()
    env = validation_environment(tmp_path)
    env.update(
        {
            "VALIDATE_TEST_HANDOFF_STATE": str(state_dir),
            "VALIDATE_TEST_LIFECYCLE_STATUS": str(lifecycle_status),
            "VALIDATE_TEST_PYTEST_STATUS": str(pytest_status),
            "VALIDATE_TEST_SERIAL_STATUS": str(pytest_status),
            "VALIDATE_TEST_PARALLEL_STATUS": str(pytest_status),
        }
    )
    return env


def wait_for_parallel_phases(tmp_path: Path) -> list[int]:
    markers = [
        tmp_path / f"handoff-state/{phase}.started"
        for phase in ("lifecycle", "pytest")
    ]
    deadline = time.monotonic() + 5
    while not all(marker.exists() for marker in markers):
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for lifecycle and pytest")
        time.sleep(0.01)
    return [int(marker.read_text()) for marker in markers]


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
    return [json.loads(line) for line in capture.read_text().splitlines()]


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
    assert kinds.count("tests") == 2
    lifecycle_command = next(
        command for command in commands if child_kind(command["argv"]) == "lifecycle"
    )
    assert child_options(lifecycle_command["argv"], "run_lxc_lifecycle_regressions.py") == [
        "--full"
    ]
    assert_fixture_environment(commands, expected_cache_count=3)
    assert not (Path(env["HOME"]) / ".ansible/homelab-iac-lifecycle.lock").exists()


@pytest.mark.parametrize(
    ("lifecycle_status", "pytest_status"),
    [(0, 0), (41, 0), (0, 43), (41, 43)],
)
def test_handoff_overlaps_and_reports_both_natural_results(
    tmp_path: Path,
    lifecycle_status: int,
    pytest_status: int,
) -> None:
    env = handoff_environment(
        tmp_path,
        lifecycle_status=lifecycle_status,
        pytest_status=pytest_status,
    )
    process = subprocess.Popen(
        [str(RUNNER)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for_parallel_phases(tmp_path)
        (tmp_path / "handoff-state/release").touch()
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)

    assert process.returncode == (lifecycle_status or pytest_status)
    for phase, status in (("lifecycle", lifecycle_status), ("pytest", pytest_status)):
        stream = stdout if status == 0 else stderr
        result = "passed" if status == 0 else f"failed (exit {status})"
        assert f"validate.sh: {phase} {result}" in stream
        assert f"fake-{phase}-output" in stream


@pytest.mark.parametrize(
    ("signal_number", "expected_returncode"),
    [(signal.SIGINT, 130), (signal.SIGTERM, 143)],
)
def test_handoff_signal_cleans_up_started_process_groups_before_returning(
    tmp_path: Path, signal_number: int, expected_returncode: int
) -> None:
    env = handoff_environment(tmp_path)
    process = subprocess.Popen(
        [str(RUNNER)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        process_groups = wait_for_parallel_phases(tmp_path)
        os.kill(process.pid, signal_number)
        process.wait(timeout=10)

        assert process.returncode == expected_returncode
        for pgid in process_groups:
            with pytest.raises(ProcessLookupError):
                os.killpg(pgid, 0)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_no_argument_run_stops_when_lint_fails(tmp_path: Path) -> None:
    env = validation_environment(tmp_path, fail_lint=True)

    result = run_validation(env, REPO_ROOT)

    assert result.returncode == 41
    commands = captured_commands(tmp_path)
    assert child_kinds(commands) == ["lint"]
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
    assert child_kinds(commands) == ["tests", "tests"]
    assert child_options(commands[0]["argv"], "pytest") == [
        "-n",
        "0",
        "-m",
        "serial",
    ]
    assert child_options(commands[1]["argv"], "pytest") == [
        "-n",
        "2",
        "--dist=worksteal",
        "--max-worker-restart=0",
        "-m",
        "not serial",
    ]


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
    assert child_kinds(commands) == ["tests", "tests"]
    assert child_options(commands[0]["argv"], "pytest") == [
        "-n",
        "0",
        "-m",
        "serial",
        target,
    ]
    assert child_options(commands[1]["argv"], "pytest") == [
        "-n",
        "2",
        "--dist=worksteal",
        "--max-worker-restart=0",
        "-m",
        "not serial",
        target,
    ]


@pytest.mark.parametrize(
    ("lane", "status", "expected_calls"),
    [("serial", 41, 1), ("parallel", 43, 2)],
)
def test_tests_preserves_lane_failure_status_and_stops_after_serial_failure(
    tmp_path: Path, lane: str, status: int, expected_calls: int
) -> None:
    env = validation_environment(tmp_path)
    env[f"VALIDATE_TEST_{lane.upper()}_STATUS"] = str(status)

    result = run_validation(env, REPO_ROOT, "tests")

    commands = captured_commands(tmp_path)
    assert result.returncode == status
    assert child_kinds(commands) == ["tests"] * expected_calls
    if lane == "serial":
        assert child_options(commands[0]["argv"], "pytest")[-2:] == ["-m", "serial"]
    else:
        assert child_options(commands[1]["argv"], "pytest")[-2:] == [
            "-m",
            "not serial",
        ]


@pytest.mark.parametrize(
    ("serial_status", "parallel_status", "expected_status"),
    [(5, 0, 0), (0, 5, 0), (5, 5, 5)],
)
def test_tests_accepts_one_empty_lane_but_preserves_an_empty_suite(
    tmp_path: Path,
    serial_status: int,
    parallel_status: int,
    expected_status: int,
) -> None:
    env = validation_environment(tmp_path)
    env["VALIDATE_TEST_SERIAL_STATUS"] = str(serial_status)
    env["VALIDATE_TEST_PARALLEL_STATUS"] = str(parallel_status)

    result = run_validation(env, REPO_ROOT, "tests")

    assert result.returncode == expected_status
    assert child_kinds(captured_commands(tmp_path)) == ["tests", "tests"]


def test_serial_and_parallel_markers_partition_the_complete_collected_suite(
    tmp_path: Path,
) -> None:
    env = validation_environment(tmp_path)
    env["ANSIBLE_INVENTORY"] = FIXTURE_INVENTORY
    env["ANSIBLE_VAULT_PASSWORD_FILE"] = FIXTURE_VAULT_PASSWORD_FILE
    real_uv = shutil.which("uv")
    assert real_uv is not None

    def collect(*arguments: str) -> list[str]:
        result = subprocess.run(
            [real_uv, "run", "--locked", "pytest", "--collect-only", "-q", *arguments],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        return [
            line
            for line in result.stdout.splitlines()
            if line.startswith("tests/") and "::" in line
        ]

    all_items = collect()
    serial_items = collect("-m", "serial")
    parallel_items = collect("-m", "not serial")
    all_ids = set(all_items)
    serial_ids = set(serial_items)
    parallel_ids = set(parallel_items)

    assert all_items
    assert len(all_items) == len(all_ids)
    assert len(serial_items) == len(serial_ids)
    assert len(parallel_items) == len(parallel_ids)
    assert serial_ids.isdisjoint(parallel_ids)
    assert serial_ids | parallel_ids == all_ids
    serial_modules = (
        "tests/regression/test_lifecycle_prerequisite_layers.py::",
        "tests/regression/test_validate_command.py::",
        "tests/regression/test_vault_command.py::",
        "tests/regression/test_image_update_renovate_adapter_real.py::",
        "tests/regression/test_overmind_postgres_backup.py::",
        "tests/regression/test_portal_traefik_redis_recreation.py::",
        "tests/unit/test_lxc_lifecycle_regression_runner.py::",
        "tests/unit/test_proxmox_pct.py::",
        "tests/unit/test_stack_update_policy_snapshot.py::",
    )
    for module in serial_modules:
        assert any(item.startswith(module) for item in serial_ids), module
        assert not any(item.startswith(module) for item in parallel_ids), module
    for module in (
        "tests/regression/test_materialize_templates.py::",
        "tests/regression/test_workstation_persistent_home.py::",
    ):
        module_items = [item for item in all_ids if item.startswith(module)]
        assert len(module_items) == 1
        assert module_items[0] in parallel_ids


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
