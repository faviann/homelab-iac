#!/usr/bin/env python3
"""Lobu-specific invariants that generic repository validation cannot cover.

Deliberately minimal. The real acceptance for this deployment is the end-to-end
ChatGPT -> MCP -> device path, not unit coverage, so this pins only the few
things that would break the deployment silently and are not checked elsewhere:
the pgvector requirement, the persistence and signup-lockout contract, the vault
bindings, and the public router's security boundary.
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
    def test_database_image_provides_pgvector_and_both_images_are_digest_pinned(self) -> None:
        services = load_yaml(STACK_ROOT / "compose.yaml")["services"]

        # Not an optional memory feature: the baseline schema migration declares
        # non-nullable vector columns, so a stock postgres image cannot migrate.
        self.assertTrue(
            services["postgres"]["image"].startswith("pgvector/pgvector:pg18-trixie@sha256:"),
        )
        self.assertTrue(
            services["lobu"]["image"].startswith("ghcr.io/lobu-ai/lobu-app:19.2.0@sha256:"),
        )

    def test_durable_state_and_signup_lockout(self) -> None:
        services = load_yaml(STACK_ROOT / "compose.yaml")["services"]

        # Lobu's durable state is exactly these two directories. Stack-relative
        # appdata lands on the shared volume's per-host subpath, so it survives
        # container and LXC recreation. The parent of PGDATA is mounted so
        # PostgreSQL 18 creates and owns the nested directory itself.
        self.assertIn("./appdata/postgres:/var/lib/postgresql", services["postgres"]["volumes"])
        self.assertIn("./appdata/workspaces:/app/workspaces", services["lobu"]["volumes"])
        self.assertEqual(services["lobu"]["environment"]["LOBU_SINGLE_USER"], "1")

    def test_secrets_resolve_from_the_vault_and_are_never_rendered_literally(self) -> None:
        stack_vars = load_yaml(REPO_ROOT / "inventory/host_vars/lobu.yml")[
            "lxc_docker_env_stack_vars"
        ]["lobu"]
        env_template = (STACK_ROOT / ".env.j2").read_text(encoding="utf-8")

        for variable, key, vault_name in (
            ("LOBU_ENCRYPTION_KEY", "encryption_key", "vault_lobu_encryption_key"),
            ("LOBU_BETTER_AUTH_SECRET", "better_auth_secret", "vault_lobu_better_auth_secret"),
            ("LOBU_POSTGRES_PASSWORD", "postgres_password", "vault_lobu_postgres_password"),
        ):
            self.assertEqual(stack_vars[key], "{{ %s }}" % vault_name)
            self.assertIn(
                f"{variable}={{{{ stack_vars.{key} | compose_env }}}}", env_template
            )
        self.assertNotIn("REPLACE_", env_template)

    def test_public_router_matches_the_gateway_origin_and_exposes_no_namespace(self) -> None:
        host_vars = load_yaml(REPO_ROOT / "inventory/host_vars/lobu.yml")
        http = load_yaml(TRAEFIK_CONF)["http"]
        router = http["routers"]["lobu"]

        # PUBLIC_GATEWAY_URL must equal the origin clients actually see, or the
        # MCP origin-trust middleware rejects requests opaquely.
        self.assertEqual(host_vars["lobu_public_gateway_url"], PUBLIC_ORIGIN)
        self.assertIn("Host(`lobu.faviann.com`)", router["rule"])
        self.assertEqual(
            http["services"]["lobu"]["loadBalancer"]["servers"],
            [{"url": "http://lobu.faviann.vms:8787"}],
        )

        # No ForwardAuth: ChatGPT's connector onboarding needs unauthenticated
        # dynamic client registration and Lobu is its own authorization server.
        self.assertNotIn("middlewares", router)
        # Better Auth also serves organization management, member removal,
        # password change and session revocation under /api/auth. Only named
        # endpoints may be public, so signup stays unreachable and a new
        # upstream endpoint is never published by default.
        self.assertNotIn("PathPrefix(`/api/auth", router["rule"])
        self.assertNotIn("sign-up", router["rule"])
        for required in (
            "Path(`/mcp`)",
            "Path(`/oauth/register`)",
            "PathPrefix(`/api/workers/`)",
        ):
            self.assertIn(required, router["rule"])


if __name__ == "__main__":
    unittest.main()
