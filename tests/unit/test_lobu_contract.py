#!/usr/bin/env python3
"""Lobu-specific wiring assertions that generic stack validation cannot cover.

Deliberately small: the real acceptance for this deployment is the end-to-end
ChatGPT -> MCP -> device path, not unit coverage. What is pinned here is only
what would silently break the deployment and not be caught elsewhere — the
digest pins, the vault bindings, and the absence of rendered secrets.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_ROOT = REPO_ROOT / "stacks/lobu/lobu"
TRAEFIK_CONF = REPO_ROOT / (
    "stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml"
)
PUBLIC_ORIGIN = "https://lobu.faviann.com"


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class LobuContractTests(unittest.TestCase):
    def test_inventory_places_lobu_in_the_declared_groups(self) -> None:
        children = load_yaml(REPO_ROOT / "inventory/hosts.yml")["all"]["children"]
        host_vars = load_yaml(REPO_ROOT / "inventory/host_vars/lobu.yml")
        overrides = host_vars["proxmox_lxc_overrides"]

        self.assertIn("lobu", children["tier_medium"]["hosts"])
        self.assertIn("lobu", children["cap_docker"]["hosts"])
        self.assertNotIn("lobu", children["cap_gpu"]["hosts"])
        self.assertNotIn("lobu", children["cap_wireguard"]["hosts"])
        self.assertEqual(host_vars["lxc_hwaddr"], "BC:24:11:14:5B:9C")
        self.assertEqual(overrides["vmid"], 308)
        self.assertEqual(overrides["hostname"], "lobu")
        # Root disk is the only tier override; cores and memory take tier defaults.
        self.assertEqual(overrides["disk"], "16")
        self.assertNotIn("cores", overrides)
        self.assertNotIn("memory", overrides)
        # ansible_host must stay derived from lxc_dns_domain, never pinned here.
        self.assertNotIn("ansible_host", host_vars)

    def test_images_are_pinned_by_version_and_digest(self) -> None:
        services = load_yaml(STACK_ROOT / "compose.yaml")["services"]

        self.assertTrue(
            services["postgres"]["image"].startswith("pgvector/pgvector:pg18-trixie@sha256:"),
            "the baseline schema migration declares non-nullable vector columns",
        )
        self.assertTrue(
            services["lobu"]["image"].startswith("ghcr.io/lobu-ai/lobu-app:19.2.0@sha256:"),
        )

    def test_durable_state_and_boot_environment(self) -> None:
        compose = load_yaml(STACK_ROOT / "compose.yaml")
        services = compose["services"]
        environment = services["lobu"]["environment"]

        # Stack-relative appdata: /conf/docker is a per-host subpath of the
        # shared volume, so this survives LXC recreation. The parent of PGDATA
        # is mounted so PostgreSQL 18 owns the nested directory itself.
        self.assertIn("./appdata/postgres:/var/lib/postgresql", services["postgres"]["volumes"])
        self.assertIn("./appdata/workspaces:/app/workspaces", services["lobu"]["volumes"])
        self.assertEqual(
            sorted(compose["x-prereq-dirs"]),
            ["./appdata/postgres", "./appdata/workspaces"],
        )
        self.assertEqual(
            services["lobu"]["depends_on"]["postgres"]["condition"], "service_healthy"
        )
        self.assertEqual(environment["LOBU_SINGLE_USER"], "1")
        self.assertEqual(environment["NODE_ENV"], "production")
        # Unset on purpose: one hostname/certificate, and deny-all worker egress.
        self.assertNotIn("AUTH_COOKIE_DOMAIN", environment)
        self.assertNotIn("WORKER_ALLOWED_DOMAINS", environment)

    def test_secrets_resolve_from_the_vault_and_are_never_rendered_literally(self) -> None:
        host_vars = load_yaml(REPO_ROOT / "inventory/host_vars/lobu.yml")
        stack_vars = host_vars["lxc_docker_env_stack_vars"]["lobu"]
        env_template = (STACK_ROOT / ".env.j2").read_text(encoding="utf-8")
        vault_example = load_yaml(REPO_ROOT / "inventory/group_vars/all/vault.yml.example")

        self.assertEqual(stack_vars["encryption_key"], "{{ vault_lobu_encryption_key }}")
        self.assertEqual(stack_vars["better_auth_secret"], "{{ vault_lobu_better_auth_secret }}")
        self.assertEqual(stack_vars["postgres_password"], "{{ vault_lobu_postgres_password }}")
        for name in (
            "vault_lobu_encryption_key",
            "vault_lobu_better_auth_secret",
            "vault_lobu_postgres_password",
        ):
            self.assertIn(name, vault_example)
            self.assertTrue(str(vault_example[name]).startswith("REPLACE_WITH_"))
        for variable, source in (
            ("LOBU_ENCRYPTION_KEY", "encryption_key"),
            ("LOBU_BETTER_AUTH_SECRET", "better_auth_secret"),
            ("LOBU_POSTGRES_PASSWORD", "postgres_password"),
        ):
            self.assertIn(
                f"{variable}={{{{ stack_vars.{source} | compose_env }}}}", env_template
            )
        self.assertNotIn("REPLACE_", env_template)

    def test_public_origin_is_one_canonical_bare_value(self) -> None:
        host_vars = load_yaml(REPO_ROOT / "inventory/host_vars/lobu.yml")
        routers = load_yaml(TRAEFIK_CONF)["http"]["routers"]
        services = load_yaml(TRAEFIK_CONF)["http"]["services"]

        # PUBLIC_GATEWAY_URL must equal the origin clients actually see, or the
        # MCP origin-trust middleware rejects requests opaquely.
        self.assertEqual(host_vars["lobu_public_gateway_url"], PUBLIC_ORIGIN)
        self.assertIn("Host(`lobu.faviann.com`)", routers["lobu"]["rule"])
        self.assertEqual(
            services["lobu"]["loadBalancer"]["servers"],
            [{"url": "http://lobu.faviann.vms:8787"}],
        )

    def test_public_router_admits_only_the_observed_protocol_surface(self) -> None:
        routers = load_yaml(TRAEFIK_CONF)["http"]["routers"]
        rule = routers["lobu"]["rule"]

        # No ForwardAuth/Authentik in front: ChatGPT's connector onboarding needs
        # unauthenticated dynamic client registration, and Lobu is its own
        # authorization server.
        self.assertNotIn("middlewares", routers["lobu"])
        for fragment in (
            "PathPrefix(`/mcp`)",
            "PathPrefix(`/.well-known/oauth-protected-resource`)",
            "Path(`/.well-known/oauth-authorization-server`)",
            "PathPrefix(`/oauth/`)",
            "PathPrefix(`/api/workers/`)",
            "PathPrefix(`/api/me/devices`)",
            "Path(`/auth/login`)",
            "PathPrefix(`/api/auth/`)",
        ):
            self.assertIn(fragment, rule)
        # The admin SPA and the workspace API stay off the public origin.
        self.assertNotIn("PathPrefix(`/api/`)", rule)

        signup = routers["lobu-signup-denied"]
        self.assertEqual(signup["service"], "noop")
        self.assertIn("PathPrefix(`/api/auth/sign-up`)", signup["rule"])
        self.assertGreater(signup["priority"], routers["lobu"]["priority"])


if __name__ == "__main__":
    unittest.main()
