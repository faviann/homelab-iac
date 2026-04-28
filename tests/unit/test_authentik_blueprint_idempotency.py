#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "authentik_blueprint_sync.py"


def load_script():
    spec = importlib.util.spec_from_file_location("authentik_blueprint_sync", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script from {SCRIPT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["authentik_blueprint_sync"] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeBlueprintClient:
    def __init__(
        self,
        *,
        available: list[dict[str, Any]],
        instances: list[dict[str, Any]],
    ):
        self.available = available
        self.instances = instances
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.applied: list[str] = []
        self.deleted: list[str] = []
        self.requested: list[tuple[str, str, dict[str, Any] | None]] = []

    def get_paginated(self, path: str) -> list[dict[str, Any]]:
        if path == "/api/v3/managed/blueprints/?page_size=200":
            return list(self.instances)
        raise AssertionError(f"Unexpected paginated path: {path}")

    def request_json(
        self,
        method: str,
        path_or_url: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        self.requested.append((method, path_or_url, payload))
        if method == "GET" and path_or_url == "/api/v3/managed/blueprints/available/":
            return list(self.available)
        if method == "POST" and path_or_url == "/api/v3/managed/blueprints/":
            created = {
                "pk": "created-pk",
                "name": payload["name"],
                "path": payload["path"],
                "enabled": payload["enabled"],
                "status": "successful",
                "last_applied": None,
                "last_applied_hash": None,
            }
            self.created.append(dict(payload))
            self.instances.append(created)
            return created
        if method == "PATCH" and path_or_url.startswith("/api/v3/managed/blueprints/"):
            pk = path_or_url.removeprefix("/api/v3/managed/blueprints/").removesuffix("/")
            self.updated.append((pk, dict(payload)))
            instance = next(item for item in self.instances if item["pk"] == pk)
            instance.update(payload)
            return instance
        if method == "POST" and path_or_url.endswith("/apply/"):
            pk = path_or_url.removeprefix("/api/v3/managed/blueprints/").removesuffix("/apply/")
            self.applied.append(pk)
            instance = next(item for item in self.instances if item["pk"] == pk)
            available = next(item for item in self.available if item["path"] == instance["path"])
            instance["status"] = "successful"
            instance["last_applied"] = "later"
            instance["last_applied_hash"] = available.get("hash")
            return {}
        if method == "GET" and path_or_url.startswith("/api/v3/managed/blueprints/"):
            pk = path_or_url.removeprefix("/api/v3/managed/blueprints/").removesuffix("/")
            return next(item for item in self.instances if item["pk"] == pk)
        if method == "DELETE" and path_or_url.startswith("/api/v3/managed/blueprints/"):
            pk = path_or_url.removeprefix("/api/v3/managed/blueprints/").removesuffix("/")
            self.deleted.append(pk)
            self.instances = [item for item in self.instances if item["pk"] != pk]
            return None
        raise AssertionError(f"Unexpected request: {method} {path_or_url}")


class AuthentikBlueprintIdempotencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def setUp(self):
        self.original_plan = self.mod.blueprint_plan
        self.original_wait = self.mod.wait_for_instance
        self.original_navidrome = self.mod.ensure_navidrome_password_change_sync_binding
        self.mod.blueprint_plan = lambda flow_slugs: [("repo-auth-groups", "10-groups.yaml")]
        self.mod.wait_for_instance = lambda client, instance_pk, previous_last_applied: client.request_json(
            "GET",
            f"/api/v3/managed/blueprints/{instance_pk}/",
        )

    def tearDown(self):
        self.mod.blueprint_plan = self.original_plan
        self.mod.wait_for_instance = self.original_wait
        self.mod.ensure_navidrome_password_change_sync_binding = self.original_navidrome

    def test_matching_hash_skips_apply_and_reports_unchanged(self):
        client = FakeBlueprintClient(
            available=[{"path": "custom/10-groups.yaml", "hash": "abc"}],
            instances=[
                {
                    "pk": "instance-pk",
                    "name": "repo-auth-groups",
                    "path": "custom/10-groups.yaml",
                    "enabled": True,
                    "status": "successful",
                    "last_applied": "earlier",
                    "last_applied_hash": "abc",
                }
            ],
        )

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertFalse(result["changed"])
        self.assertEqual(client.applied, [])
        self.assertEqual(result["applied"][0]["action"], "unchanged")

    def test_hash_mismatch_applies_and_reports_changed(self):
        client = FakeBlueprintClient(
            available=[{"path": "custom/10-groups.yaml", "hash": "new"}],
            instances=[
                {
                    "pk": "instance-pk",
                    "name": "repo-auth-groups",
                    "path": "custom/10-groups.yaml",
                    "enabled": True,
                    "status": "successful",
                    "last_applied": "earlier",
                    "last_applied_hash": "old",
                }
            ],
        )

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.applied, ["instance-pk"])
        self.assertEqual(result["applied"][0]["action"], "applied")

    def test_metadata_mismatch_updates_applies_and_reports_changed(self):
        client = FakeBlueprintClient(
            available=[{"path": "custom/10-groups.yaml", "hash": "abc"}],
            instances=[
                {
                    "pk": "instance-pk",
                    "name": "repo-auth-groups",
                    "path": "custom/10-groups.yaml",
                    "enabled": False,
                    "status": "successful",
                    "last_applied": "earlier",
                    "last_applied_hash": "abc",
                }
            ],
        )

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.updated, [("instance-pk", {
            "name": "repo-auth-groups",
            "path": "custom/10-groups.yaml",
            "enabled": True,
        })])
        self.assertEqual(client.applied, ["instance-pk"])
        self.assertEqual(result["applied"][0]["action"], "updated+applied")

    def test_missing_instance_creates_applies_and_reports_changed(self):
        client = FakeBlueprintClient(
            available=[{"path": "custom/10-groups.yaml", "hash": "abc"}],
            instances=[],
        )

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.created, [{
            "name": "repo-auth-groups",
            "path": "custom/10-groups.yaml",
            "enabled": True,
        }])
        self.assertEqual(client.applied, ["created-pk"])
        self.assertEqual(result["applied"][0]["action"], "created+applied")

    def test_non_success_status_applies_even_when_hash_matches(self):
        client = FakeBlueprintClient(
            available=[{"path": "custom/10-groups.yaml", "hash": "abc"}],
            instances=[
                {
                    "pk": "instance-pk",
                    "name": "repo-auth-groups",
                    "path": "custom/10-groups.yaml",
                    "enabled": True,
                    "status": "error",
                    "last_applied": "earlier",
                    "last_applied_hash": "abc",
                }
            ],
        )

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.applied, ["instance-pk"])
        self.assertEqual(result["applied"][0]["action"], "applied")

    def test_path_fallback_finds_instance_by_path_when_name_differs(self):
        client = FakeBlueprintClient(
            available=[{"path": "custom/10-groups.yaml", "hash": "abc"}],
            instances=[
                {
                    "pk": "instance-pk",
                    "name": "repo-auth-groups-old",
                    "path": "custom/10-groups.yaml",
                    "enabled": True,
                    "status": "successful",
                    "last_applied": "earlier",
                    "last_applied_hash": "abc",
                }
            ],
        )

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.updated, [("instance-pk", {
            "name": "repo-auth-groups",
            "path": "custom/10-groups.yaml",
            "enabled": True,
        })])
        self.assertEqual(client.applied, ["instance-pk"])
        self.assertEqual(result["applied"][0]["action"], "updated+applied")

    def test_none_available_hash_forces_apply(self):
        client = FakeBlueprintClient(
            available=[{"path": "custom/10-groups.yaml"}],
            instances=[
                {
                    "pk": "instance-pk",
                    "name": "repo-auth-groups",
                    "path": "custom/10-groups.yaml",
                    "enabled": True,
                    "status": "successful",
                    "last_applied": "earlier",
                    "last_applied_hash": None,
                }
            ],
        )

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.applied, ["instance-pk"])
        self.assertEqual(result["applied"][0]["action"], "applied")

    def test_navidrome_unchanged_binding_reports_unchanged(self):
        self.mod.blueprint_plan = lambda flow_slugs: [
            (self.mod.NAVIDROME_PASSWORD_CHANGE_SYNC_BLUEPRINT_NAME, "27-navidrome-password-change-sync.yaml")
        ]
        self.mod.ensure_navidrome_password_change_sync_binding = lambda client: {
            "status": "successful",
            "changed": False,
            "action": "unchanged",
            "binding_pk": "binding-pk",
            "target_pk": "target-pk",
        }
        client = FakeBlueprintClient(available=[], instances=[])

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertFalse(result["changed"])
        self.assertEqual(result["applied"][0]["action"], "unchanged")

    def test_navidrome_changed_binding_reports_changed(self):
        self.mod.blueprint_plan = lambda flow_slugs: [
            (self.mod.NAVIDROME_PASSWORD_CHANGE_SYNC_BLUEPRINT_NAME, "27-navidrome-password-change-sync.yaml")
        ]
        self.mod.ensure_navidrome_password_change_sync_binding = lambda client: {
            "status": "successful",
            "changed": True,
            "action": "updated-binding",
            "binding_pk": "binding-pk",
            "target_pk": "target-pk",
        }
        client = FakeBlueprintClient(available=[], instances=[])

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(result["applied"][0]["action"], "updated-binding")

    def test_navidrome_stale_blueprint_instance_delete_reports_changed(self):
        self.mod.blueprint_plan = lambda flow_slugs: [
            (self.mod.NAVIDROME_PASSWORD_CHANGE_SYNC_BLUEPRINT_NAME, "27-navidrome-password-change-sync.yaml")
        ]
        self.mod.ensure_navidrome_password_change_sync_binding = lambda client: {
            "status": "successful",
            "changed": False,
            "action": "unchanged",
            "binding_pk": "binding-pk",
            "target_pk": "target-pk",
        }
        client = FakeBlueprintClient(
            available=[],
            instances=[
                {
                    "pk": "stale-pk",
                    "name": self.mod.NAVIDROME_PASSWORD_CHANGE_SYNC_BLUEPRINT_NAME,
                    "path": "custom/27-navidrome-password-change-sync.yaml",
                    "enabled": True,
                    "status": "successful",
                    "last_applied": "earlier",
                    "last_applied_hash": "abc",
                }
            ],
        )

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.deleted, ["stale-pk"])
        self.assertEqual(result["applied"][0]["action"], "deleted-stale-instance")


if __name__ == "__main__":
    unittest.main()