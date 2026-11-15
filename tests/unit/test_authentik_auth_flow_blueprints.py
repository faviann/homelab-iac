#!/usr/bin/env python3
"""Unit tests for repo-managed Authentik authentication flow blueprints."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import jinja2
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUTH_POLICIES_FILE = (
    REPO_ROOT
    / "stacks"
    / "auth"
    / "auth"
    / "appdata"
    / "authentik"
    / "blueprints"
    / "25-default-auth-policies.yaml"
)
SOCIAL_LOGIN_TEMPLATE_FILE = DEFAULT_AUTH_POLICIES_FILE.with_name("28-social-login.yaml.j2")
FILTER_PLUGIN_PATH = REPO_ROOT / "playbooks" / "filter_plugins" / "compose_env.py"


class BlueprintLoader(yaml.SafeLoader):
    pass


def _construct_find(loader: BlueprintLoader, node: yaml.Node) -> tuple:
    return ("!Find", tuple(loader.construct_sequence(node, deep=True)))


def _construct_keyof(loader: BlueprintLoader, node: yaml.Node) -> tuple:
    return ("!KeyOf", loader.construct_scalar(node))


BlueprintLoader.add_constructor("!Find", _construct_find)
BlueprintLoader.add_constructor("!KeyOf", _construct_keyof)


def load_default_auth_policies() -> dict:
    return yaml.load(DEFAULT_AUTH_POLICIES_FILE.read_text(encoding="utf-8"), Loader=BlueprintLoader)


def find_ref(model: str, field: str, value: str) -> tuple:
    return ("!Find", (model, [field, value]))


class DefaultAuthPoliciesBlueprintTests(unittest.TestCase):
    def test_passwordless_flow_replaces_identification_with_user_login(self):
        blueprint = load_default_auth_policies()
        entries = blueprint["entries"]
        passwordless_flow = find_ref("authentik_flows.flow", "slug", "default-passwordless-flow")
        identification_stage = find_ref(
            "authentik_stages_identification.identificationstage",
            "name",
            "default-authentication-identification",
        )
        login_stage = find_ref(
            "authentik_stages_user_login.userloginstage",
            "name",
            "default-authentication-login",
        )

        stale_identification_bindings = [
            entry for entry in entries
            if entry.get("model") == "authentik_flows.flowstagebinding"
            and entry.get("state") == "absent"
            and entry.get("identifiers") == {
                "target": passwordless_flow,
                "stage": identification_stage,
                "order": 20,
            }
        ]
        replacement_login_bindings = [
            entry for entry in entries
            if entry.get("model") == "authentik_flows.flowstagebinding"
            and entry.get("state") == "present"
            and entry.get("identifiers") == {
                "target": passwordless_flow,
                "stage": login_stage,
                "order": 20,
            }
        ]

        self.assertEqual(len(stale_identification_bindings), 0)
        self.assertEqual(len(replacement_login_bindings), 1)


def render_social_login(**stack_vars: str) -> list[dict]:
    spec = importlib.util.spec_from_file_location("compose_env_filters", FILTER_PLUGIN_PATH)
    filters = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(filters)
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    environment.filters.update(filters.FilterModule().filters())
    template = environment.from_string(SOCIAL_LOGIN_TEMPLATE_FILE.read_text(encoding="utf-8"))
    rendered = template.render(stack_vars=stack_vars)
    return yaml.load(rendered, Loader=BlueprintLoader)["entries"]


class SocialLoginBlueprintTests(unittest.TestCase):
    REQUIRED = {
        "discord_source_client_id": "discord-id",
        "discord_source_client_secret": "discord-secret",
        "google_source_client_id": "google-id",
        "google_source_client_secret": "google-secret",
    }

    def login_page(self, entries: list[dict]) -> tuple[dict[str, dict], list[str]]:
        sources = {
            entry["attrs"]["slug"]: entry
            for entry in entries
            if entry["model"] == "authentik_sources_oauth.oauthsource"
        }
        (stage,) = [
            entry for entry in entries
            if entry["model"] == "authentik_stages_identification.identificationstage"
        ]
        ids = {entry["id"]: slug for slug, entry in sources.items()}
        return sources, [ids[ref] for _tag, ref in stage["attrs"]["sources"]]

    def test_login_page_shows_every_deployed_source(self):
        sources, shown = self.login_page(render_social_login(**self.REQUIRED))
        self.assertEqual(sorted(sources), ["discord", "google"])
        self.assertEqual(sorted(shown), ["discord", "google"])


if __name__ == "__main__":
    unittest.main()
