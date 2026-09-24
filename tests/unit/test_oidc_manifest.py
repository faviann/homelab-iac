#!/usr/bin/env python3
"""Unit tests for OIDC manifest validation and blueprint generation."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import jinja2
import yaml

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

    def test_unknown_grant_type_fails(self):
        apps = [minimal_app(grant_types=["magic_beans"])]
        with self.assertRaises(ValueError) as cm:
            self.mod.validate_oidc_manifest(apps)
        self.assertIn("magic_beans", str(cm.exception))

    def test_empty_grant_types_list_fails(self):
        apps = [minimal_app(grant_types=[])]
        with self.assertRaises(ValueError) as cm:
            self.mod.validate_oidc_manifest(apps)
        self.assertIn("grant_types", str(cm.exception))

    def test_known_grant_types_pass(self):
        self.mod.validate_oidc_manifest(
            [minimal_app(grant_types=["authorization_code", "refresh_token"])]
        )

    def test_empty_apps_passes(self):
        self.mod.validate_oidc_manifest([])

    def test_multiple_redirect_uris_all_https_passes(self):
        apps = [minimal_app(redirect_uris=[
            "https://app.example.com/callback",
            "https://app.example.com/mobile-redirect",
        ])]
        self.mod.validate_oidc_manifest(apps)


FILTER_PLUGIN_PATH = REPO_ROOT / "playbooks" / "filter_plugins" / "compose_env.py"


class BlueprintLoader(yaml.SafeLoader):
    pass


def _tagged(loader: BlueprintLoader, suffix: str, node: yaml.Node) -> tuple:
    if isinstance(node, yaml.SequenceNode):
        return (f"!{suffix}", loader.construct_sequence(node, deep=True))
    return (f"!{suffix}", loader.construct_scalar(node))


BlueprintLoader.add_multi_constructor("!", _tagged)


def credential_filters() -> dict:
    spec = importlib.util.spec_from_file_location("compose_env_filters", FILTER_PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


def synthetic_values(apps: list[dict]) -> dict:
    context: dict = {}
    for app in apps:
        for variable in (app["client_secret_var"], app["signing_certificate_var"]):
            *parents, leaf = variable.split(".")
            scope = context
            for parent in parents:
                scope = scope.setdefault(parent, {})
            scope[leaf] = f"synthetic-{leaf}"
    return context


class RenderedOidcBlueprint:
    """The generated blueprint as Authentik sees it after Ansible templating."""

    def __init__(self, mod, apps: list[dict]):
        environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
        environment.filters.update(credential_filters())
        rendered = environment.from_string(mod.generate_oidc_blueprint_content(apps)).render(
            synthetic_values(apps)
        )
        self.entries = yaml.load(rendered, Loader=BlueprintLoader)["entries"]

    def of_model(self, model: str) -> list[dict]:
        return [entry for entry in self.entries if entry["model"] == model]

    def application(self, slug: str) -> dict:
        (application,) = [
            entry for entry in self.of_model("authentik_core.application")
            if entry["attrs"]["slug"] == slug
        ]
        return application

    def provider(self, slug: str) -> dict:
        reference = self.application(slug)["attrs"]["provider"]
        (provider,) = [
            entry for entry in self.of_model("authentik_providers_oauth2.oauth2provider")
            if ("!KeyOf", entry["id"]) == reference
        ]
        return provider

    def bindings(self, slug: str, state: str) -> list[dict]:
        target = ("!KeyOf", self.application(slug)["id"])
        return [
            entry for entry in self.of_model("authentik_policies.policybinding")
            if entry["state"] == state and entry["identifiers"]["target"] == target
        ]

    def admission(self, slug: str) -> dict[int, tuple[str, str]]:
        """Map each enabled, non-negated binding's order to the group or policy it admits."""
        admitted = {}
        for binding in self.bindings(slug, "present"):
            attrs = binding["attrs"]
            if attrs["enabled"] and not attrs["negate"]:
                kind = "group" if "group" in attrs else "policy"
                _tag, (_model, (_field, name)) = attrs[kind]
                admitted[attrs["order"]] = (kind, name)
        return admitted


class OidcBlueprintGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_generation_is_deterministic(self):
        apps = [minimal_app()]
        self.assertEqual(
            self.mod.generate_oidc_blueprint_content(apps),
            self.mod.generate_oidc_blueprint_content(apps),
        )

    def test_application_is_served_by_a_provider_with_its_client_identity(self):
        redirect_uris = [
            "https://app.example.com/callback",
            "https://app.example.com/mobile-redirect",
        ]
        blueprint = RenderedOidcBlueprint(self.mod, [minimal_app(redirect_uris=redirect_uris)])

        application = blueprint.application("test-app")["attrs"]
        provider = blueprint.provider("test-app")["attrs"]

        self.assertEqual(application["launch_url"], "https://test.example.com")
        self.assertEqual(provider["name"], "test-app-oidc")
        self.assertEqual(provider["client_id"], "test-app")
        self.assertEqual(provider["client_type"], "confidential")
        self.assertEqual(
            provider["redirect_uris"],
            [{"matching_mode": "strict", "url": uri} for uri in redirect_uris],
        )

    def test_secret_and_signing_key_stay_template_expressions(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app()])
        provider = RenderedOidcBlueprint(self.mod, [minimal_app()]).provider("test-app")["attrs"]

        self.assertIn("{{ auth_test_oidc_client_secret | required_credential }}", content)
        self.assertIn("{{ auth_test_oidc_signing_cert | tojson }}", content)
        self.assertEqual(provider["client_secret"], "synthetic-auth_test_oidc_client_secret")
        self.assertEqual(
            provider["signing_key"],
            ("!Find", ["authentik_crypto.certificatekeypair", ["name", "synthetic-auth_test_oidc_signing_cert"]]),
        )

    def test_shared_scope_mapping_is_defined_once_and_bound_to_each_provider(self):
        mapping = {"name": "Email Verify", "scope_name": "email", "expression": "return {}"}
        blueprint = RenderedOidcBlueprint(self.mod, [
            minimal_app(custom_scope_mappings=[mapping]),
            minimal_app(slug="other-app", client_id="other", custom_scope_mappings=[mapping]),
        ])

        (scope,) = blueprint.of_model("authentik_providers_oauth2.scopemapping")
        self.assertEqual(scope["attrs"]["scope_name"], "email")
        for slug in ("test-app", "other-app"):
            with self.subTest(slug=slug):
                self.assertIn(
                    ("!KeyOf", scope["id"]),
                    blueprint.provider(slug)["attrs"]["property_mappings"],
                )

    def test_scope_mapping_description_is_emitted_only_when_declared(self):
        for description in ("Verified email claim", None):
            with self.subTest(description=description):
                mapping = {"name": "Email Verify", "scope_name": "email", "expression": "return {}"}
                if description is not None:
                    mapping["description"] = description
                blueprint = RenderedOidcBlueprint(self.mod, [minimal_app(custom_scope_mappings=[mapping])])

                (scope,) = blueprint.of_model("authentik_providers_oauth2.scopemapping")
                self.assertEqual(scope["attrs"].get("description"), description)

    def test_grant_types_are_managed_only_when_declared(self):
        # Providers created before Authentik 2026.5 were backfilled by migration;
        # omitting the key keeps the blueprint from narrowing their live grants.
        declared = RenderedOidcBlueprint(
            self.mod, [minimal_app(grant_types=["authorization_code", "refresh_token"])]
        ).provider("test-app")["attrs"]
        omitted = RenderedOidcBlueprint(self.mod, [minimal_app()]).provider("test-app")["attrs"]

        self.assertEqual(declared["grant_types"], ["authorization_code", "refresh_token"])
        self.assertNotIn("grant_types", omitted)

    def test_group_app_admits_its_group_and_admins_and_removes_the_permissive_binding(self):
        blueprint = RenderedOidcBlueprint(self.mod, [minimal_app(group="media")])

        self.assertEqual(
            blueprint.admission("test-app"),
            {1: ("group", "media"), 2: ("group", "admins")},
        )
        self.assertEqual(
            [binding["identifiers"]["order"] for binding in blueprint.bindings("test-app", "absent")],
            [0],
        )

    def test_policy_app_is_admitted_only_by_its_policy(self):
        blueprint = RenderedOidcBlueprint(self.mod, [minimal_app(policy="always-allow")])

        self.assertEqual(blueprint.admission("test-app"), {0: ("policy", "always-allow")})
        self.assertEqual(blueprint.bindings("test-app", "absent"), [])

    def test_real_manifest_validates_cleanly(self):
        self.mod.validate_oidc_manifest(self.mod.load_oidc_manifest())

    def test_real_manifest_apps_admit_only_their_group_and_admins(self):
        apps = self.mod.load_oidc_manifest()
        blueprint = RenderedOidcBlueprint(self.mod, apps)

        for app in apps:
            with self.subTest(slug=app["slug"]):
                self.assertEqual(
                    blueprint.admission(app["slug"]),
                    {1: ("group", app.get("group")), 2: ("group", "admins")},
                )

    def test_committed_oidc_blueprint_matches_generator(self):
        apps = self.mod.load_oidc_manifest()
        expected = self.mod.generate_oidc_blueprint_content(apps)
        actual = self.mod.OIDC_BLUEPRINT_FILE.read_text(encoding="utf-8")
        self.assertEqual(actual, expected)


class BlueprintPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_blueprints_deploy_from_their_files(self):
        plan = dict(self.mod.blueprint_plan([]))
        for name, path in (
            ("repo-auth-roles", "15-roles.yaml"),
            ("repo-auth-oidc-apps", "80-oidc-apps.yaml"),
            ("repo-auth-proxmox-oidc", "85-proxmox-oidc.yaml"),
            ("repo-auth-legacy-cleanup", "90-cleanup-legacy.yaml"),
        ):
            with self.subTest(name=name):
                self.assertEqual(plan.get(name), path)

    def test_blueprints_apply_after_what_they_reference(self):
        names = [name for name, _ in self.mod.blueprint_plan(["default-authentication-flow"])]
        for before, after in (
            ("repo-auth-groups", "repo-auth-roles"),
            ("repo-auth-roles", "repo-auth-flow-default-authentication-flow"),
            ("repo-auth-registration-approval-flow", "repo-auth-navidrome-password-change-sync"),
            ("repo-auth-navidrome-password-change-sync", "repo-auth-providers"),
            ("repo-auth-notifications", "repo-auth-proxmox-oidc"),
            ("repo-auth-proxmox-oidc", "repo-auth-providers"),
            ("repo-auth-outposts", "repo-auth-oidc-apps"),
            ("repo-auth-applications", "repo-auth-legacy-cleanup"),
            ("repo-auth-oidc-apps", "repo-auth-legacy-cleanup"),
        ):
            with self.subTest(before=before, after=after):
                self.assertIn(before, names)
                self.assertIn(after, names)
                self.assertLess(names.index(before), names.index(after))

    def test_proxmox_blueprint_uses_provider_specific_issuer_mode(self):
        content = (
            REPO_ROOT / "stacks/auth/auth/appdata/authentik/blueprints/85-proxmox-oidc.yaml.j2"
        ).read_text(encoding="utf-8")
        self.assertIn("issuer_mode: per_provider", content)
        self.assertNotIn("issuer_mode: global", content)


if __name__ == "__main__":
    unittest.main()
