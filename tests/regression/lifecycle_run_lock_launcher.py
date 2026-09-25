#!/usr/bin/env python3
"""Regression for the machine-local lifecycle wrapper lock and marker guard."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import fcntl
from io import StringIO
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ansible.cli.playbook import PlaybookCLI

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "run.sh"
LOCK_RELATIVE_PATH = Path(".ansible/homelab-iac-lifecycle.lock")
METADATA_LOCK_RELATIVE_PATH = Path(".ansible/homelab-iac-lifecycle.lock.metadata")
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)
FIXTURE_COLLECTIONS = (
    REPO_ROOT
    / "tests/regression/fixtures/lxc_lifecycle_facade_assets/collections"
)


def make_fake_uv(bin_dir: Path) -> None:
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env python3
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

arguments = sys.argv[1:]
if "ansible-playbook" not in arguments:
    raise SystemExit(0)

capture = Path(os.environ["LIFECYCLE_TEST_CAPTURE"])
capture.write_text(json.dumps({
    "argv": arguments,
    "marker": os.environ.get("HOMELAB_IAC_LIFECYCLE_WRAPPER"),
    "pid": os.getpid(),
}), encoding="utf-8")

def raise_signal_exit():
    raise SystemExit(130)

mode = os.environ.get("LIFECYCLE_TEST_MODE", "success")
if mode == "sleep":
    signal.signal(signal.SIGINT, lambda *_: raise_signal_exit())
    while True:
        time.sleep(1)
if mode == "delay":
    time.sleep(float(os.environ["LIFECYCLE_TEST_DELAY_SECONDS"]))
if mode in ("cleanup_contention_success", "cleanup_contention_fail"):
    metadata_path = Path(os.environ["HOME"]) / ".ansible/homelab-iac-lifecycle.lock.metadata"
    metadata_file = metadata_path.open("a+", encoding="utf-8")
    fcntl.flock(metadata_file, fcntl.LOCK_EX)
    holder = subprocess.Popen(
        ["sleep", "1.4"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        pass_fds=(metadata_file.fileno(),),
    )
    metadata_file.seek(0)
    metadata_file.truncate()
    metadata_file.write(f"pid={holder.pid} worktree=/controlled/cleanup-holder\\n")
    metadata_file.flush()
    metadata_file.close()
    if mode == "cleanup_contention_fail":
        raise SystemExit(42)
if mode == "fail":
    raise SystemExit(42)
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)


def wrapper_environment(temp_root: Path, *, mode: str = "success") -> dict[str, str]:
    home = temp_root / "home"
    bin_dir = temp_root / "bin"
    home.mkdir()
    bin_dir.mkdir()
    make_fake_uv(bin_dir)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "LIFECYCLE_TEST_CAPTURE": str(temp_root / "capture.json"),
            "LIFECYCLE_TEST_MODE": mode,
        }
    )
    return env


def run_wrapper(env: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(RUNNER), *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def process_has_open_path(pid: int, expected_path: Path) -> bool:
    try:
        return any(
            descriptor.resolve() == expected_path
            for descriptor in Path(f"/proc/{pid}/fd").iterdir()
        )
    except (FileNotFoundError, PermissionError):
        return False


def accepted_protected_long_options() -> tuple[tuple[str, bool], ...]:
    protected_options = (
        ("--limit", True),
        ("--inventory", True),
        ("--inventory-file", True),
        ("--tags", True),
        ("--skip-tags", True),
        ("--check", False),
        ("--start-at-task", True),
        ("--syntax-check", False),
        ("--list-hosts", False),
        ("--list-tags", False),
        ("--list-tasks", False),
        ("--step", False),
        ("--help", False),
        ("--version", False),
    )
    candidates = {
        (option[:length], requires_value)
        for option, requires_value in protected_options
        for length in range(3, len(option) + 1)
    }
    cli = PlaybookCLI(["ansible-playbook"])
    cli.init_parser()
    accepted: list[tuple[str, bool]] = []
    for candidate, requires_value in sorted(candidates):
        arguments = [candidate]
        if requires_value:
            arguments.append("fixture-value")
        arguments.append("site.yml")
        try:
            with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
                cli.parser.parse_args(arguments)
        except SystemExit as error:
            if error.code == 0:
                accepted.append((candidate, requires_value))
            continue
        accepted.append((candidate, requires_value))
    return tuple(accepted)


def accepted_safe_long_value_options() -> tuple[str, ...]:
    safe_options = (
        "--private-key",
        "--key-file",
        "--user",
        "--connection",
        "--timeout",
        "--ssh-common-args",
        "--sftp-extra-args",
        "--scp-extra-args",
        "--ssh-extra-args",
        "--connection-password-file",
        "--conn-pass-file",
        "--become-method",
        "--become-user",
        "--become-password-file",
        "--become-pass-file",
        "--vault-id",
        "--vault-password-file",
        "--vault-pass-file",
        "--forks",
        "--module-path",
        "--extra-vars",
    )
    candidates = {
        option[:length]
        for option in safe_options
        for length in range(3, len(option) + 1)
    }
    cli = PlaybookCLI(["ansible-playbook"])
    cli.init_parser()
    accepted: list[str] = []
    for candidate in sorted(candidates):
        try:
            with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
                parsed = cli.parser.parse_args(
                    [candidate, "2", "site.yml"]
                )
        except SystemExit:
            continue
        if parsed.args == ["site.yml"]:
            accepted.append(candidate)
    return tuple(accepted)


def assert_prerequisite_plays_survive_lifecycle_limits() -> None:
    for wrapper_arguments, expected_host in (
        (("--limit", "collie"), "collie"),
        (("--include-controller",), "workstation"),
    ):
        with tempfile.TemporaryDirectory(prefix="lifecycle-prerequisite-limit-") as temp_dir:
            temp_root = Path(temp_dir)
            env = wrapper_environment(temp_root)
            wrapper_result = run_wrapper(env, *wrapper_arguments)
            capture = json.loads(
                (temp_root / "capture.json").read_text(encoding="utf-8")
            )
            inventory = temp_root / "inventory.yml"
            inventory.write_text(
                """---
all:
  children:
    lxcs:
      hosts:
        collie:
        workstation:
""",
                encoding="utf-8",
            )
            list_result = subprocess.run(
                [
                    *ANSIBLE_PLAYBOOK,
                    *capture["argv"][3:],
                    "--list-hosts",
                    "-i",
                    str(inventory),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "ANSIBLE_COLLECTIONS_PATH": str(FIXTURE_COLLECTIONS),
                },
                timeout=30,
            )
            output = f"{list_result.stdout}\n{list_result.stderr}"
            for play_name in (
                "Verify control node prerequisites",
                "Verify Proxmox host SSH access",
            ):
                play_start = output.rfind(play_name)
                play_end = output.find("\n  play #", play_start + 1)
                play_output = output[play_start : play_end if play_end >= 0 else None]
                if (
                    wrapper_result.returncode != 0
                    or list_result.returncode != 0
                    or play_start < 0
                    or "hosts (1):" not in play_output
                    or expected_host not in play_output
                ):
                    raise AssertionError(
                        f"{play_name!r} lost {expected_host!r} under {wrapper_arguments!r}:\n"
                        f"{output}"
                    )


def assert_command_grammar_reports_help_and_usage_errors() -> None:
    with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-grammar-") as temp_dir:
        env = wrapper_environment(Path(temp_dir))
        help_result = run_wrapper(env, "--help")
        help_output = f"{help_result.stdout}\n{help_result.stderr}"
        if (
            help_result.returncode != 0
            or "full" not in help_output
            or "provision" not in help_output
            or "configure" not in help_output
        ):
            raise AssertionError(f"help did not describe lifecycle operations:\n{help_output}")

        sensitive_placeholder = "PLACEHOLDER_SENSITIVE_VALUE_206"
        for arguments in (
            (f"unknown-{sensitive_placeholder}",),
            (f"--unknown={sensitive_placeholder}",),
        ):
            result = run_wrapper(env, *arguments)
            output = f"{result.stdout}\n{result.stderr}"
            if result.returncode != 2 or sensitive_placeholder in output:
                raise AssertionError(
                    "invalid input did not return 2 with non-disclosing diagnostics:\n"
                    f"returncode={result.returncode}\n{output}"
                )

        for arguments in (
            ("-e", "proxmox_skip_self=false"),
            ("--extra-vars", "proxmox_skip_self=false"),
            ("--tags", "provision"),
        ):
            result = run_wrapper(env, *arguments)
            if result.returncode != 2 or (Path(temp_dir) / "capture.json").exists():
                raise AssertionError(
                    f"low-level option before -- was not rejected: {arguments!r}\n"
                    f"returncode={result.returncode}\n{result.stdout}\n{result.stderr}"
                )

    with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-empty-limit-") as temp_dir:
        temp_root = Path(temp_dir)
        env = wrapper_environment(temp_root)
        result = run_wrapper(env, "--limit", "")
        if result.returncode != 2 or (temp_root / "capture.json").exists():
            raise AssertionError(
                "empty --limit did not fail closed without launching Ansible:\n"
                f"returncode={result.returncode}\n{result.stdout}\n{result.stderr}"
            )

    with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-empty-stack-") as temp_dir:
        temp_root = Path(temp_dir)
        env = wrapper_environment(temp_root)
        result = run_wrapper(env, "--stack", "")
        if result.returncode != 2 or (temp_root / "capture.json").exists():
            raise AssertionError(
                "empty --stack did not fail closed without launching Ansible:\n"
                f"returncode={result.returncode}\n{result.stdout}\n{result.stderr}"
            )


def assert_wrapper_routes_and_propagates() -> None:
    def canonical_defaults(intent: str, target: str = "localhost") -> tuple[str, ...]:
        return (
            "-e",
            f"prerequisite_target_pattern={target}",
            "-e",
            f"proxmox_lifecycle_intent={intent}",
            "-e",
            "proxmox_skip_self=true",
            '--extra-vars={"stack_filter":null}',
        )

    full_defaults = canonical_defaults("full")
    provision_defaults = canonical_defaults("provision_only")
    configure_defaults = canonical_defaults("configure_only")
    cap_docker_defaults = canonical_defaults("full", "cap_docker")
    mixed_limit_defaults = canonical_defaults("full", "collie,portal,!workstation")
    collie_provision_defaults = canonical_defaults("provision_only", "collie")
    collie_configure_defaults = canonical_defaults("configure_only", "collie")
    cases = (
        ((), "site.yml", full_defaults),
        (("full",), "site.yml", full_defaults),
        (("--limit", "cap_docker"), "site.yml", ("--limit", "cap_docker", *cap_docker_defaults)),
        (("--limit", "collie,portal,!workstation"), "site.yml", ("--limit", "collie,portal,!workstation", *mixed_limit_defaults)),
        (("--check",), "site.yml", ("--check", *full_defaults)),
        (
            ("--stack", "beets"),
            "site.yml",
            (
                "-e",
                "prerequisite_target_pattern=localhost",
                "-e",
                "proxmox_lifecycle_intent=full",
                "-e",
                "proxmox_skip_self=true",
                "-e",
                "stack_filter=beets",
            ),
        ),
        (
            ("--include-controller",),
            "site.yml",
            (
                "--limit",
                "workstation",
                "-e",
                "prerequisite_target_pattern=workstation",
                "-e",
                "proxmox_lifecycle_intent=full",
                "-e",
                "proxmox_skip_self=false",
                '--extra-vars={"stack_filter":null}',
            ),
        ),
        (
            ("--include-controller", "--limit", "portal"),
            "site.yml",
            (
                "--limit",
                "workstation",
                "-e",
                "prerequisite_target_pattern=workstation",
                "-e",
                "proxmox_lifecycle_intent=full",
                "-e",
                "proxmox_skip_self=false",
                '--extra-vars={"stack_filter":null}',
            ),
        ),
        (("-v",), "site.yml", ("-v", *full_defaults)),
        (("-vv",), "site.yml", ("-vv", *full_defaults)),
        (("-vvv",), "site.yml", ("-vvv", *full_defaults)),
        (("--", "-Dv"), "site.yml", ("-Dv", *full_defaults)),
        (("--", "--diff", "-e", "harmless=true"), "site.yml", ("--diff", "-e", "harmless=true", *full_defaults)),
        (("--", "--extra-vars=harmless=true"), "site.yml", ("--extra-vars=harmless=true", *full_defaults)),
        (("--", "-eharmless=true"), "site.yml", ("-eharmless=true", *full_defaults)),
        (("--", "-eharmless=Ci/l/t"), "site.yml", ("-eharmless=Ci/l/t", *full_defaults)),
        (("--", "-e", '{"harmless": true}'), "site.yml", ("-e", '{"harmless": true}', *full_defaults)),
        (("--", "--extra-vars", "{harmless: true}"), "site.yml", ("--extra-vars", "{harmless: true}", *full_defaults)),
        (("--", "-e", "@vaulted-vars.yml"), "site.yml", ("-e", "@vaulted-vars.yml", *full_defaults)),
        (("--", "-e", "proxmox_lifecycle_intent=configure_only"), "site.yml", ("-e", "proxmox_lifecycle_intent=configure_only", *full_defaults)),
        (("--", "-e", "prerequisite_target_pattern=workstation"), "site.yml", ("-e", "prerequisite_target_pattern=workstation", *full_defaults)),
        (("--", '--extra-vars={"stack_filter":"beets","proxmox_skip_self":false}'), "site.yml", ('--extra-vars={"stack_filter":"beets","proxmox_skip_self":false}', *full_defaults)),
        (("--", "--private-key", "/tmp/fixture-key"), "site.yml", ("--private-key", "/tmp/fixture-key", *full_defaults)),
        (("--", "--private-key=/tmp/fixture-key"), "site.yml", ("--private-key=/tmp/fixture-key", *full_defaults)),
        (("--", "--connection", "local"), "site.yml", ("--connection", "local", *full_defaults)),
        (("--", "--connection=local"), "site.yml", ("--connection=local", *full_defaults)),
        (("--", "--forks", "2"), "site.yml", ("--forks", "2", *full_defaults)),
        (("--", "--forks=2"), "site.yml", ("--forks=2", *full_defaults)),
        (("provision", "--limit", "collie"), "playbooks/provision-lxcs.yml", ("--limit", "collie", *collie_provision_defaults)),
        (("configure", "--limit", "collie"), "playbooks/configure-lxcs.yml", ("--limit", "collie", *collie_configure_defaults)),
        (("configure", "--", "--diff", "-e", "harmless=true"), "playbooks/configure-lxcs.yml", ("--diff", "-e", "harmless=true", *configure_defaults)),
    )
    for arguments, playbook, passthrough in cases:
        with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-routing-") as temp_dir:
            temp_root = Path(temp_dir)
            env = wrapper_environment(temp_root)
            proc = run_wrapper(env, *arguments)
            if not (temp_root / "capture.json").exists():
                raise AssertionError(
                    f"wrapper did not launch for {arguments!r}: returncode={proc.returncode}\n"
                    f"{proc.stdout}\n{proc.stderr}"
                )
            capture = json.loads((temp_root / "capture.json").read_text(encoding="utf-8"))
            expected = ["run", "--locked", "ansible-playbook", playbook, *passthrough]
            if (
                proc.returncode != 0
                or capture["argv"] != expected
                or capture["marker"] != "1"
                or not isinstance(capture["pid"], int)
            ):
                raise AssertionError(
                    f"wrapper routing mismatch for {arguments!r}: capture={capture!r}\n"
                    f"{proc.stdout}\n{proc.stderr}"
                )

    for option in accepted_safe_long_value_options():
        with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-safe-prefix-") as temp_dir:
            temp_root = Path(temp_dir)
            env = wrapper_environment(temp_root)
            proc = run_wrapper(env, "--", option, "fixture-value")
            capture_path = temp_root / "capture.json"
            if proc.returncode != 0 or not capture_path.exists():
                raise AssertionError(
                    f"accepted safe option {option!r} did not consume its operand:\n"
                    f"{proc.stdout}\n{proc.stderr}"
                )
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            expected = [
                "run",
                "--locked",
                "ansible-playbook",
                "site.yml",
                option,
                "fixture-value",
                *full_defaults,
            ]
            if capture["argv"] != expected:
                raise AssertionError(
                    f"accepted safe option {option!r} was not forwarded byte-for-byte: "
                    f"{capture['argv']!r}"
                )

    with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-nondisclosure-") as temp_dir:
        temp_root = Path(temp_dir)
        env = wrapper_environment(temp_root)
        sensitive_placeholder = "PLACEHOLDER_SENSITIVE_VALUE_206"
        extra_var = f"harmless={sensitive_placeholder}"
        proc = run_wrapper(env, "--", "-e", extra_var)
        capture = json.loads((temp_root / "capture.json").read_text(encoding="utf-8"))
        output = f"{proc.stdout}\n{proc.stderr}"
        if (
            proc.returncode != 0
            or extra_var not in capture["argv"]
            or sensitive_placeholder in output
        ):
            raise AssertionError(
                "passthrough was not forwarded exactly and kept out of terminal prose:\n"
                f"capture={capture!r}\n{output}"
            )

    protected_passthrough = (
        ("--", "--limit", "portal"),
        ("--", "--check"),
        ("--", "--tags", "provision"),
        ("--", "-t", "configure"),
        ("--", "--tag=configure"),
        ("--", "--ta", "validation"),
        ("--", "--help"),
        ("--", "--version"),
        ("--", "-h"),
        ("--", "-Dh"),
        ("--", "--sk", "validation"),
        ("--", "--skip-t", "validation"),
        ("--", "--inventory", "inventory/other.yml"),
        ("--", "--inventory-file=inventory/other.yml"),
        ("--", "--inventory-f", "inventory/other.yml"),
        ("--", "-i", "inventory/other.yml"),
        ("--", "--lim=portal"),
        ("--", "--ch"),
        ("--", "--start-at-task", "Apply lifecycle actions"),
        ("--", "--sta", "Apply lifecycle actions"),
        ("--", "--start-a=Apply lifecycle actions"),
        ("provision", "--", "--tags", "configure"),
        ("--check", "--", "--limit", "portal"),
        ("--", "-CD"),
        ("--", "-Dlportal"),
        ("--", "-Dtconfigure"),
        ("--", "-Di/tmp/other.yml"),
        ("--", f"-Dl{sensitive_placeholder}"),
        ("--", f"-Dt{sensitive_placeholder}"),
        ("--", f"-Di/tmp/{sensitive_placeholder}"),
        ("--", "-DC"),
        ("--", f"-vl{sensitive_placeholder}"),
        ("--", f"-vt{sensitive_placeholder}"),
        ("--", f"-vi/tmp/{sensitive_placeholder}"),
        ("--", f"other-{sensitive_placeholder}.yml"),
        ("provision", "--", "other-playbook.yml"),
        ("configure", "--", "other-playbook.yml"),
        ("--check", "--", "other-playbook.yml"),
    )
    protected_passthrough += tuple(
        (
            "--",
            option,
            *((sensitive_placeholder,) if requires_value else ()),
        )
        for option, requires_value in accepted_protected_long_options()
    )
    for arguments in protected_passthrough:
        with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-protection-") as temp_dir:
            temp_root = Path(temp_dir)
            env = wrapper_environment(temp_root)
            proc = run_wrapper(env, *arguments)
            output = f"{proc.stdout}\n{proc.stderr}"
            if (
                proc.returncode != 2
                or (temp_root / "capture.json").exists()
                or sensitive_placeholder in output
            ):
                raise AssertionError(
                    f"protected passthrough {arguments!r} was not rejected:\n"
                    f"{output}"
                )

    for arguments in (("--limit",), ("--stack",), ("--limit", "--check")):
        with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-missing-value-") as temp_dir:
            temp_root = Path(temp_dir)
            env = wrapper_environment(temp_root)
            proc = run_wrapper(env, *arguments)
            if proc.returncode != 2 or (temp_root / "capture.json").exists():
                raise AssertionError(
                    f"missing option value {arguments!r} was not rejected:\n"
                    f"{proc.stdout}\n{proc.stderr}"
                )

    with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-failure-") as temp_dir:
        temp_root = Path(temp_dir)
        env = wrapper_environment(temp_root, mode="fail")
        first = run_wrapper(env)
        env["LIFECYCLE_TEST_MODE"] = "success"
        second = run_wrapper(env)
        if first.returncode != 1 or second.returncode != 0:
            raise AssertionError(
                "wrapper did not normalize failure or release the lock afterward:\n"
                f"first={first.returncode}\n{first.stdout}\n{first.stderr}\n"
                f"second={second.returncode}\n{second.stdout}\n{second.stderr}"
            )


def assert_contention_fails_fast() -> None:
    with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-contention-") as temp_dir:
        temp_root = Path(temp_dir)
        env = wrapper_environment(temp_root)
        lock_path = Path(env["HOME"]) / LOCK_RELATIVE_PATH
        lock_path.parent.mkdir(parents=True)
        with lock_path.open("w", encoding="utf-8") as lock_file:
            lock_file.write("pid=4242 worktree=/controlled/holder\n")
            lock_file.flush()
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            start = time.monotonic()
            proc = run_wrapper(env)
            elapsed = time.monotonic() - start
        output = f"{proc.stdout}\n{proc.stderr}"
        if (
            proc.returncode == 0
            or elapsed >= 2
            or "pid=4242" not in output
            or "/controlled/holder" not in output
            or (temp_root / "capture.json").exists()
        ):
            raise AssertionError(
                f"contending run did not fail fast with holder identity ({elapsed:.2f}s):\n{output}"
            )


def assert_lock_class_follows_operation_class() -> None:
    cases = (
        (fcntl.LOCK_SH, (), 75),
        (fcntl.LOCK_SH, ("provision",), 75),
        (fcntl.LOCK_SH, ("configure",), 75),
        (fcntl.LOCK_SH, ("--check",), 0),
        (fcntl.LOCK_EX, ("--check",), 75),
    )
    for held_class, arguments, expected_returncode in cases:
        with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-lock-class-") as temp_dir:
            temp_root = Path(temp_dir)
            env = wrapper_environment(temp_root)
            lock_path = Path(env["HOME"]) / LOCK_RELATIVE_PATH
            lock_path.parent.mkdir(parents=True)
            with lock_path.open("w", encoding="utf-8") as lock_file:
                lock_file.write("pid=4242 worktree=/controlled/holder\n")
                lock_file.flush()
                fcntl.flock(lock_file, held_class | fcntl.LOCK_NB)
                start = time.monotonic()
                proc = run_wrapper(env, *arguments)
                elapsed = time.monotonic() - start
            if proc.returncode != expected_returncode:
                raise AssertionError(
                    f"wrong lock behavior for {arguments!r} with held class {held_class}: "
                    f"returned {proc.returncode}, expected {expected_returncode}\n"
                    f"{proc.stdout}\n{proc.stderr}"
                )
            if expected_returncode == 75:
                output = f"{proc.stdout}\n{proc.stderr}"
                if elapsed >= 2 or "pid=4242" not in output or "/controlled/holder" not in output:
                    raise AssertionError(
                        f"contention for {arguments!r} did not fail fast with holder identity "
                        f"({elapsed:.2f}s):\n{output}"
                    )


def assert_contention_names_a_remaining_shared_holder() -> None:
    with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-shared-holders-") as temp_dir:
        temp_root = Path(temp_dir)
        base_env = wrapper_environment(temp_root)

        first_env = base_env.copy()
        first_capture = temp_root / "first-capture.json"
        first_env.update(
            {
                "LIFECYCLE_TEST_CAPTURE": str(first_capture),
                "LIFECYCLE_TEST_MODE": "sleep",
            }
        )
        first = subprocess.Popen(
            [str(RUNNER), "--check"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=first_env,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 10
            while not first_capture.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not first_capture.exists():
                raise AssertionError("first shared holder never launched")
            first_child_pid = json.loads(first_capture.read_text(encoding="utf-8"))["pid"]

            second_env = base_env.copy()
            second_capture = temp_root / "second-capture.json"
            second_env.update(
                {
                    "LIFECYCLE_TEST_CAPTURE": str(second_capture),
                    "LIFECYCLE_TEST_MODE": "delay",
                    "LIFECYCLE_TEST_DELAY_SECONDS": "0.3",
                }
            )
            second = subprocess.Popen(
                [str(RUNNER), "--check"],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=second_env,
            )
            second_stdout, second_stderr = second.communicate(timeout=10)
            if second.returncode != 0 or not second_capture.exists():
                raise AssertionError(
                    "later shared holder did not overlap and exit cleanly:\n"
                    f"{second_stdout}\n{second_stderr}"
                )
            if first.poll() is not None:
                raise AssertionError("earlier shared holder exited before contention")

            contender_env = base_env.copy()
            contender_capture = temp_root / "contender-capture.json"
            contender_env.update(
                {
                    "LIFECYCLE_TEST_CAPTURE": str(contender_capture),
                    "LIFECYCLE_TEST_MODE": "success",
                }
            )
            contender = run_wrapper(contender_env)
            output = f"{contender.stdout}\n{contender.stderr}"
            if (
                contender.returncode != 75
                or f"pid={first_child_pid}" not in output
                or f"worktree={REPO_ROOT}" not in output
                or contender_capture.exists()
            ):
                raise AssertionError(
                    "contention did not identify the remaining shared holder:\n"
                    f"{output}"
                )
        finally:
            if first.poll() is None:
                os.killpg(first.pid, signal.SIGINT)
            first.communicate(timeout=10)


def assert_contention_ignores_a_completed_holder_during_turnover() -> None:
    with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-holder-turnover-") as temp_dir:
        temp_root = Path(temp_dir)
        base_env = wrapper_environment(temp_root)

        completed_env = base_env.copy()
        completed_capture = temp_root / "completed-capture.json"
        completed_env.update(
            {
                "LIFECYCLE_TEST_CAPTURE": str(completed_capture),
                "LIFECYCLE_TEST_MODE": "delay",
                "LIFECYCLE_TEST_DELAY_SECONDS": "0.3",
            }
        )
        completed = subprocess.Popen(
            [str(RUNNER), "--check"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=completed_env,
        )
        deadline = time.monotonic() + 10
        while not completed_capture.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not completed_capture.exists():
            completed.kill()
            raise AssertionError("first turnover holder never launched")

        current_env = base_env.copy()
        current_capture = temp_root / "current-capture.json"
        current_env.update(
            {
                "LIFECYCLE_TEST_CAPTURE": str(current_capture),
                "LIFECYCLE_TEST_MODE": "sleep",
            }
        )
        current = subprocess.Popen(
            [str(RUNNER), "--check"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=current_env,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 10
            while not current_capture.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not current_capture.exists():
                raise AssertionError("successor shared holder never launched")
            current_child_pid = json.loads(
                current_capture.read_text(encoding="utf-8")
            )["pid"]
            completed_stdout, completed_stderr = completed.communicate(timeout=10)
            if completed.returncode != 0:
                raise AssertionError(
                    "first turnover holder did not complete cleanly:\n"
                    f"{completed_stdout}\n{completed_stderr}"
                )
            if current.poll() is not None:
                raise AssertionError("successor holder exited before turnover contention")

            contender_env = base_env.copy()
            contender_capture = temp_root / "turnover-contender-capture.json"
            contender_env.update(
                {
                    "LIFECYCLE_TEST_CAPTURE": str(contender_capture),
                    "LIFECYCLE_TEST_MODE": "success",
                }
            )
            contender = run_wrapper(contender_env)
            output = f"{contender.stdout}\n{contender.stderr}"
            if (
                contender.returncode != 75
                or f"pid={current_child_pid}" not in output
                or f"worktree={REPO_ROOT}" not in output
                or contender_capture.exists()
            ):
                raise AssertionError(
                    "turnover contention reported stale rather than current metadata:\n"
                    f"{output}"
                )
        finally:
            if completed.poll() is None:
                completed.kill()
                completed.communicate(timeout=10)
            if current.poll() is None:
                os.killpg(current.pid, signal.SIGINT)
            current.communicate(timeout=10)


def assert_metadata_transitions_serialize_compatible_callers() -> None:
    with tempfile.TemporaryDirectory(prefix="lifecycle-metadata-serialization-") as temp_dir:
        temp_root = Path(temp_dir)
        env = wrapper_environment(temp_root, mode="delay")
        env["LIFECYCLE_TEST_DELAY_SECONDS"] = "0.2"
        metadata_path = Path(env["HOME"]) / METADATA_LOCK_RELATIVE_PATH
        metadata_path.parent.mkdir(parents=True)
        with metadata_path.open("w", encoding="utf-8") as metadata_file:
            fcntl.flock(metadata_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            caller = subprocess.Popen(
                [str(RUNNER), "--check"],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            deadline = time.monotonic() + 2
            while (
                caller.poll() is None
                and not process_has_open_path(caller.pid, metadata_path)
                and time.monotonic() < deadline
            ):
                time.sleep(0.005)
            if caller.poll() is not None or not process_has_open_path(
                caller.pid, metadata_path
            ):
                raise AssertionError("compatible caller rejected metadata serialization")
            time.sleep(0.04)
            if (temp_root / "capture.json").exists():
                caller.kill()
                raise AssertionError(
                    "compatible caller bypassed the metadata transition boundary"
                )
            fcntl.flock(metadata_file, fcntl.LOCK_UN)
        stdout, stderr = caller.communicate(timeout=10)
        if caller.returncode != 0 or not (temp_root / "capture.json").exists():
            raise AssertionError(
                "compatible caller did not continue after metadata serialization:\n"
                f"{stdout}\n{stderr}"
            )


def assert_metadata_coordination_has_a_bounded_failure() -> None:
    with tempfile.TemporaryDirectory(prefix="lifecycle-metadata-timeout-") as temp_dir:
        temp_root = Path(temp_dir)
        env = wrapper_environment(temp_root)
        metadata_path = Path(env["HOME"]) / METADATA_LOCK_RELATIVE_PATH
        metadata_path.parent.mkdir(parents=True)
        with metadata_path.open("w", encoding="utf-8") as metadata_file:
            metadata_file.write(
                f"pid={os.getpid()} worktree=/controlled/metadata-holder\n"
            )
            metadata_file.flush()
            fcntl.flock(metadata_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            start = time.monotonic()
            caller = subprocess.Popen(
                [str(RUNNER)],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,
            )
            try:
                stdout, stderr = caller.communicate(timeout=1)
            except subprocess.TimeoutExpired as error:
                os.killpg(caller.pid, signal.SIGKILL)
                caller.communicate(timeout=10)
                raise AssertionError("metadata acquisition waited beyond its bound") from error
            elapsed = time.monotonic() - start
        output = f"{stdout}\n{stderr}"
        if (
            caller.returncode != 75
            or elapsed < 0.05
            or elapsed >= 0.5
            or f"pid={os.getpid()}" not in output
            or "worktree=/controlled/metadata-holder" not in output
            or (temp_root / "capture.json").exists()
        ):
            raise AssertionError(
                f"bounded metadata failure lacked active holder identity ({elapsed:.2f}s):\n"
                f"{output}"
            )


def assert_cleanup_metadata_contention_preserves_playbook_status() -> None:
    for mode, expected_status in (
        ("cleanup_contention_success", 0),
        ("cleanup_contention_fail", 1),
    ):
        with tempfile.TemporaryDirectory(prefix="lifecycle-cleanup-contention-") as temp_dir:
            temp_root = Path(temp_dir)
            env = wrapper_environment(temp_root, mode=mode)
            result = run_wrapper(env)
            output = f"{result.stdout}\n{result.stderr}"
            holder_records = list(
                (Path(env["HOME"]) / f"{LOCK_RELATIVE_PATH}.holders").glob("*.holder")
            )
            lock_path = Path(env["HOME"]) / LOCK_RELATIVE_PATH
            with lock_path.open("a", encoding="utf-8") as lock_file:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise AssertionError(
                        f"cleanup contention left the lifecycle lock held for {mode}"
                    ) from error
            if (
                result.returncode != expected_status
                or not (temp_root / "capture.json").exists()
                or holder_records
                or "coordinates" in output
            ):
                raise AssertionError(
                    f"cleanup contention changed the normalized playbook result for {mode}:\n"
                    f"returncode={result.returncode}\n{output}"
                )


def assert_holder_metadata_covers_lock_lifetime() -> None:
    with tempfile.TemporaryDirectory(prefix="lifecycle-holder-lifetime-") as temp_dir:
        temp_root = Path(temp_dir)
        env = wrapper_environment(temp_root, mode="delay")
        env["LIFECYCLE_TEST_DELAY_SECONDS"] = "0.6"
        lock_path = Path(env["HOME"]) / LOCK_RELATIVE_PATH
        holder = subprocess.Popen(
            [str(RUNNER), "--check"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        capture_path = temp_root / "capture.json"
        deadline = time.monotonic() + 10
        while not capture_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        holder_records = list(Path(f"{lock_path}.holders").glob("*.holder"))
        if not capture_path.exists() or len(holder_records) != 1:
            holder.kill()
            raise AssertionError("held live lock lacked invocation metadata")
        with lock_path.open("a", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                holder.kill()
                raise AssertionError("shared holder metadata existed without its live lock")
        stdout, stderr = holder.communicate(timeout=10)
        if holder.returncode != 0:
            raise AssertionError(
                "holder cleanup changed the playbook result:\n"
                f"{stdout}\n{stderr}"
            )
        if list(Path(f"{lock_path}.holders").glob("*.holder")):
            raise AssertionError("holder metadata outlived its released lock")


def assert_interrupt_releases_lock() -> None:
    with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-interrupt-") as temp_dir:
        temp_root = Path(temp_dir)
        env = wrapper_environment(temp_root, mode="sleep")
        proc = subprocess.Popen(
            [str(RUNNER)],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        capture_path = temp_root / "capture.json"
        deadline = time.monotonic() + 10
        while not capture_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not capture_path.exists():
            proc.kill()
            raise AssertionError("wrapper never launched the controlled playbook process")
        os.killpg(proc.pid, signal.SIGINT)
        stdout, stderr = proc.communicate(timeout=10)

        lock_path = Path(env["HOME"]) / LOCK_RELATIVE_PATH
        with lock_path.open("a", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise AssertionError(
                    f"lock remained held after interrupt:\n{stdout}\n{stderr}"
                ) from error
        env["LIFECYCLE_TEST_MODE"] = "success"
        subsequent = run_wrapper(env)
        if subsequent.returncode != 0:
            raise AssertionError(
                "subsequent lifecycle run failed after the interrupted holder exited:\n"
                f"{subsequent.stdout}\n{subsequent.stderr}"
            )


def assert_wrapper_crash_keeps_child_lock() -> None:
    with tempfile.TemporaryDirectory(prefix="lifecycle-wrapper-crash-") as temp_dir:
        temp_root = Path(temp_dir)
        env = wrapper_environment(temp_root, mode="sleep")
        proc = subprocess.Popen(
            [str(RUNNER)],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        capture_path = temp_root / "capture.json"
        deadline = time.monotonic() + 10
        while not capture_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not capture_path.exists():
            proc.kill()
            raise AssertionError("wrapper never launched the controlled playbook process")
        child_pid = json.loads(capture_path.read_text(encoding="utf-8"))["pid"]
        proc.kill()
        proc.wait(timeout=10)

        lock_path = Path(env["HOME"]) / LOCK_RELATIVE_PATH
        with lock_path.open("a", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                os.kill(child_pid, signal.SIGKILL)
                raise AssertionError(
                    "lock was released while the lifecycle child was still running"
                )

        os.kill(child_pid, signal.SIGKILL)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with lock_path.open("a", encoding="utf-8") as lock_file:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    time.sleep(0.05)
                else:
                    break
        else:
            raise AssertionError("lock remained held after the lifecycle child exited")


def assert_direct_lifecycle_run_is_rejected() -> None:
    with tempfile.TemporaryDirectory(prefix="lifecycle-marker-guard-") as temp_dir:
        temp_root = Path(temp_dir)
        inventory = temp_root / "inventory.ini"
        vault = temp_root / "vault-pass"
        inventory.write_text("[local]\nlocalhost ansible_connection=local\n", encoding="utf-8")
        vault.write_text("unused-fixture-placeholder\n", encoding="utf-8")
        env = os.environ.copy()
        env.pop("HOMELAB_IAC_LIFECYCLE_WRAPPER", None)
        env["ANSIBLE_INVENTORY"] = str(inventory)
        env["ANSIBLE_VAULT_PASSWORD_FILE"] = str(vault)
        env["ANSIBLE_COLLECTIONS_PATH"] = str(FIXTURE_COLLECTIONS)
        proc = subprocess.run(
            [*ANSIBLE_PLAYBOOK, "site.yml"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        output = f"{proc.stdout}\n{proc.stderr}"
        if (
            proc.returncode == 0
            or "./run.sh" not in output
            or "Check for uv-managed control node virtual environment" in output
            or "TASK [infrastructure/proxmox_host_bootstrap" in output
        ):
            raise AssertionError(f"direct lifecycle run was not rejected first:\n{output}")


def main() -> int:
    try:
        assert_prerequisite_plays_survive_lifecycle_limits()
        assert_command_grammar_reports_help_and_usage_errors()
        assert_wrapper_routes_and_propagates()
        assert_contention_fails_fast()
        assert_lock_class_follows_operation_class()
        assert_contention_names_a_remaining_shared_holder()
        assert_contention_ignores_a_completed_holder_during_turnover()
        assert_metadata_transitions_serialize_compatible_callers()
        assert_cleanup_metadata_contention_preserves_playbook_status()
        assert_metadata_coordination_has_a_bounded_failure()
        assert_holder_metadata_covers_lock_lifetime()
        assert_interrupt_releases_lock()
        assert_wrapper_crash_keeps_child_lock()
        assert_direct_lifecycle_run_is_rejected()
    except (AssertionError, subprocess.TimeoutExpired) as error:
        print(error, file=sys.stderr)
        return 1
    print("ok: lifecycle wrapper serializes machine-local lifecycle mutation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
