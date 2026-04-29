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


def flatten_tasks(tasks: list[dict[str, object]]) -> list[dict[str, object]]:
    flat_tasks: list[dict[str, object]] = []
    for task in tasks:
        flat_tasks.append(task)
        for child_key in ("block", "always", "rescue"):
            child_tasks = task.get(child_key, [])
            if isinstance(child_tasks, list):
                flat_tasks.extend(flatten_tasks(child_tasks))
    return flat_tasks


class WorkstationBaselineRoleTests(unittest.TestCase):
    def test_role_defaults_contract(self) -> None:
        defaults = load_yaml(REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml")

        self.assertEqual(defaults["workstation_username"], "{{ docker_user }}")
        self.assertEqual(defaults["workstation_uid"], "{{ docker_uid }}")
        self.assertEqual(defaults["workstation_gid"], "{{ docker_gid }}")
        self.assertEqual(defaults["workstation_home"], "/home/{{ workstation_username }}")
        self.assertFalse(defaults["workstation_persistent_home_enabled"])
        self.assertEqual(defaults["workstation_persistent_home_root"], "/ephemeral/workstation/home")
        self.assertEqual(
            defaults["workstation_persistent_home_links"],
            [
                {
                    "name": "claude",
                    "path": "{{ workstation_home }}/.claude",
                    "target": "{{ workstation_persistent_home_root }}/.claude",
                    "mode": "0700",
                },
                {
                    "name": "codex",
                    "path": "{{ workstation_home }}/.codex",
                    "target": "{{ workstation_persistent_home_root }}/.codex",
                    "mode": "0700",
                },
                {
                    "name": "repos",
                    "path": "{{ workstation_home }}/repos",
                    "target": "{{ workstation_persistent_home_root }}/repos",
                    "mode": "0755",
                },
            ],
        )
        self.assertNotIn("workstation_agent_state_enabled", defaults)
        self.assertNotIn("workstation_agent_state_root", defaults)
        self.assertNotIn("workstation_agent_state_links", defaults)
        self.assertNotIn("workstation_github_known_host_name", defaults)
        self.assertNotIn("workstation_github_ssh_private_key_path", defaults)
        self.assertNotIn("workstation_github_register_public_key", defaults)
        expected_apt_packages = {
            "tmux",
            "mosh",
            "wget",
            "git",
            "htop",
            "tree",
            "zip",
            "unzip",
            "build-essential",
            "pkg-config",
            "python3-venv",
            "python3-pip",
        }
        self.assertTrue(
            expected_apt_packages.issubset(set(defaults["workstation_packages"])),
            msg="workstation_packages is missing expected baseline OS tools",
        )
        self.assertTrue(
            {
                "gh",
                "jq",
                "ripgrep",
                "fd-find",
                "fzf",
                "nodejs",
                "npm",
                "pipx",
            }.isdisjoint(set(defaults["workstation_packages"])),
            msg="mise-owned tools must not be installed through apt",
        )
        self.assertFalse(defaults["workstation_bootstrap_unattended"])
        self.assertEqual(defaults["workstation_bootstrap_run_dir"], "/run/workstation-bootstrap")
        self.assertEqual(
            defaults["workstation_bootstrap_env_path"],
            "{{ workstation_bootstrap_run_dir }}/bootstrap.env",
        )
        self.assertEqual(
            defaults["workstation_bootstrap_marker_path"],
            "{{ workstation_home }}/.local/state/workstation-bootstrap/complete",
        )
        self.assertEqual(defaults["workstation_dotfiles_repo_url"], "https://github.com/faviann/dotfiles.git")
        self.assertEqual(defaults["workstation_github_cli_token_item"], "dotfiles/github-cli-token")
        self.assertIn("WORKSTATION_BW_CLIENTID", defaults["workstation_bootstrap_controller_env"].values())
        self.assertIn("WORKSTATION_BW_CLIENTSECRET", defaults["workstation_bootstrap_controller_env"].values())
        self.assertIn("WORKSTATION_BW_PASSWORD", defaults["workstation_bootstrap_controller_env"].values())
        self.assertEqual(
            defaults["workstation_bw_release_api_url"],
            "https://api.github.com/repos/bitwarden/clients/releases/tags/cli-v{{ workstation_bw_version }}",
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
        self.assertTrue(workstation_vars["workstation_persistent_home_enabled"])
        self.assertNotIn("workstation_agent_state_enabled", workstation_vars)

    def test_role_argument_specs_contract(self) -> None:
        specs = load_yaml(REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml")
        options = specs["argument_specs"]["main"]["options"]

        self.assertEqual(options["workstation_persistent_home_enabled"]["type"], "bool")
        self.assertFalse(options["workstation_persistent_home_enabled"]["required"])
        self.assertEqual(options["workstation_persistent_home_root"]["type"], "str")
        self.assertFalse(options["workstation_persistent_home_root"]["required"])
        self.assertEqual(options["workstation_persistent_home_links"]["type"], "list")
        self.assertEqual(options["workstation_persistent_home_links"]["elements"], "dict")
        self.assertFalse(options["workstation_persistent_home_links"]["required"])
        self.assertEqual(options["workstation_bootstrap_unattended"]["type"], "bool")
        self.assertFalse(options["workstation_bootstrap_unattended"]["required"])
        self.assertEqual(options["workstation_bootstrap_run_dir"]["type"], "str")
        self.assertEqual(options["workstation_bootstrap_env_path"]["type"], "str")
        self.assertEqual(options["workstation_bootstrap_marker_path"]["type"], "str")
        self.assertEqual(options["workstation_dotfiles_repo_url"]["type"], "str")
        self.assertEqual(options["workstation_github_cli_token_item"]["type"], "str")
        self.assertEqual(options["workstation_bootstrap_controller_env"]["type"], "dict")
        self.assertEqual(options["workstation_mise_tools"]["type"], "list")
        self.assertEqual(options["workstation_mise_tools"]["elements"], "str")
        self.assertEqual(options["workstation_bw_release_api_url"]["type"], "str")
        self.assertNotIn("workstation_agent_state_enabled", options)
        self.assertNotIn("workstation_agent_state_root", options)
        self.assertNotIn("workstation_agent_state_links", options)

    def test_role_tasks_contract(self) -> None:
        tasks = load_yaml(REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml")
        task_names = [t.get("name") for t in tasks]
        self.assertIn("Install workstation baseline packages", task_names)
        self.assertIn("Configure workstation persistent home links", task_names)
        self.assertIn("Configure GitHub SSH keys", task_names)
        self.assertIn("Install chezmoi", task_names, "missing chezmoi install task")
        self.assertIn("Install Bitwarden CLI", task_names, "missing bw CLI install task")
        self.assertIn("Install mise", task_names, "missing mise install task")
        self.assertIn("Install workstation bootstrap script", task_names, "missing bootstrap script task")
        self.assertIn("Run unattended workstation bootstrap", task_names, "missing unattended bootstrap task")

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
        self.assertIn("bitwarden_cli.yml", rendered_tasks)
        self.assertIn("mise.yml", rendered_tasks)
        self.assertIn("bootstrap.yml", rendered_tasks)
        self.assertIn("workstation_bootstrap_unattended | bool", rendered_tasks)
        self.assertNotIn("npm install -g @bitwarden/cli", rendered_tasks)
        bootstrap_tasks = load_yaml(
            REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/tasks/bootstrap.yml"
        )
        bootstrap_rendered = yaml.safe_dump(bootstrap_tasks, sort_keys=True)
        self.assertIn("workstation_bootstrap_controller_env.BW_CLIENTID", bootstrap_rendered)
        self.assertIn("workstation_bootstrap_env_path", bootstrap_rendered)
        for task in flatten_tasks(bootstrap_tasks):
            if task.get("name") in {
                "Validate controller bootstrap environment variables are present",
                "Ensure workstation bootstrap run directory exists",
                "Write workstation bootstrap envelope",
                "Run workstation bootstrap",
                "Ensure workstation bootstrap run directory is absent",
            }:
                self.assertTrue(task.get("no_log"), f"{task.get('name')} must use no_log")
        bootstrap_template = (
            REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/templates/workstation-bootstrap.sh.j2"
        ).read_text(encoding="utf-8")
        self.assertIn("parse_env_file", bootstrap_template)
        self.assertIn("trap cleanup EXIT", bootstrap_template)
        self.assertIn("gh auth status", bootstrap_template)
        self.assertIn("git@github.com", bootstrap_template)
        self.assertNotIn('source "$ENV_PATH"', bootstrap_template)
        persistent_home_tasks = load_yaml(
            REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/tasks/persistent_home.yml"
        )
        persistent_home_task_names = [t.get("name") for t in persistent_home_tasks]
        self.assertIn("Validate workstation persistent home links", persistent_home_task_names)
        self.assertIn("Ensure workstation persistent home targets exist", persistent_home_task_names)
        self.assertIn("Inspect workstation persistent home links", persistent_home_task_names)
        self.assertIn(
            "Fail when workstation persistent home path is not the managed symlink",
            persistent_home_task_names,
        )
        self.assertIn("Link workstation persistent home paths", persistent_home_task_names)
        for removed_fragment in ("workstation_github_", "gh auth status", "user/keys"):
            self.assertNotIn(removed_fragment, rendered_tasks)

        rendered_persistent_home_tasks = yaml.safe_dump(persistent_home_tasks, sort_keys=True)
        expected_fragments = (
            "workstation_persistent_home_enabled",
            "workstation_persistent_home_root",
            "workstation_persistent_home_links",
            "islnk",
            "lnk_source",
            "state: link",
            "mode: '{{ item.mode",
        )
        for expected_fragment in expected_fragments:
            self.assertIn(expected_fragment, rendered_persistent_home_tasks)

    def test_workstation_bootstrap_deploy_wrapper_contract(self) -> None:
        wrapper = REPO_ROOT / "scripts/workstation-bootstrap-deploy.sh"
        text = wrapper.read_text(encoding="utf-8")

        self.assertIn("read -rsp 'Bitwarden master password: ' BW_PASSWORD", text)
        self.assertIn("dotfiles/workstation-bitwarden-api-key", text)
        self.assertIn("client_id", text)
        self.assertIn("client_secret", text)
        self.assertIn("workstation_bootstrap_unattended=true", text)
        self.assertIn("trap cleanup EXIT", text)
        self.assertNotIn("controller.env", text)


if __name__ == "__main__":
    unittest.main()
