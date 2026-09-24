#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import sys
import types
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
        post_apply_updates: dict[str, Any] | None = None,
        final_snapshot_updates: dict[str, Any] | None = None,
    ):
        self.available = available
        self.instances = instances
        self.post_apply_updates = post_apply_updates
        self.final_snapshot_updates = final_snapshot_updates
        self.instance_list_requests = 0
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.applied: list[str] = []
        self.deleted: list[str] = []
        self.requested: list[tuple[str, str, dict[str, Any] | None]] = []

    def get_paginated(self, path: str) -> list[dict[str, Any]]:
        if path == "/api/v3/managed/blueprints/?page_size=200":
            self.instance_list_requests += 1
            if self.instance_list_requests == 2 and self.final_snapshot_updates is not None:
                self.instances[0].update(self.final_snapshot_updates)
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
            if self.post_apply_updates is not None:
                instance.update(self.post_apply_updates)
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


GROUPS_PATH = "custom/10-groups.yaml"


def groups_instance(**overrides: Any) -> dict[str, Any]:
    instance = {
        "pk": "instance-pk",
        "name": "repo-auth-groups",
        "path": GROUPS_PATH,
        "enabled": True,
        "status": "successful",
        "last_applied": "earlier",
        "last_applied_hash": "abc",
    }
    instance.update(overrides)
    return instance


def groups_client(available_hash: str | None, *instances: dict[str, Any], **options: Any) -> FakeBlueprintClient:
    available = {"path": GROUPS_PATH}
    if available_hash is not None:
        available["hash"] = available_hash
    return FakeBlueprintClient(available=[available], instances=list(instances), **options)


class AuthentikBlueprintIdempotencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def setUp(self):
        self.original_plan = self.mod.blueprint_plan
        self.original_navidrome = self.mod.ensure_navidrome_password_change_sync_binding
        self.mod.blueprint_plan = lambda flow_slugs: [("repo-auth-groups", "10-groups.yaml")]

    def tearDown(self):
        self.mod.blueprint_plan = self.original_plan
        self.mod.ensure_navidrome_password_change_sync_binding = self.original_navidrome

    def test_matching_hash_skips_apply_and_reports_unchanged(self):
        client = groups_client("abc", groups_instance())

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertFalse(result["changed"])
        self.assertEqual(client.applied, [])
        self.assertEqual(result["applied"][0]["action"], "unchanged")

    def test_hash_mismatch_applies_and_reports_changed(self):
        client = groups_client("new", groups_instance(last_applied_hash="old"))

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.applied, ["instance-pk"])
        self.assertEqual(result["applied"][0]["action"], "applied")

    def test_successful_apply_without_the_expected_hash_fails(self):
        for observed_hash in ("stale-hash", None):
            with self.subTest(observed_hash=observed_hash):
                client = groups_client(
                    "expected-hash",
                    groups_instance(last_applied_hash="stale-hash"),
                    post_apply_updates={
                        "last_applied_hash": observed_hash,
                        "detail": "apply result was not persisted",
                    },
                )

                with self.assertRaisesRegex(
                    RuntimeError,
                    f"repo-auth-groups.*expected-hash.*{re.escape(repr(observed_hash))}"
                    ".*apply result was not persisted",
                ):
                    self.mod.reconcile_blueprint_instances(client, [])

    def test_final_reobservation_rejects_contradictory_evidence(self):
        for final_snapshot in (
            {"last_applied_hash": "stale-final-hash", "detail": "final snapshot did not retain the applied hash"},
            {"status": "error", "last_applied_hash": "stale-final-hash", "detail": "final validation failed"},
        ):
            with self.subTest(status=final_snapshot.get("status", "successful")):
                client = groups_client(
                    "expected-hash",
                    groups_instance(last_applied="later", last_applied_hash="expected-hash"),
                    final_snapshot_updates=final_snapshot,
                )

                with self.assertRaisesRegex(
                    RuntimeError,
                    f"repo-auth-groups.*expected-hash.*stale-final-hash.*{final_snapshot['detail']}",
                ):
                    self.mod.reconcile_blueprint_instances(client, [])

    def test_apply_error_includes_hashes_and_api_detail(self):
        client = groups_client(
            "expected-hash",
            groups_instance(last_applied_hash="stale-hash"),
            post_apply_updates={
                "status": "error",
                "last_applied_hash": "stale-hash",
                "detail": "validation failed",
            },
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "repo-auth-groups.*expected-hash.*stale-hash.*validation failed",
        ):
            self.mod.reconcile_blueprint_instances(client, [])

    def test_apply_timeout_includes_instance_and_hashes(self):
        client = groups_client(
            "expected-hash",
            groups_instance(last_applied_hash="stale-hash"),
            post_apply_updates={
                "status": "pending",
                "last_applied_hash": "stale-hash",
            },
        )
        original_time = self.mod.time.time
        original_sleep = self.mod.time.sleep
        clock = iter([0, 0, 121])
        self.mod.time.time = lambda: next(clock)
        self.mod.time.sleep = lambda _seconds: None

        try:
            with self.assertRaisesRegex(
                RuntimeError,
                "repo-auth-groups.*expected-hash.*stale-hash",
            ):
                self.mod.reconcile_blueprint_instances(client, [])
        finally:
            self.mod.time.time = original_time
            self.mod.time.sleep = original_sleep

    def test_apply_timeout_before_first_get_uses_pre_apply_diagnostics(self):
        client = groups_client("expected-hash", groups_instance(last_applied_hash="stale-pre-apply-hash"))
        original_time = self.mod.time.time
        clock = iter([0, 121])
        self.mod.time.time = lambda: next(clock)

        try:
            with self.assertRaisesRegex(
                RuntimeError,
                "repo-auth-groups.*expected-hash.*stale-pre-apply-hash",
            ):
                self.mod.reconcile_blueprint_instances(client, [])
        finally:
            self.mod.time.time = original_time

        self.assertNotIn(
            ("GET", "/api/v3/managed/blueprints/instance-pk/", None),
            client.requested,
        )

    def test_metadata_mismatch_updates_applies_and_reports_changed(self):
        client = groups_client("abc", groups_instance(enabled=False))

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.updated, [("instance-pk", {
            "name": "repo-auth-groups",
            "path": GROUPS_PATH,
            "enabled": True,
        })])
        self.assertEqual(client.applied, ["instance-pk"])
        self.assertEqual(result["applied"][0]["action"], "updated+applied")

    def test_missing_instance_creates_applies_and_reports_changed(self):
        client = groups_client("abc")

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.created, [{
            "name": "repo-auth-groups",
            "path": GROUPS_PATH,
            "enabled": True,
        }])
        self.assertEqual(client.applied, ["created-pk"])
        self.assertEqual(result["applied"][0]["action"], "created+applied")

    def test_non_success_status_applies_even_when_hash_matches(self):
        client = groups_client("abc", groups_instance(status="error"))

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.applied, ["instance-pk"])
        self.assertEqual(result["applied"][0]["action"], "applied")

    def test_path_fallback_finds_instance_by_path_when_name_differs(self):
        client = groups_client("abc", groups_instance(name="repo-auth-groups-old"))

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.updated, [("instance-pk", {
            "name": "repo-auth-groups",
            "path": GROUPS_PATH,
            "enabled": True,
        })])
        self.assertEqual(client.applied, ["instance-pk"])
        self.assertEqual(result["applied"][0]["action"], "updated+applied")

    def test_none_available_hash_forces_apply(self):
        client = groups_client(None, groups_instance(last_applied_hash=None))

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.applied, ["instance-pk"])
        self.assertEqual(result["applied"][0]["action"], "applied")

    def test_metadata_repair_removes_stale_lookup_keys_between_plan_entries(self):
        self.mod.blueprint_plan = lambda flow_slugs: [
            ("repo-auth-groups", "10-groups.yaml"),
            ("repo-auth-roles", "20-roles.yaml"),
        ]
        client = FakeBlueprintClient(
            available=[
                {"path": GROUPS_PATH, "hash": "groups-hash"},
                {"path": "custom/20-roles.yaml", "hash": "roles-hash"},
            ],
            instances=[
                groups_instance(pk="groups-pk", path="custom/20-roles.yaml", last_applied_hash="old"),
            ],
        )

        result = self.mod.reconcile_blueprint_instances(client, [])

        self.assertTrue(result["changed"])
        self.assertEqual(client.updated, [("groups-pk", {
            "name": "repo-auth-groups",
            "path": GROUPS_PATH,
            "enabled": True,
        })])
        self.assertEqual(client.created, [{
            "name": "repo-auth-roles",
            "path": "custom/20-roles.yaml",
            "enabled": True,
        }])
        self.assertEqual(client.applied, ["groups-pk", "created-pk"])
        self.assertEqual({item["name"] for item in result["applied"]}, {"repo-auth-groups", "repo-auth-roles"})

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


class ScriptCliOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_main_apply_emits_valid_json_with_changed_boolean(self):
        fake_client = types.SimpleNamespace(base_url="https://auth.faviann.com")
        original_parse_args = self.mod.parse_args
        original_from_token_file = self.mod.AuthentikClient.from_token_file
        original_generate = self.mod.generate_oidc_blueprint_file
        original_collect_state = self.mod.collect_state
        original_flow_slug_set = self.mod.flow_slug_set
        original_reconcile = self.mod.reconcile_blueprint_instances
        stdout = io.StringIO()

        self.mod.parse_args = lambda: types.SimpleNamespace(
            command="apply",
            token_file="token-file",
            base_url="https://auth.faviann.com",
        )
        self.mod.AuthentikClient.from_token_file = lambda token_file, base_url=None: fake_client
        self.mod.generate_oidc_blueprint_file = lambda: None
        self.mod.collect_state = lambda client: {"flows": []}
        self.mod.flow_slug_set = lambda state: []
        self.mod.reconcile_blueprint_instances = lambda client, flow_slugs: {
            "changed": False,
            "applied": [],
            "available_paths": [],
        }

        try:
            with contextlib.redirect_stdout(stdout):
                exit_code = self.mod.main()
        finally:
            self.mod.parse_args = original_parse_args
            self.mod.AuthentikClient.from_token_file = original_from_token_file
            self.mod.generate_oidc_blueprint_file = original_generate
            self.mod.collect_state = original_collect_state
            self.mod.flow_slug_set = original_flow_slug_set
            self.mod.reconcile_blueprint_instances = original_reconcile

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["base_url"], "https://auth.faviann.com")
        self.assertIn("changed", payload)
        self.assertIs(payload["changed"], False)


if __name__ == "__main__":
    unittest.main()
