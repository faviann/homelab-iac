#!/usr/bin/env python3
"""Tests for vault-based token resolution in authentik_blueprint_sync."""

from __future__ import annotations

import unittest
from pathlib import Path

import importlib.util
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "authentik_blueprint_sync.py"

VAULT_FILE = REPO_ROOT / "inventory" / "group_vars" / "all" / "vault.yml"
VAULT_PASS_FILE = Path.home() / ".ansible" / "vault-pass"


def load_script():
    spec = importlib.util.spec_from_file_location("authentik_blueprint_sync", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script from {SCRIPT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["authentik_blueprint_sync"] = mod
    spec.loader.exec_module(mod)
    return mod


class ExtractVaultTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_extracts_token_from_yaml_string(self):
        yaml_str = "vault_auth_blueprint_api_token: mytoken123\nother_key: other_value\n"
        token = self.mod._extract_vault_token(yaml_str, "vault_auth_blueprint_api_token")
        self.assertEqual(token, "mytoken123")

    def test_raises_on_missing_key(self):
        yaml_str = "some_other_key: somevalue\n"
        with self.assertRaises(KeyError):
            self.mod._extract_vault_token(yaml_str, "vault_auth_blueprint_api_token")

    def test_strips_whitespace_from_token(self):
        yaml_str = "vault_auth_blueprint_api_token: '  spaced  '\n"
        token = self.mod._extract_vault_token(yaml_str, "vault_auth_blueprint_api_token")
        self.assertEqual(token, "spaced")


@unittest.skipUnless(
    VAULT_FILE.exists() and VAULT_PASS_FILE.exists(),
    "vault.yml or vault-pass not present — skipping integration tests",
)
class VaultTokenIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_token_from_vault_returns_non_empty_string(self):
        token = self.mod.token_from_vault(VAULT_FILE, VAULT_PASS_FILE)
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 0)

    def test_client_from_vault_connects_to_authentik(self):
        client = self.mod.AuthentikClient.from_vault()
        self.assertIsNotNone(client.base_url)
        self.assertGreater(len(client.token), 0)


if __name__ == "__main__":
    unittest.main()
