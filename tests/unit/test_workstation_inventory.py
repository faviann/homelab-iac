#!/usr/bin/env python3
"""Static inventory checks for the workstation LXC contract."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class WorkstationInventoryTests(unittest.TestCase):
    def test_workstation_inventory_contract(self) -> None:
        inventory = load_yaml(REPO_ROOT / "inventory/hosts.yml")
        workstation_vars = load_yaml(REPO_ROOT / "inventory/host_vars/workstation.yml")

        self.assertIn("workstation", inventory["all"]["children"]["tier_large"]["hosts"])
        self.assertIn("workstation", inventory["all"]["children"]["cap_docker"]["hosts"])
        self.assertNotIn("workstation", inventory["all"]["children"]["cap_wireguard"]["hosts"])

        self.assertEqual(workstation_vars["workstation_enabled"], True)
        self.assertEqual(workstation_vars["docker_user"], "faviann")
        self.assertEqual(workstation_vars["docker_uid"], 1000)
        self.assertEqual(workstation_vars["docker_gid"], 1000)
        self.assertEqual(workstation_vars["workstation_github_users"], ["faviann"])
        self.assertEqual(workstation_vars["docker_agents_enabled"], False)
        self.assertEqual(workstation_vars["traefik_kop_enabled"], False)
        self.assertEqual(workstation_vars["lxc_hwaddr"], "BC:24:11:57:80:06")
        self.assertEqual(workstation_vars["proxmox_lxc_overrides"]["vmid"], 306)
        self.assertEqual(workstation_vars["proxmox_lxc_overrides"]["hostname"], "workstation")
        self.assertEqual(workstation_vars["proxmox_lxc_overrides"]["cores"], 16)
        self.assertEqual(workstation_vars["proxmox_lxc_overrides"]["memory"], 32768)
        self.assertEqual(workstation_vars["proxmox_lxc_overrides"]["disk"], "128")


if __name__ == "__main__":
    unittest.main()
