#!/usr/bin/env python3
"""Unit tests for the proxmox_pct Ansible module."""

from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()