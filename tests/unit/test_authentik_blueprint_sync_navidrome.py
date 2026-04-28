#!/usr/bin/env python3
"""Unit tests for Authentik blueprint sync API reconciliation paths."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

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


class FakeAuthentikClient:
    def __init__(
        self,
        *,
        policies: list[dict] | None = None,
        bindings: list[dict] | None = None,
        export_entries: list[dict] | None = None,
    ) -> None:
        self.policies = policies if policies is not None else [
            {"pk": "policy-pk", "name": "navidrome-registration-sync-policy"},
        ]
        self.bindings = bindings if bindings is not None else []
        self.export_entries = export_entries if export_entries is not None else self.default_export_entries()
        self.requests: list[dict] = []

    @staticmethod
    def default_export_entries() -> list[dict]:
        return [
            {
                "model": "authentik_flows.flow",
                "identifiers": {"pk": "flow-pk", "slug": "default-password-change"},
            },
            {
                "model": "authentik_stages_prompt.promptstage",
                "identifiers": {"pk": "prompt-stage-pk", "name": "default-password-change-prompt"},
            },
            {
                "model": "authentik_flows.flowstagebinding",
                "identifiers": {
                    "pk": "flow-stage-binding-pk",
                    "target": "flow-pk",
                    "stage": "prompt-stage-pk",
                    "order": 0,
                },
            },
        ]

    def get_paginated(self, path: str) -> list[dict]:
        if path == "/api/v3/policies/all/?page_size=200":
            return self.policies
        if path == "/api/v3/policies/bindings/?page_size=500":
            return self.bindings
        raise AssertionError(f"Unexpected paginated path: {path}")

    def request_text(self, method: str, path: str) -> str:
        self.requests.append({"method": method, "path": path})
        return "entries:\n" + "\n".join(self._entry_yaml(entry) for entry in self.export_entries)

    def request_json(self, method: str, path: str, payload: dict | None = None):
        self.requests.append({"method": method, "path": path, "payload": payload})
        if method == "POST" and path == "/api/v3/policies/bindings/":
            return {"pk": "created-binding-pk", **(payload or {})}
        if method == "PATCH" and path.startswith("/api/v3/policies/bindings/"):
            return {"pk": path.rstrip("/").split("/")[-1], **(payload or {})}
        raise AssertionError(f"Unexpected request: {method} {path}")

    @staticmethod
    def _entry_yaml(entry: dict) -> str:
        lines = ["- model: " + entry["model"], "  identifiers:"]
        for key, value in entry["identifiers"].items():
            lines.append(f"    {key}: {value}")
        return "\n".join(lines)


class NavidromeBindingReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_script()

    def test_creates_binding_when_absent(self):
        client = FakeAuthentikClient()

        result = self.mod.ensure_navidrome_password_change_sync_binding(client)

        post_requests = [
            request for request in client.requests
            if request["method"] == "POST" and request["path"] == "/api/v3/policies/bindings/"
        ]
        self.assertEqual(len(post_requests), 1)
        self.assertEqual(post_requests[0]["payload"], {
            "policy": "policy-pk",
            "target": "flow-stage-binding-pk",
            "order": 0,
            "enabled": True,
            "negate": False,
            "failure_result": False,
            "timeout": 10,
        })
        self.assertEqual(result["binding_pk"], "created-binding-pk")

    def test_leaves_matching_binding_untouched(self):
        client = FakeAuthentikClient(bindings=[{
            "pk": "existing-binding-pk",
            "policy": "policy-pk",
            "target": "flow-stage-binding-pk",
            "order": 0,
            "enabled": True,
            "negate": False,
            "failure_result": False,
            "timeout": 10,
        }])

        result = self.mod.ensure_navidrome_password_change_sync_binding(client)

        mutating_requests = [
            request for request in client.requests
            if request["method"] in {"POST", "PATCH"}
        ]
        self.assertEqual(mutating_requests, [])
        self.assertEqual(result["binding_pk"], "existing-binding-pk")

    def test_patches_drifted_binding_fields(self):
        client = FakeAuthentikClient(bindings=[{
            "pk": "drifted-binding-pk",
            "policy": "policy-pk",
            "target": "flow-stage-binding-pk",
            "order": 99,
            "enabled": False,
            "negate": True,
            "failure_result": True,
            "timeout": 99,
        }])

        result = self.mod.ensure_navidrome_password_change_sync_binding(client)

        patch_requests = [
            request for request in client.requests
            if request["method"] == "PATCH"
        ]
        self.assertEqual(len(patch_requests), 1)
        self.assertEqual(patch_requests[0]["path"], "/api/v3/policies/bindings/drifted-binding-pk/")
        self.assertEqual(patch_requests[0]["payload"], {
            "policy": "policy-pk",
            "target": "flow-stage-binding-pk",
            "order": 0,
            "enabled": True,
            "negate": False,
            "failure_result": False,
            "timeout": 10,
        })
        self.assertEqual(result["binding_pk"], "drifted-binding-pk")

    def test_missing_policy_raises_clear_error(self):
        client = FakeAuthentikClient(policies=[])

        with self.assertRaisesRegex(RuntimeError, "navidrome-registration-sync-policy"):
            self.mod.ensure_navidrome_password_change_sync_binding(client)

    def test_missing_exported_flow_stage_binding_raises_clear_error(self):
        client = FakeAuthentikClient(export_entries=[
            entry for entry in FakeAuthentikClient.default_export_entries()
            if entry["model"] != "authentik_flows.flowstagebinding"
        ])

        with self.assertRaisesRegex(RuntimeError, "flow-stage binding"):
            self.mod.ensure_navidrome_password_change_sync_binding(client)


if __name__ == "__main__":
    unittest.main()
