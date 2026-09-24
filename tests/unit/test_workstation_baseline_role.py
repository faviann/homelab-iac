#!/usr/bin/env python3
"""Contract tests for the workstation baseline role."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_ROOT = REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline"


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


def task_named(tasks: list[dict[str, object]], name: str) -> dict[str, object]:
    return next(task for task in tasks if task.get("name") == name)


class WorkstationBaselineRoleTests(unittest.TestCase):
    def test_apt_leaves_home_manager_owned_tools_to_home_manager(self) -> None:
        defaults = load_yaml(ROLE_ROOT / "defaults/main.yml")

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
            msg="Home Manager-owned tools must not be installed through apt",
        )

    def test_persistent_home_root_lives_on_a_host_bind_mount(self) -> None:
        # Only a host bind mount survives an LXC rebuild, so the backing root
        # must sit under one or nothing it holds is actually durable.
        defaults = load_yaml(ROLE_ROOT / "defaults/main.yml")
        fleet = load_yaml(REPO_ROOT / "inventory/group_vars/all/proxmox.yml")
        workstation_vars = load_yaml(REPO_ROOT / "inventory/host_vars/workstation.yml")
        bind_mounts = {
            **fleet["proxmox_default_bind_mounts"],
            **workstation_vars.get("proxmox_lxc_bind_mounts_overrides", {}),
        }
        mount_targets = {
            option.removeprefix("mp=")
            for spec in bind_mounts.values()
            for option in spec.split(",")
            if option.startswith("mp=")
        }
        root = workstation_vars.get(
            "workstation_persistent_home_root", defaults["workstation_persistent_home_root"]
        )

        self.assertTrue(
            any(root.startswith(f"{target}/") for target in mount_targets),
            msg=f"{root} is not under any host bind mount target {sorted(mount_targets)}",
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

    def test_role_wires_every_workstation_capability(self) -> None:
        # The normal baseline regression disables packages, chezmoi, Nix and
        # lingering, so this is the only check that main.yml still wires them.
        # The other names here also have runtime owners.
        task_names = [t.get("name") for t in load_yaml(ROLE_ROOT / "tasks/main.yml")]

        for name in (
            "Install workstation baseline packages",
            "Configure workstation origin firewall",
            "Configure workstation persistent home mounts",
            "Configure GitHub SSH keys",
            "Install chezmoi",
            "Install Bitwarden CLI",
            "Install Determinate Nix",
            "Enable workstation user lingering",
        ):
            self.assertIn(name, task_names)

    def test_locale_entry_is_enabled_before_generation(self) -> None:
        # Debian's locale-gen generates only the uncommented entries of
        # /etc/locale.gen and can ignore a locale passed as an argument, so it
        # exits 0 having generated nothing. The entry must be enabled first,
        # and locale-gen itself ships in the `locales` package.
        defaults = load_yaml(ROLE_ROOT / "defaults/main.yml")
        tasks = load_yaml(ROLE_ROOT / "tasks/main.yml")
        task_names = [t.get("name") for t in tasks]

        self.assertIn("locales", defaults["workstation_packages"])
        locale_entry = task_named(tasks, "Enable the en_US.UTF-8 locale entry")
        self.assertEqual(locale_entry["ansible.builtin.lineinfile"]["path"], "/etc/locale.gen")
        self.assertEqual(locale_entry["ansible.builtin.lineinfile"]["line"], "en_US.UTF-8 UTF-8")
        locale_gen_cmd = task_named(tasks, "Generate enabled locales")["ansible.builtin.shell"]["cmd"]
        self.assertNotIn(
            "locale-gen en_US",
            locale_gen_cmd,
            msg="locale-gen must not rely on a locale argument; it is ignored on Debian images",
        )
        self.assertIn("locale-gen", locale_gen_cmd)
        self.assertLess(
            task_names.index("Enable the en_US.UTF-8 locale entry"),
            task_names.index("Generate enabled locales"),
        )

    def test_login_hook_prompts_only_in_interactive_ssh_sessions(self) -> None:
        # Non-interactive SSH (scp, rsync, Ansible) must never reach the setup
        # prompt. The first-login regressions run the hook without a TTY, so
        # they cannot observe these guards.
        profile_hook = (ROLE_ROOT / "templates/workstation-setup-profile.sh.j2").read_text(encoding="utf-8")

        for guard in ("[ -t 0 ]", "[ -t 1 ]", "SSH_CONNECTION", "SSH_TTY"):
            self.assertIn(guard, profile_hook)

    def test_origin_firewall_contract(self) -> None:
        firewall_tasks = load_yaml(ROLE_ROOT / "tasks/origin_firewall.yml")
        firewall_task_names = [t.get("name") for t in firewall_tasks]

        # Removing the old ruleset before the replacement is active would leave
        # the protected ports open in between.
        replacement_activation_and_legacy_cleanup = [
            "Enable workstation origin firewall service",
            "Flush workstation origin firewall handlers",
            "Stop legacy AoE LAN proxy firewall service",
            "Remove legacy AoE LAN proxy firewall table",
            "Remove legacy AoE LAN proxy firewall rules",
        ]
        self.assertEqual(
            [firewall_task_names.index(name) for name in replacement_activation_and_legacy_cleanup],
            sorted(firewall_task_names.index(name) for name in replacement_activation_and_legacy_cleanup),
            msg="replacement firewall activation must complete before ordered legacy AoE cleanup",
        )

        # ansible.builtin.shell has no check-mode support. Without this opt-out
        # the probe is skipped under --check and the resolution assert fails.
        resolution = task_named(firewall_tasks, "Resolve workstation origin firewall allowlist address")
        self.assertIs(resolution.get("check_mode"), False)

        # The role owns only its own table. A global /etc/nftables.conf (the
        # first AoE firewall shipped one starting with `flush ruleset`) would
        # wipe Docker's nft rules on every load.
        rendered_firewall_tasks = yaml.safe_dump(firewall_tasks, sort_keys=True)
        self.assertNotIn("/etc/nftables.conf", rendered_firewall_tasks)

        environment = Environment(
            loader=FileSystemLoader(ROLE_ROOT / "templates"),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
        rendered_firewall = environment.get_template("workstation-origin-firewall.nft.j2").render(
            workstation_origin_firewall_protected_ports=[4001, 9119, 18789, 8788],
            workstation_origin_firewall_allowed_ipv4=["192.0.2.10", "192.0.2.11"],
        )
        self.assertNotIn("flush ruleset", rendered_firewall)
        self.assertIn("table inet workstation_origin {", rendered_firewall)
        self.assertIn("elements = { 4001, 9119, 18789, 8788 }", rendered_firewall)
        self.assertIn("elements = { 192.0.2.10, 192.0.2.11 }", rendered_firewall)
        loopback_accept = 'iifname "lo" tcp dport @protected_tcp_ports accept'
        allowed_accept = "ip saddr @allowed_ipv4 tcp dport @protected_tcp_ports accept"
        protected_drop = "tcp dport @protected_tcp_ports drop"
        self.assertLess(rendered_firewall.index(loopback_accept), rendered_firewall.index(allowed_accept))
        self.assertLess(rendered_firewall.index(allowed_accept), rendered_firewall.index(protected_drop))
        for unprotected_port in (80, 443, 22):
            self.assertNotIn(str(unprotected_port), rendered_firewall)

        rendered_firewall_service = environment.get_template(
            "workstation-origin-firewall.service.j2"
        ).render(workstation_origin_firewall_nft_path="/tmp/firewall/custom-origin.nft")
        self.assertIn(
            "ExecStart=/usr/sbin/nft -f /tmp/firewall/custom-origin.nft",
            rendered_firewall_service,
        )
        # ExecStop must delete the table the rules file creates.
        self.assertIn(
            "ExecStop=/usr/sbin/nft delete table inet workstation_origin\n",
            rendered_firewall_service,
        )
        self.assertIn("RemainAfterExit=yes", rendered_firewall_service)

        unit_name = "{{ workstation_origin_firewall_service_path | basename }}"
        # Restarting on every run would delete and reload the table, briefly
        # opening the protected ports. Only the handler restarts, on change.
        # The firewall regression's systemd stub reports no change either way,
        # so it cannot see this.
        enable_task = task_named(firewall_tasks, "Enable workstation origin firewall service")
        self.assertEqual(enable_task["ansible.builtin.systemd"]["state"], "started")
        for task_name in (
            "Enable workstation origin firewall service",
            "Stop workstation origin firewall service when disabled",
        ):
            self.assertEqual(
                task_named(firewall_tasks, task_name)["ansible.builtin.systemd"]["name"], unit_name
            )

        firewall_handlers = load_yaml(ROLE_ROOT / "handlers/main.yml")
        self.assertEqual(len(firewall_handlers), 1)
        self.assertEqual(firewall_handlers[0]["name"], "Restart workstation origin firewall")
        self.assertEqual(firewall_handlers[0]["ansible.builtin.systemd"]["name"], unit_name)
        self.assertEqual(firewall_handlers[0]["ansible.builtin.systemd"]["state"], "restarted")

    def test_persistent_home_mount_probe_runs_in_check_mode(self) -> None:
        """The mount probe must opt out of check mode, or check runs fail on correct hosts.

        ansible.builtin.command has no check-mode support, so without check_mode: false the
        probe is skipped and the conflict assert loses its mount evidence. An already-mounted
        path then matches none of the assert's accepted shapes, and every check run fails on
        paths that are already in their desired state. The probe is read-only, so running it
        during a check mutates nothing.
        """
        tasks = flatten_tasks(load_yaml(ROLE_ROOT / "tasks/persistent_home.yml"))
        probes = [
            task
            for task in tasks
            if "findmnt" in str(task.get("ansible.builtin.command", {}).get("cmd", ""))
        ]

        self.assertEqual(len(probes), 1, "expected exactly one findmnt mount probe")
        self.assertIs(probes[0].get("check_mode"), False)
        self.assertIs(probes[0].get("changed_when"), False)


if __name__ == "__main__":
    unittest.main()
