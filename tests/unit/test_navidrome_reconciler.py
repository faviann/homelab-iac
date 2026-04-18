#!/usr/bin/env python3
"""Unit tests for the Navidrome reconciler planning logic."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "stacks" / "public" / "music" / "reconciler" / "reconciler.py"


def load_script():
    spec = importlib.util.spec_from_file_location("navidrome_reconciler", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["navidrome_reconciler"] = module
    spec.loader.exec_module(module)
    return module


class NavidromeReconcilerPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_active_media_user_missing_from_navidrome_is_created(self):
        operations = self.mod.plan_reconciliation(
            [
                {
                    "username": "alice",
                    "email": "alice@example.com",
                    "is_active": True,
                    "groups_obj": [{"name": "media"}],
                }
            ],
            [],
        )

        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["action"], "create")
        self.assertEqual(operations[0]["payload"]["userName"], "alice")

    def test_active_media_user_is_reenabled_when_disabled(self):
        operations = self.mod.plan_reconciliation(
            [
                {
                    "username": "alice",
                    "email": "alice@example.com",
                    "is_active": True,
                    "groups_obj": [{"name": "media"}],
                }
            ],
            [
                {
                    "id": 10,
                    "userName": "alice",
                    "email": "alice@example.com",
                    "isAdmin": False,
                    "isDisabled": True,
                }
            ],
        )

        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["action"], "update")
        self.assertFalse(operations[0]["payload"]["isDisabled"])

    def test_non_media_user_is_disabled_when_present(self):
        operations = self.mod.plan_reconciliation(
            [
                {
                    "username": "alice",
                    "email": "alice@example.com",
                    "is_active": True,
                    "groups_obj": [{"name": "other"}],
                }
            ],
            [
                {
                    "id": 10,
                    "userName": "alice",
                    "email": "alice@example.com",
                    "isAdmin": False,
                    "isDisabled": False,
                }
            ],
        )

        self.assertEqual(len(operations), 1)
        self.assertTrue(operations[0]["payload"]["isDisabled"])

    def test_email_change_updates_existing_user(self):
        operations = self.mod.plan_reconciliation(
            [
                {
                    "username": "alice",
                    "email": "new@example.com",
                    "is_active": True,
                    "groups_obj": [{"name": "media"}],
                }
            ],
            [
                {
                    "id": 10,
                    "userName": "alice",
                    "email": "old@example.com",
                    "isAdmin": True,
                    "isDisabled": False,
                }
            ],
        )

        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["payload"]["email"], "new@example.com")
        self.assertTrue(operations[0]["payload"]["isAdmin"])

    def test_is_active_field_is_supported_for_navidrome_updates(self):
        payload = self.mod._build_update_payload(
            {
                "id": 10,
                "userName": "alice",
                "email": "alice@example.com",
                "isAdmin": False,
                "isActive": False,
            },
            email="alice@example.com",
            disabled=False,
        )

        self.assertTrue(payload["isActive"])

    def test_navidrome_api_headers_uses_login_token(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["headers"] = dict(req.header_items())
            captured["body"] = req.data.decode("utf-8") if req.data else ""
            return FakeResponse({"token": "navidrome-token"})

        original_urlopen = self.mod.request.urlopen
        self.mod.request.urlopen = fake_urlopen
        try:
            headers = self.mod._navidrome_api_headers("http://navidrome:4533", "svc-automation", "secret")
        finally:
            self.mod.request.urlopen = original_urlopen

        self.assertEqual(captured["url"], "http://navidrome:4533/auth/login")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(json.loads(captured["body"]), {"username": "svc-automation", "password": "secret"})
        self.assertEqual(headers, {"Accept": "application/json", "X-ND-Authorization": "Bearer navidrome-token"})


if __name__ == "__main__":
    unittest.main()