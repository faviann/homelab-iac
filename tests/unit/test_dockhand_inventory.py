#!/usr/bin/env python3
"""Static inventory checks for Dockhand configuration wiring."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class DockhandInventoryTests(unittest.TestCase):
    def test_discord_webhook_uses_dockhand_named_vault_key(self) -> None:
        vault_example = load_yaml(REPO_ROOT / "inventory/group_vars/all/vault.yml.example")
        portal_vars = load_yaml(REPO_ROOT / "inventory/host_vars/portal.yml")

        self.assertIn("vault_dockhand_discord_webhook_url", vault_example)
        self.assertNotIn("vault_portal_diun_discord_webhook", vault_example)
        self.assertEqual(
            portal_vars.get("dockhand_discord_webhook_url"),
            "{{ vault_dockhand_discord_webhook_url }}",
        )


if __name__ == "__main__":
    unittest.main()
