#!/usr/bin/env python3
"""Contract tests for the shared origin firewall role."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_ROOT = REPO_ROOT / "playbooks/roles/config/lxc_origin_firewall"


def load_yaml(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def task_named(tasks: list[dict[str, object]], name: str) -> dict[str, object]:
    return next(task for task in tasks if task.get("name") == name)


class OriginFirewallRoleTests(unittest.TestCase):
    def test_origin_firewall_contract(self) -> None:
        firewall_tasks = load_yaml(ROLE_ROOT / "tasks/main.yml")

        # ansible.builtin.shell has no check-mode support. Without this opt-out
        # the probe is skipped under --check and the resolution assert fails.
        resolution = task_named(firewall_tasks, "Resolve origin firewall allowlist address")
        self.assertIs(resolution.get("check_mode"), False)

        # The role owns only its own table. A global /etc/nftables.conf that
        # starts with `flush ruleset` would wipe Docker's nft rules on every load.
        rendered_firewall_tasks = yaml.safe_dump(firewall_tasks, sort_keys=True)
        self.assertNotIn("/etc/nftables.conf", rendered_firewall_tasks)

        environment = Environment(
            loader=FileSystemLoader(ROLE_ROOT / "templates"),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
        rendered_firewall = environment.get_template("origin-firewall.nft.j2").render(
            lxc_origin_firewall_protected_ports=[4001, 9119, 18789, 8788],
            lxc_origin_firewall_allowed_ipv4=["192.0.2.10", "192.0.2.11"],
        )
        self.assertNotIn("flush ruleset", rendered_firewall)
        self.assertIn("table inet origin_firewall {", rendered_firewall)
        self.assertIn("elements = { 4001, 9119, 18789, 8788 }", rendered_firewall)
        self.assertIn("elements = { 192.0.2.10, 192.0.2.11 }", rendered_firewall)
        loopback_accept = 'iifname "lo" tcp dport @protected_tcp_ports accept'
        allowed_accept = "ip saddr @allowed_ipv4 tcp dport @protected_tcp_ports accept"
        protected_drop = "tcp dport @protected_tcp_ports drop"
        self.assertLess(rendered_firewall.index(loopback_accept), rendered_firewall.index(allowed_accept))
        self.assertLess(rendered_firewall.index(allowed_accept), rendered_firewall.index(protected_drop))

        rendered_firewall_service = environment.get_template(
            "origin-firewall.service.j2"
        ).render(lxc_origin_firewall_nft_path="/tmp/firewall/custom-origin.nft")
        self.assertIn(
            "ExecStart=/usr/sbin/nft -f /tmp/firewall/custom-origin.nft",
            rendered_firewall_service,
        )
        # ExecStop must delete the table the rules file creates.
        self.assertIn(
            "ExecStop=/usr/sbin/nft delete table inet origin_firewall\n",
            rendered_firewall_service,
        )
        self.assertIn("RemainAfterExit=yes", rendered_firewall_service)

        unit_name = "{{ lxc_origin_firewall_service_path | basename }}"
        # Restarting on every run would delete and reload the table, briefly
        # opening the protected ports. Only the handler restarts, on change.
        # The firewall regression's systemd stub reports no change either way,
        # so it cannot see this.
        enable_task = task_named(firewall_tasks, "Enable origin firewall service")
        self.assertEqual(enable_task["ansible.builtin.systemd"]["state"], "started")
        for task_name in (
            "Enable origin firewall service",
            "Stop origin firewall service when disabled",
        ):
            self.assertEqual(
                task_named(firewall_tasks, task_name)["ansible.builtin.systemd"]["name"], unit_name
            )

        firewall_handlers = load_yaml(ROLE_ROOT / "handlers/main.yml")
        self.assertEqual(firewall_handlers[0]["ansible.builtin.systemd"]["name"], unit_name)
        self.assertEqual(firewall_handlers[0]["ansible.builtin.systemd"]["state"], "restarted")


if __name__ == "__main__":
    unittest.main()
