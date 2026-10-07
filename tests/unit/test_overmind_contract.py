#!/usr/bin/env python3
"""Static contract checks for the Overmind deployment."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


class OvermindContractTests(unittest.TestCase):
    def test_backups_land_on_the_backup_bind_mount(self) -> None:
        # Nothing at deploy time checks this. A mismatch writes backups to the
        # LXC root filesystem, and the freshness check still passes.
        with (REPO_ROOT / "inventory/host_vars/overmind.yml").open("r", encoding="utf-8") as handle:
            overmind_vars = yaml.safe_load(handle)
        backup_dir = overmind_vars["overmind_postgres_backup"]["backup_dir"]
        backup_mount = overmind_vars["proxmox_lxc_bind_mounts_overrides"]["mp4"]

        self.assertEqual(f"mp={backup_dir}", backup_mount.split(",")[1])


if __name__ == "__main__":
    unittest.main()
