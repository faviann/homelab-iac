#!/usr/bin/env python3
"""Unit tests for OIDC manifest validation and blueprint generation."""

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


def minimal_app(**overrides) -> dict:
    base = {
        "name": "TestApp",
        "slug": "test-app",
        "provider_name": "test-app-oidc",
        "launch_url": "https://test.example.com",
        "client_id": "test-app",
        "client_secret_var": "auth_test_oidc_client_secret",
        "signing_certificate_var": "auth_test_oidc_signing_cert",
        "redirect_uris": ["https://test.example.com/callback"],
    }
    base.update(overrides)
    return base


class OidcManifestValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_valid_manifest_passes(self):
        self.mod.validate_oidc_manifest([minimal_app()])

    def test_duplicate_slug_fails(self):
        apps = [minimal_app(), minimal_app(client_id="other")]
        with self.assertRaises(ValueError) as cm:
            self.mod.validate_oidc_manifest(apps)
        self.assertIn("slug", str(cm.exception))

    def test_duplicate_client_id_fails(self):
        apps = [minimal_app(), minimal_app(slug="other-app")]
        with self.assertRaises(ValueError) as cm:
            self.mod.validate_oidc_manifest(apps)
        self.assertIn("client_id", str(cm.exception))

    def test_non_https_redirect_uri_fails(self):
        apps = [minimal_app(redirect_uris=["http://test.example.com/callback"])]
        with self.assertRaises(ValueError) as cm:
            self.mod.validate_oidc_manifest(apps)
        self.assertIn("https", str(cm.exception))

    def test_relative_redirect_uri_fails(self):
        apps = [minimal_app(redirect_uris=["/callback"])]
        with self.assertRaises(ValueError) as cm:
            self.mod.validate_oidc_manifest(apps)
        self.assertIn("https", str(cm.exception))

    def test_conflicting_scope_mapping_name_fails(self):
        mapping_a = {"name": "Email Verify", "scope_name": "email", "expression": "return {}"}
        mapping_b = {"name": "Email Verify", "scope_name": "profile", "expression": "return {}"}
        apps = [
            minimal_app(custom_scope_mappings=[mapping_a]),
            minimal_app(slug="other-app", client_id="other", custom_scope_mappings=[mapping_b]),
        ]
        with self.assertRaises(ValueError) as cm:
            self.mod.validate_oidc_manifest(apps)
        self.assertIn("Email Verify", str(cm.exception))

    def test_identical_shared_scope_mapping_passes(self):
        mapping = {"name": "Email Verify", "scope_name": "email", "expression": "return {}"}
        apps = [
            minimal_app(custom_scope_mappings=[mapping]),
            minimal_app(slug="other-app", client_id="other", custom_scope_mappings=[mapping]),
        ]
        self.mod.validate_oidc_manifest(apps)

    def test_missing_required_field_slug_fails(self):
        app = minimal_app()
        del app["slug"]
        with self.assertRaises(ValueError) as cm:
            self.mod.validate_oidc_manifest([app])
        self.assertIn("slug", str(cm.exception))

    def test_missing_required_field_client_secret_var_fails(self):
        app = minimal_app()
        del app["client_secret_var"]
        with self.assertRaises(ValueError) as cm:
            self.mod.validate_oidc_manifest([app])
        self.assertIn("client_secret_var", str(cm.exception))

    def test_empty_apps_passes(self):
        self.mod.validate_oidc_manifest([])

    def test_multiple_redirect_uris_all_https_passes(self):
        apps = [minimal_app(redirect_uris=[
            "https://app.example.com/callback",
            "https://app.example.com/mobile-redirect",
        ])]
        self.mod.validate_oidc_manifest(apps)


class OidcBlueprintGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_generation_is_deterministic(self):
        apps = [minimal_app()]
        content1 = self.mod.generate_oidc_blueprint_content(apps)
        content2 = self.mod.generate_oidc_blueprint_content(apps)
        self.assertEqual(content1, content2)

    def test_generated_content_starts_with_version(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app()])
        self.assertTrue(content.startswith("version: 1\n"))

    def test_generated_content_contains_instance_name(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app()])
        self.assertIn("repo-auth-oidc-apps", content)

    def test_generated_content_contains_app_slug(self):
        apps = [minimal_app()]
        content = self.mod.generate_oidc_blueprint_content(apps)
        self.assertIn("test-app", content)
        self.assertIn("slug: test-app", content)

    def test_generated_content_has_expected_models(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app()])
        self.assertIn("authentik_providers_oauth2.oauth2provider", content)
        self.assertIn("authentik_core.application", content)
        self.assertIn("authentik_policies.policybinding", content)

    def test_jinja_client_secret_expression_is_literal(self):
        apps = [minimal_app()]
        content = self.mod.generate_oidc_blueprint_content(apps)
        self.assertIn("{{ auth_test_oidc_client_secret | replace('$', '$$') }}", content)

    def test_jinja_signing_key_expression_is_literal(self):
        apps = [minimal_app()]
        content = self.mod.generate_oidc_blueprint_content(apps)
        self.assertIn("{{ auth_test_oidc_signing_cert | tojson }}", content)

    def test_shared_scope_mapping_emitted_once(self):
        mapping = {"name": "Email Verify", "scope_name": "email", "expression": "return {}"}
        apps = [
            minimal_app(custom_scope_mappings=[mapping]),
            minimal_app(slug="other-app", client_id="other", custom_scope_mappings=[mapping]),
        ]
        content = self.mod.generate_oidc_blueprint_content(apps)
        self.assertEqual(content.count("id: scope-email-verify"), 1)
        self.assertEqual(content.count("!KeyOf scope-email-verify"), 2)

    def test_scope_mapping_description_included_when_present(self):
        mapping = {
            "name": "Email Verify",
            "scope_name": "email",
            "description": "Verified email claim",
            "expression": "return {}",
        }
        content = self.mod.generate_oidc_blueprint_content([minimal_app(custom_scope_mappings=[mapping])])
        self.assertIn("description: Verified email claim", content)

    def test_scope_mapping_description_omitted_when_absent(self):
        mapping = {"name": "Email Verify", "scope_name": "email", "expression": "return {}"}
        content = self.mod.generate_oidc_blueprint_content([minimal_app(custom_scope_mappings=[mapping])])
        # "    description:" (4-space indent) would only appear inside a scope mapping attrs block
        self.assertNotIn("    description:", content)

    def test_multiple_redirect_uris_all_emitted(self):
        apps = [minimal_app(redirect_uris=[
            "https://app.example.com/callback",
            "https://app.example.com/mobile-redirect",
        ])]
        content = self.mod.generate_oidc_blueprint_content(apps)
        self.assertIn("https://app.example.com/callback", content)
        self.assertIn("https://app.example.com/mobile-redirect", content)
        self.assertEqual(content.count("matching_mode: strict"), 2)

    def test_always_allow_policy_emitted(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app(policy="always-allow")])
        self.assertIn("name, always-allow", content)

    def test_empty_apps_produces_valid_header(self):
        content = self.mod.generate_oidc_blueprint_content([])
        self.assertIn("version: 1", content)
        self.assertIn("entries:", content)

    def test_real_manifest_generates_expected_apps(self):
        apps = self.mod.load_oidc_manifest()
        content = self.mod.generate_oidc_blueprint_content(apps)
        for slug in (
            "romm-public",
            "audiobookshelf-public",
            "komga-public",
            "calibre-web-automated-public",
        ):
            self.assertIn(f"slug: {slug}", content)

    def test_real_manifest_reading_scope_emitted_once(self):
        apps = self.mod.load_oidc_manifest()
        content = self.mod.generate_oidc_blueprint_content(apps)
        self.assertEqual(content.count("id: scope-reading-apps-email-verification"), 1)
        self.assertEqual(content.count("!KeyOf scope-reading-apps-email-verification"), 4)

    def test_real_manifest_validates_cleanly(self):
        apps = self.mod.load_oidc_manifest()
        self.mod.validate_oidc_manifest(apps)


class OidcBlueprintPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_oidc_blueprint_in_plan(self):
        plan = self.mod.blueprint_plan([])
        names = [name for name, _ in plan]
        self.assertIn("repo-auth-oidc-apps", names)

    def test_oidc_blueprint_path_in_plan(self):
        plan = self.mod.blueprint_plan([])
        paths = [path for _, path in plan]
        self.assertIn("80-oidc-apps.yaml", paths)

    def test_oidc_blueprint_after_outposts_in_plan(self):
        plan = self.mod.blueprint_plan([])
        names = [name for name, _ in plan]
        self.assertGreater(names.index("repo-auth-oidc-apps"), names.index("repo-auth-outposts"))

    def test_navidrome_password_change_sync_blueprint_precedes_providers(self):
        plan = self.mod.blueprint_plan([])
        names = [name for name, _ in plan]
        self.assertIn("repo-auth-navidrome-password-change-sync", names)
        self.assertGreater(
            names.index("repo-auth-navidrome-password-change-sync"),
            names.index("repo-auth-registration-approval-flow"),
        )
        self.assertLess(
            names.index("repo-auth-navidrome-password-change-sync"),
            names.index("repo-auth-providers"),
        )


if __name__ == "__main__":
    unittest.main()
