#!/usr/bin/env python3
"""Contract tests for the workstation baseline role."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class WorkstationBaselineRoleTests(unittest.TestCase):
    def test_role_defaults_contract(self) -> None:
        defaults = load_yaml(REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml")

        self.assertEqual(defaults["workstation_username"], "{{ docker_user }}")
        self.assertEqual(defaults["workstation_uid"], "{{ docker_uid }}")
        self.assertEqual(defaults["workstation_gid"], "{{ docker_gid }}")
        self.assertNotIn("workstation_github_known_host_name", defaults)
        self.assertNotIn("workstation_github_ssh_private_key_path", defaults)
        self.assertNotIn("workstation_github_register_public_key", defaults)
        self.assertTrue(
            {
                "tmux",
                "mosh",
                "gh",
                "jq",
                "ripgrep",
                "fd-find",
                "fzf",
                "tree",
                "zip",
                "unzip",
                "build-essential",
                "pkg-config",
                "python3-venv",
                "python3-pip",
                "pipx",
                "nodejs",
                "npm",
            }.issubset(set(defaults["workstation_packages"])),
            msg="workstation_packages is missing expected baseline tools",
        )

    def test_lifecycle_wires_workstation_baseline_role_once(self) -> None:
        tasks = load_yaml(REPO_ROOT / "playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml")
        flat_tasks = []
        for task in tasks:
            flat_tasks.append(task)
            flat_tasks.extend(task.get("block", []))
        matching_tasks = [task for task in flat_tasks if task.get("name") == "Configure workstation baseline"]

        self.assertEqual(len(matching_tasks), 1)

        task = matching_tasks[0]
        include_role = next(
            (value for key, value in task.items() if key.endswith("include_role")),
            None,
        )
        self.assertIsNotNone(include_role)
        self.assertEqual(include_role["name"], "config/lxc_workstation_baseline")

        when_value = task.get("when")
        if isinstance(when_value, list):
            when_text = " ".join(str(item) for item in when_value)
        else:
            when_text = str(when_value)
        self.assertIn("workstation_enabled | default(false)", when_text)

    def test_role_tasks_contract(self) -> None:
        tasks = load_yaml(REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml")
        task_names = [t.get("name") for t in tasks]
        self.assertIn("Install workstation baseline packages", task_names)
        self.assertIn("Configure GitHub SSH keys", task_names)
        self.assertIn("Install chezmoi", task_names, "missing chezmoi install task")
        self.assertIn("Install bw CLI", task_names, "missing bw CLI install task")

        removed_task_names = {
            "Fetch GitHub SSH host key on controller",
            "Ensure github.com known_hosts entry exists",
            "Ensure workstation GitHub known_hosts permissions",
            "Generate workstation GitHub SSH keypair",
            "Ensure workstation GitHub SSH key ownership",
            "Read workstation GitHub SSH public key",
            "Set workstation GitHub SSH public key fact",
            "Verify GitHub CLI auth is available on controller",
            "List registered GitHub SSH public keys on controller",
            "Register workstation GitHub SSH public key on controller",
        }
        self.assertTrue(
            removed_task_names.isdisjoint(task_names),
            msg="workstation baseline still contains removed outbound GitHub SSH identity tasks",
        )

        rendered_tasks = yaml.safe_dump(tasks, sort_keys=True)
        for removed_fragment in ("workstation_github_", "gh auth status", "user/keys"):
            self.assertNotIn(removed_fragment, rendered_tasks)


if __name__ == "__main__":
    unittest.main()
