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
        self.assertEqual(defaults["workstation_home"], "/home/{{ workstation_username }}")
        self.assertFalse(defaults["workstation_agent_state_enabled"])
        self.assertEqual(defaults["workstation_agent_state_root"], "/ephemeral/workstation/agent-state")
        self.assertEqual(
            defaults["workstation_agent_state_links"],
            [
                {
                    "name": "claude",
                    "path": "{{ workstation_home }}/.claude",
                    "target": "{{ workstation_agent_state_root }}/claude",
                },
                {
                    "name": "codex",
                    "path": "{{ workstation_home }}/.codex",
                    "target": "{{ workstation_agent_state_root }}/codex",
                },
            ],
        )
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

    def test_workstation_inventory_opt_in_contract(self) -> None:
        workstation_vars = load_yaml(REPO_ROOT / "inventory/host_vars/workstation.yml")

        self.assertTrue(workstation_vars["workstation_enabled"])
        self.assertTrue(workstation_vars["workstation_agent_state_enabled"])

    def test_role_argument_specs_contract(self) -> None:
        specs = load_yaml(REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml")
        options = specs["argument_specs"]["main"]["options"]

        self.assertEqual(options["workstation_agent_state_enabled"]["type"], "bool")
        self.assertFalse(options["workstation_agent_state_enabled"]["required"])
        self.assertEqual(options["workstation_agent_state_root"]["type"], "str")
        self.assertFalse(options["workstation_agent_state_root"]["required"])
        self.assertEqual(options["workstation_agent_state_links"]["type"], "list")
        self.assertEqual(options["workstation_agent_state_links"]["elements"], "dict")
        self.assertFalse(options["workstation_agent_state_links"]["required"])

    def test_role_tasks_contract(self) -> None:
        tasks = load_yaml(REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml")
        task_names = [t.get("name") for t in tasks]
        self.assertIn("Install workstation baseline packages", task_names)
        self.assertIn("Configure workstation agent state", task_names)
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
        agent_state_tasks = load_yaml(
            REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/tasks/agent_state.yml"
        )
        agent_state_task_names = [t.get("name") for t in agent_state_tasks]
        self.assertIn("Validate workstation agent state paths", agent_state_task_names)
        self.assertIn("Ensure workstation agent state directories exist", agent_state_task_names)
        self.assertIn("Inspect workstation agent state home links", agent_state_task_names)
        self.assertIn(
            "Fail when workstation agent state home path is not the managed symlink",
            agent_state_task_names,
        )
        self.assertIn("Link workstation agent state into home directory", agent_state_task_names)
        for removed_fragment in ("workstation_github_", "gh auth status", "user/keys"):
            self.assertNotIn(removed_fragment, rendered_tasks)

        rendered_agent_state_tasks = yaml.safe_dump(agent_state_tasks, sort_keys=True)
        expected_fragments = (
            "workstation_agent_state_enabled",
            "workstation_agent_state_root",
            "workstation_agent_state_links",
            "islnk",
            "lnk_source",
            "state: link",
            "mode: '0700'",
        )
        for expected_fragment in expected_fragments:
            self.assertIn(expected_fragment, rendered_agent_state_tasks)


if __name__ == "__main__":
    unittest.main()
