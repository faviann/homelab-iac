#!/usr/bin/env python3
"""Static contract check for the per-host /shared bind mount."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


class SharedMountContractTests(unittest.TestCase):
    def test_default_shared_bind_source_is_created_on_the_host(self) -> None:
        # A missing bind source stops the container from starting, and nothing
        # inside a new container can create a folder on the Proxmox host.
        with (REPO_ROOT / "inventory/group_vars/all/proxmox.yml").open("r", encoding="utf-8") as handle:
            fleet = yaml.safe_load(handle)
        source = fleet["proxmox_default_bind_mounts"]["mp0"].split(",")[0]

        self.assertIn(source, [entry["path"] for entry in fleet["proxmox_default_host_directories"]])


if __name__ == "__main__":
    unittest.main()
