#!/usr/bin/env python3
"""Unit tests for the proxmox_pct Ansible module."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "library" / "proxmox_pct.py"


class ModuleExit(Exception):
    """Capture exit_json payloads from a fake Ansible module."""

    def __init__(self, payload: dict):
        super().__init__(payload.get("msg", "module exited"))
        self.payload = payload


class ModuleFail(Exception):
    """Capture fail_json payloads from a fake Ansible module."""

    def __init__(self, payload: dict):
        super().__init__(payload.get("msg", "module failed"))
        self.payload = payload


class FakeAnsibleModule:
    """Minimal AnsibleModule stub for exercising main()."""

    params_queue: list[dict] = []
    # What main() declared, so tests can assert on the adapter's real surface
    # instead of restating it.
    last_kwargs: dict = {}

    def __init__(self, *args, **kwargs):
        self.params = self.params_queue.pop(0)
        self.check_mode = False
        FakeAnsibleModule.last_kwargs = kwargs

    @classmethod
    def last_argument_spec(cls) -> dict:
        return cls.last_kwargs.get("argument_spec", {})

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleFail(kwargs)


def load_module():
    spec = importlib.util.spec_from_file_location("proxmox_pct_under_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {MODULE_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProxmoxPctModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.original_ansible_module = self.module.AnsibleModule
        self.original_run_pct_command = self.module.run_pct_command
        self.addCleanup(self.restore_module)

    def restore_module(self) -> None:
        self.module.AnsibleModule = self.original_ansible_module
        self.module.run_pct_command = self.original_run_pct_command

    def run_main(self, params: dict, run_result: dict):
        captured = {}

        def fake_run_pct_command(module, cmd_args, kill_after):
            captured["cmd_args"] = cmd_args
            captured["kill_after"] = kill_after
            return run_result

        FakeAnsibleModule.params_queue = [params]
        self.module.AnsibleModule = FakeAnsibleModule
        self.module.run_pct_command = fake_run_pct_command

        with self.assertRaises((ModuleExit, ModuleFail)) as context:
            self.module.main()

        self.captured = captured
        return context.exception.payload, captured.get("cmd_args")

    def test_exec_command_uses_shell_wrapper(self) -> None:
        payload, cmd_args = self.run_main(
            {
                "vmid": 101,
                "command": "exec",
                "exec_command": ". /etc/os-release && printf '%s' \"$VERSION_ID\"",
                "config_options": None,
            },
            {"stdout": "12", "stderr": "", "rc": 0, "cmd": "pct exec 101"},
        )

        self.assertEqual(
            cmd_args,
            ["exec", "101", "--", "sh", "-c", ". /etc/os-release && printf '%s' \"$VERSION_ID\""],
        )
        self.assertEqual(payload["stdout"], "12")
        self.assertFalse(payload["changed"])

    def test_reboot_command_marks_changed(self) -> None:
        payload, cmd_args = self.run_main(
            {
                "vmid": 202,
                "command": "reboot",
                "exec_command": None,
                "config_options": None,
            },
            {"stdout": "", "stderr": "", "rc": 0, "cmd": "pct reboot 202"},
        )

        self.assertEqual(cmd_args, ["reboot", "202"])
        self.assertTrue(payload["changed"])

    def test_reboot_gets_a_wider_bound_than_a_read(self) -> None:
        # pct reboot stops the guest and starts it again, so it is the one
        # remaining command with a duration of its own to respect.
        self.run_main(
            {"vmid": 202, "command": "reboot", "exec_command": None, "config_options": None},
            {"stdout": "", "stderr": "", "rc": 0, "cmd": "pct reboot 202"},
        )
        reboot_bound = self.captured["kill_after"]

        self.run_main(
            {"vmid": 202, "command": "status", "exec_command": None, "config_options": None},
            {"stdout": "status: running", "stderr": "", "rc": 0, "cmd": "pct status 202"},
        )
        status_bound = self.captured["kill_after"]

        self.assertEqual(reboot_bound, self.module.PCT_REBOOT_TIMEOUT_SECONDS)
        self.assertEqual(status_bound, self.module.PCT_COMMAND_TIMEOUT_SECONDS)
        self.assertGreater(reboot_bound, status_bound)

    def test_the_adapter_offers_no_uncalled_command_and_no_timeout_option(self) -> None:
        self.run_main(
            {"vmid": 202, "command": "status", "exec_command": None, "config_options": None},
            {"stdout": "status: running", "stderr": "", "rc": 0, "cmd": "pct status 202"},
        )
        spec = FakeAnsibleModule.last_argument_spec()

        self.assertEqual(
            spec["command"]["choices"],
            ["status", "config", "set", "exec", "reboot", "wait_exec"],
        )
        self.assertNotIn("timeout", spec)

    def test_status_command_returns_structured_status(self) -> None:
        payload, cmd_args = self.run_main(
            {
                "vmid": 303,
                "command": "status",
                "exec_command": None,
                "config_options": None,
            },
            {"stdout": "status: running", "stderr": "", "rc": 0, "cmd": "pct status 303"},
        )

        self.assertEqual(cmd_args, ["status", "303"])
        self.assertEqual(payload["status"], "running")
        self.assertFalse(payload["changed"])

    def test_config_command_returns_parsed_config(self) -> None:
        payload, cmd_args = self.run_main(
            {
                "vmid": 404,
                "command": "config",
                "exec_command": None,
                "config_options": None,
            },
            {
                "stdout": "arch: amd64\nfeatures: nesting=1,keyctl=1",
                "stderr": "",
                "rc": 0,
                "cmd": "pct config 404",
            },
        )

        self.assertEqual(cmd_args, ["config", "404"])
        self.assertEqual(payload["config"], {"arch": "amd64", "features": "nesting=1,keyctl=1"})

    def test_recognized_missing_container_returns_structured_absent_status(self) -> None:
        payload, cmd_args = self.run_main(
            {
                "vmid": 505,
                "command": "status",
                "exec_command": None,
                "config_options": None,
            },
            {
                "stdout": "",
                "stderr": (
                    "Configuration file 'nodes/pve-a/lxc/505.conf' does not exist"
                ),
                "rc": 2,
                "cmd": "pct status 505",
            },
        )

        self.assertEqual(cmd_args, ["status", "505"])
        self.assertEqual(payload["rc"], 0)
        self.assertEqual(payload["status"], "absent")
        self.assertEqual(
            payload["stderr"],
            "Configuration file 'nodes/pve-a/lxc/505.conf' does not exist",
        )
        self.assertFalse(payload["changed"])

    def test_unrecognized_nonzero_status_fails_with_original_result_payload(self) -> None:
        payload, cmd_args = self.run_main(
            {
                "vmid": 505,
                "command": "status",
                "exec_command": None,
                "config_options": None,
            },
            {
                "stdout": "",
                "stderr": "permission denied while reading /etc/pve",
                "rc": 13,
                "cmd": "pct status 505",
            },
        )

        self.assertEqual(cmd_args, ["status", "505"])
        self.assertEqual(payload["rc"], 13)
        self.assertEqual(payload["cmd"], "pct status 505")
        self.assertEqual(payload["stderr"], "permission denied while reading /etc/pve")
        self.assertIn("LXC 505", payload["msg"])
        self.assertIn("permission denied while reading /etc/pve", payload["msg"])

    def test_missing_response_for_another_lxc_is_not_treated_as_absent(self) -> None:
        payload, _ = self.run_main(
            {
                "vmid": 505,
                "command": "status",
                "exec_command": None,
                "config_options": None,
            },
            {
                "stdout": "",
                "stderr": (
                    "Configuration file 'nodes/pve-a/lxc/999.conf' does not exist"
                ),
                "rc": 2,
                "cmd": "pct status 505",
            },
        )

        self.assertNotIn("status", payload)
        self.assertIn("nodes/pve-a/lxc/999.conf", payload["msg"])

    def test_missing_response_with_nested_node_path_is_not_treated_as_absent(self) -> None:
        payload, _ = self.run_main(
            {
                "vmid": 505,
                "command": "status",
                "exec_command": None,
                "config_options": None,
            },
            {
                "stdout": "",
                "stderr": (
                    "Configuration file 'nodes/pve/a/lxc/505.conf' does not exist"
                ),
                "rc": 2,
                "cmd": "pct status 505",
            },
        )

        self.assertNotIn("status", payload)
        self.assertIn("nodes/pve/a/lxc/505.conf", payload["msg"])

    def test_a_failure_names_the_lxc_and_the_command_that_failed(self) -> None:
        # A wedged pct is only actionable if the operator can tell which LXC and
        # which call produced it, matching the readiness message from #45.
        payload, _ = self.run_main(
            {
                "vmid": 606,
                "command": "status",
                "exec_command": None,
                "config_options": None,
            },
            {
                "stdout": "",
                "stderr": "pct command exceeded its 60s execution timeout and was killed",
                "rc": 124,
                "cmd": "pct status 606",
            },
        )

        message = payload["msg"]
        self.assertIn("LXC 606", message)
        self.assertIn("pct status 606", message)
        self.assertIn("rc=124", message)
        self.assertIn("execution timeout", message)


class GuestCommandReadinessTests(unittest.TestCase):
    """Bounded readiness polling over the pct execution seam."""

    def setUp(self) -> None:
        # Each load_module() call yields a fresh module object, so swapping its
        # `time` reference for a virtual clock never touches the real time module.
        self.module = load_module()
        self.calls: list[tuple[list, int | None]] = []
        self.sleeps: list[float] = []
        self.clock = 0.0
        self.module.time = self.VirtualClock(self)

    class VirtualClock:
        def __init__(self, test):
            self.test = test

        def monotonic(self):
            return self.test.clock

        def sleep(self, seconds):
            self.test.sleeps.append(seconds)
            self.test.clock += seconds

    def install_results(self, results: list[dict], attempt_cost: float = 0.0):
        """Serve queued pct results; the last one repeats for further attempts.

        attempt_cost models how long the guest command really takes. An attempt
        that outlives its budget is killed and reports TIMEOUT_RC instead of the
        container's answer, exactly as the live adapter does.
        """

        def fake_run_pct_command(module, cmd_args, kill_after=None):
            self.calls.append((cmd_args, kill_after))
            if kill_after is not None and attempt_cost > kill_after:
                self.clock += kill_after
                return {
                    "stdout": "",
                    "stderr": (
                        f"pct command exceeded its {kill_after}s execution timeout "
                        "and was killed"
                    ),
                    "rc": self.module.TIMEOUT_RC,
                    "cmd": "pct exec 4201",
                }
            self.clock += attempt_cost
            return results[min(len(self.calls) - 1, len(results) - 1)]

        self.module.run_pct_command = fake_run_pct_command

    def run_wait_exec(self, params: dict):
        merged = {
            "vmid": 4201,
            "command": "wait_exec",
            "exec_command": None,
            "config_options": None,
            "ready_timeout": 30,
            "ready_delay": 3,
            "ready_command_timeout": 10,
        }
        merged.update(params)
        FakeAnsibleModule.params_queue = [merged]
        self.module.AnsibleModule = FakeAnsibleModule

        with self.assertRaises((ModuleExit, ModuleFail)) as context:
            self.module.main()
        return context.exception

    @staticmethod
    def result(rc: int, stderr: str = "") -> dict:
        return {"stdout": "", "stderr": stderr, "rc": rc, "cmd": "pct exec 4201"}

    def test_immediate_success_probes_once_with_minimal_command(self) -> None:
        self.install_results([self.result(0)])

        exception = self.run_wait_exec({})

        self.assertIsInstance(exception, ModuleExit)
        self.assertEqual(len(self.calls), 1)
        cmd_args, timeout = self.calls[0]
        self.assertEqual(cmd_args, ["exec", "4201", "--", "sh", "-c", "true"])
        self.assertEqual(timeout, 10)
        self.assertEqual(self.sleeps, [])
        self.assertFalse(exception.payload["changed"])

    def test_delayed_success_retries_with_bounded_delay(self) -> None:
        self.install_results([self.result(2, "not running"), self.result(2), self.result(0)])

        exception = self.run_wait_exec({})

        self.assertIsInstance(exception, ModuleExit)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.sleeps, [3, 3])

    def test_every_attempt_carries_a_real_execution_timeout(self) -> None:
        self.install_results([self.result(124, "killed"), self.result(0)])

        self.run_wait_exec({"ready_command_timeout": 5})

        self.assertEqual([timeout for _, timeout in self.calls], [5, 5])

    def test_permanent_failure_fails_at_the_deadline_with_identity(self) -> None:
        self.install_results([self.result(255, "container is not ready")])

        exception = self.run_wait_exec({"ready_timeout": 10, "ready_delay": 3})

        self.assertIsInstance(exception, ModuleFail)
        # Attempts stop once another delay plus a usable attempt budget would
        # cross the 10s deadline; a 4th attempt at t=9 could not answer in time.
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.sleeps, [3, 3])
        self.assertLessEqual(self.clock, 10)
        message = exception.payload["msg"]
        self.assertIn("4201", message)
        self.assertIn("pct exec 4201 -- sh -c true", message)
        self.assertIn("10s readiness deadline", message)
        self.assertIn("container is not ready", message)

    def test_deadline_accounts_for_time_spent_inside_attempts(self) -> None:
        self.install_results([self.result(255)], attempt_cost=4.0)

        exception = self.run_wait_exec({"ready_timeout": 10, "ready_delay": 3})

        self.assertIsInstance(exception, ModuleFail)
        self.assertEqual(len(self.calls), 2)
        self.assertLessEqual(self.clock, 10)

    def test_deadline_exhaustion_reports_the_containers_real_error(self) -> None:
        # Attempts that really take time: the deadline must not be spent on a
        # final attempt too short to complete, whose kill would then mask the
        # container's actual error.
        self.install_results(
            [self.result(255, "container is not ready")], attempt_cost=2.0
        )

        exception = self.run_wait_exec(
            {"ready_timeout": 11, "ready_delay": 3, "ready_command_timeout": 10}
        )

        self.assertIsInstance(exception, ModuleFail)
        message = exception.payload["msg"]
        self.assertIn("container is not ready", message)
        self.assertNotIn("execution timeout", message)
        self.assertEqual(exception.payload["rc"], 255)
        # A third attempt could only have started with a 1s budget it cannot meet.
        self.assertEqual(len(self.calls), 2)

    def test_no_attempt_starts_without_a_usable_budget(self) -> None:
        self.install_results(
            [self.result(255, "container is not ready")], attempt_cost=2.0
        )

        self.run_wait_exec(
            {"ready_timeout": 11, "ready_delay": 3, "ready_command_timeout": 10}
        )

        for _, budget in self.calls:
            self.assertGreaterEqual(budget, self.module.MIN_USEFUL_ATTEMPT_SECONDS)

    def test_all_attempts_timing_out_is_reported_as_such(self) -> None:
        # No genuine error ever arrives: the message must say so rather than
        # pretend the container answered.
        self.install_results([self.result(255, "never seen")], attempt_cost=99.0)

        exception = self.run_wait_exec(
            {"ready_timeout": 30, "ready_delay": 3, "ready_command_timeout": 5}
        )

        self.assertIsInstance(exception, ModuleFail)
        self.assertEqual(exception.payload["rc"], self.module.TIMEOUT_RC)
        self.assertIn("execution timeout", exception.payload["msg"])
        self.assertNotIn("never seen", exception.payload["msg"])

    def test_all_timeouts_message_does_not_contradict_its_own_stderr(self) -> None:
        # The last attempt is clamped to the 4s left on the deadline, not the
        # configured 5s: the message must not claim a figure the stderr denies.
        self.install_results([self.result(255, "never seen")], attempt_cost=99.0)

        exception = self.run_wait_exec(
            {"ready_timeout": 10, "ready_delay": 1, "ready_command_timeout": 5}
        )

        message = exception.payload["msg"]
        self.assertEqual([budget for _, budget in self.calls], [5, 4.0])
        self.assertIn("exceeded its 4.0s execution timeout", message)
        self.assertNotIn("5s per-attempt", message)

    def test_a_tiny_deadline_still_makes_one_usable_attempt(self) -> None:
        self.install_results([self.result(0)], attempt_cost=0.5)

        exception = self.run_wait_exec({"ready_timeout": 1, "ready_delay": 3})

        self.assertIsInstance(exception, ModuleExit)
        self.assertEqual(len(self.calls), 1)
        self.assertGreaterEqual(
            self.calls[0][1], self.module.MIN_USEFUL_ATTEMPT_SECONDS
        )

    def test_readiness_bounds_are_required_rather_than_defaulted_here(self) -> None:
        # Single source of truth: the host-config role's defaults/argument_specs
        # pair owns 120/3/10. A module-side copy is unreachable (the role always
        # passes all three) and can only drift into stale documentation, so the
        # adapter requires them declaratively instead of restating the numbers.
        self.install_results([self.result(0)])
        self.run_wait_exec({})
        spec = FakeAnsibleModule.last_argument_spec()

        readiness_options = ["ready_timeout", "ready_delay", "ready_command_timeout"]
        for option in readiness_options:
            self.assertNotIn("default", spec[option], f"{option} restates a role default")
        self.assertIn(
            ("command", "wait_exec", readiness_options),
            FakeAnsibleModule.last_kwargs["required_if"],
        )

    def test_invalid_bounds_are_rejected(self) -> None:
        self.install_results([self.result(0)])

        exception = self.run_wait_exec({"ready_timeout": 0})

        self.assertIsInstance(exception, ModuleFail)
        self.assertIn("ready_timeout > 0", exception.payload["msg"])
        self.assertEqual(self.calls, [])


class RunPctCommandTimeoutTests(unittest.TestCase):
    """The live adapter must never block forever on a bounded invocation."""

    def setUp(self) -> None:
        self.module = load_module()
        # A controlled pct on PATH: `hang` blocks forever, anything else returns.
        temp_dir = tempfile.TemporaryDirectory(prefix="proxmox-pct-unit-")
        self.addCleanup(temp_dir.cleanup)
        fake_pct = Path(temp_dir.name) / "pct"
        # `hang` blocks; `orphan` leaves a child holding the pipes after the
        # parent is killed; anything else returns at once.
        fake_pct.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            "  hang) sleep 60 ;;\n"
            "  orphan) sleep 5 & wait ;;\n"
            "esac\n"
            "echo fixture-ok\n",
            encoding="utf-8",
        )
        fake_pct.chmod(0o755)

        original_path = os.environ["PATH"]
        os.environ["PATH"] = f"{temp_dir.name}{os.pathsep}{original_path}"
        self.addCleanup(os.environ.__setitem__, "PATH", original_path)

    def test_overrunning_command_is_killed_and_reported_as_failed(self) -> None:
        started = time.monotonic()
        result = self.module.run_pct_command(module=None, cmd_args=["hang"], kill_after=1)
        elapsed = time.monotonic() - started

        self.assertEqual(result["rc"], self.module.TIMEOUT_RC)
        self.assertIn("execution timeout", result["stderr"])
        self.assertLess(elapsed, 30)

    def test_command_that_answers_within_its_bound_returns_its_output(self) -> None:
        result = self.module.run_pct_command(module=None, cmd_args=["quick"], kill_after=10)

        self.assertEqual(result["rc"], 0)
        self.assertEqual(result["stdout"], "fixture-ok")

    def test_process_group_kill_leaves_no_child_holding_the_pipes(self) -> None:
        # `orphan` leaves a grandchild on the output pipes. Killing the whole
        # process group reaps it too, so the output is collected at once. If only
        # pct died, the grandchild would hold the pipes for its full 5s sleep and
        # the read would fall through to the "did not release its pipes" path.
        started = time.monotonic()
        result = self.module.run_pct_command(
            module=None, cmd_args=["orphan"], kill_after=1
        )
        elapsed = time.monotonic() - started

        self.assertEqual(result["rc"], self.module.TIMEOUT_RC)
        self.assertNotIn("did not release its pipes", result["stderr"])
        self.assertIn("execution timeout", result["stderr"])
        self.assertLess(elapsed, 4)

    def test_killpg_fallback_cannot_block_on_orphaned_pipes(self) -> None:
        # Force kill_process_group down its fallback, where only pct is killed and
        # a surviving child keeps the pipes open. Reading output must still be
        # bounded: this is the very hang the timeout exists to prevent.
        self.module.kill_process_group = lambda proc: proc.kill()
        self.module.KILL_GRACE_SECONDS = 1

        started = time.monotonic()
        result = self.module.run_pct_command(
            module=None, cmd_args=["orphan"], kill_after=1
        )
        elapsed = time.monotonic() - started

        self.assertEqual(result["rc"], self.module.TIMEOUT_RC)
        self.assertIn("did not release its pipes", result["stderr"])
        self.assertLess(elapsed, 4)

    def test_every_pct_call_detaches_into_its_own_session(self) -> None:
        # Every call is now bounded, so every call must be killable, so every call
        # detaches. The cost is deliberate: Ctrl-C no longer reaches pct. No
        # long-running interactive pct command remains, and the bound is what ends
        # a wedged call now. Swapping the module's own `subprocess` reference
        # leaves the real subprocess module untouched.
        spy = self.SubprocessSpy(self.module.subprocess)
        self.module.subprocess = spy

        self.module.run_pct_command(module=None, cmd_args=["quick"], kill_after=5)
        self.module.run_pct_command(module=None, cmd_args=["quick"], kill_after=600)

        self.assertEqual(spy.sessions, [True, True])

    class SubprocessSpy:
        def __init__(self, real):
            self.real = real
            self.sessions: list[bool | None] = []
            self.PIPE = real.PIPE
            self.TimeoutExpired = real.TimeoutExpired

        def Popen(self, *args, **kwargs):  # noqa: N802 - mirrors subprocess.Popen
            self.sessions.append(kwargs.get("start_new_session"))
            return self.real.Popen(*args, **kwargs)


class EveryOfferedCommandIsBoundedTests(unittest.TestCase):
    """No pct invocation the adapter offers may outlive its bound.

    Driven end-to-end through main() against a real pct that never returns, so
    the bound is demonstrated by a call that genuinely hangs rather than by
    inspection of the argument spec.
    """

    # Minimum params each command needs beyond vmid/command. Asserted below to
    # cover the adapter's full choices list, so a new command cannot be added
    # without deciding its bound here.
    EXTRA_PARAMS: dict[str, dict] = {
        "status": {},
        "config": {},
        "set": {"config_options": {"memory": 2048}},
        "exec": {"exec_command": "true"},
        "reboot": {},
        "wait_exec": {
            "ready_timeout": 2,
            "ready_delay": 0,
            "ready_command_timeout": 1,
        },
    }

    def setUp(self) -> None:
        self.module = load_module()
        temp_dir = tempfile.TemporaryDirectory(prefix="proxmox-pct-bound-")
        self.addCleanup(temp_dir.cleanup)
        # A pct that never answers, whatever it is asked. This is the wedged
        # pmxcfs the bound exists for.
        fake_pct = Path(temp_dir.name) / "pct"
        fake_pct.write_text("#!/bin/sh\nsleep 60\n", encoding="utf-8")
        fake_pct.chmod(0o755)

        original_path = os.environ["PATH"]
        os.environ["PATH"] = f"{temp_dir.name}{os.pathsep}{original_path}"
        self.addCleanup(os.environ.__setitem__, "PATH", original_path)

        self.module.AnsibleModule = FakeAnsibleModule
        # Shrink the production bounds so the mechanism is provable in seconds.
        # The values themselves are not under test here.
        self.module.PCT_COMMAND_TIMEOUT_SECONDS = 1
        self.module.PCT_REBOOT_TIMEOUT_SECONDS = 1

    def run_command(self, command: str):
        params = {
            "vmid": 4242,
            "command": command,
            "exec_command": None,
            "config_options": None,
            "ready_timeout": None,
            "ready_delay": None,
            "ready_command_timeout": None,
        }
        params.update(self.EXTRA_PARAMS[command])
        FakeAnsibleModule.params_queue = [params]

        started = time.monotonic()
        with self.assertRaises((ModuleExit, ModuleFail)) as context:
            self.module.main()
        return context.exception, time.monotonic() - started

    def test_a_pct_that_never_returns_is_killed_and_reported_for_every_command(self) -> None:
        for command in self.EXTRA_PARAMS:
            with self.subTest(command=command):
                exception, elapsed = self.run_command(command)

                self.assertIsInstance(exception, ModuleFail)
                # Without the bound this would sit on the fixture's 60s sleep.
                self.assertLess(elapsed, 30)
                message = exception.payload["msg"]
                self.assertIn("4242", message)
                self.assertIn("execution timeout", message)

        self.assertEqual(
            set(FakeAnsibleModule.last_argument_spec()["command"]["choices"]),
            set(self.EXTRA_PARAMS),
            "a command the adapter offers has no bound proven here",
        )


if __name__ == "__main__":
    unittest.main()
