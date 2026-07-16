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

    def __init__(self, *args, **kwargs):
        self.params = self.params_queue.pop(0)
        self.check_mode = False

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

        def fake_run_pct_command(module, cmd_args):
            captured["cmd_args"] = cmd_args
            return run_result

        FakeAnsibleModule.params_queue = [params]
        self.module.AnsibleModule = FakeAnsibleModule
        self.module.run_pct_command = fake_run_pct_command

        with self.assertRaises((ModuleExit, ModuleFail)) as context:
            self.module.main()

        return context.exception.payload, captured.get("cmd_args")

    def test_exec_command_uses_shell_wrapper(self) -> None:
        payload, cmd_args = self.run_main(
            {
                "vmid": 101,
                "command": "exec",
                "exec_command": ". /etc/os-release && printf '%s' \"$VERSION_ID\"",
                "config_options": None,
                "timeout": 30,
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
                "timeout": 30,
            },
            {"stdout": "", "stderr": "", "rc": 0, "cmd": "pct reboot 202"},
        )

        self.assertEqual(cmd_args, ["reboot", "202"])
        self.assertTrue(payload["changed"])

    def test_status_command_returns_structured_status(self) -> None:
        payload, cmd_args = self.run_main(
            {
                "vmid": 303,
                "command": "status",
                "exec_command": None,
                "config_options": None,
                "timeout": 30,
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
                "timeout": 30,
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

    def test_nonzero_rc_fails_with_result_payload(self) -> None:
        payload, cmd_args = self.run_main(
            {
                "vmid": 505,
                "command": "status",
                "exec_command": None,
                "config_options": None,
                "timeout": 30,
            },
            {"stdout": "", "stderr": "CT 505 does not exist", "rc": 2, "cmd": "pct status 505"},
        )

        self.assertEqual(cmd_args, ["status", "505"])
        self.assertEqual(payload["rc"], 2)
        self.assertIn("CT 505 does not exist", payload["msg"])


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
            "timeout": 30,
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

    def test_unbounded_command_preserves_existing_behaviour(self) -> None:
        result = self.module.run_pct_command(module=None, cmd_args=["quick"])

        self.assertEqual(result["rc"], 0)
        self.assertEqual(result["stdout"], "fixture-ok")

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

    def test_only_the_killable_path_detaches_into_its_own_session(self) -> None:
        # Detaching costs Ctrl-C propagation, so unbounded pct calls must stay in
        # the caller's process group; only the killpg path needs its own.
        # Swapping the module's own `subprocess` reference leaves the real
        # subprocess module untouched.
        spy = self.SubprocessSpy(self.module.subprocess)
        self.module.subprocess = spy

        self.module.run_pct_command(module=None, cmd_args=["quick"])
        self.module.run_pct_command(module=None, cmd_args=["quick"], kill_after=5)

        self.assertEqual(spy.sessions, [False, True])

    class SubprocessSpy:
        def __init__(self, real):
            self.real = real
            self.sessions: list[bool | None] = []
            self.PIPE = real.PIPE
            self.TimeoutExpired = real.TimeoutExpired

        def Popen(self, *args, **kwargs):  # noqa: N802 - mirrors subprocess.Popen
            self.sessions.append(kwargs.get("start_new_session"))
            return self.real.Popen(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()