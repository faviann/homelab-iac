#!/usr/bin/env python3
"""The two homelab-owned boundaries for the Lobu control plane.

Everything else about this deployment is proven behaviourally — migrations and
health at deploy time, the live second-signup gate, and the public OAuth/MCP
smoke. What is left here is only what a regression could break while leaving
Lobu apparently healthy: losing durable storage, and silently widening the
public surface.
"""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
LOBU_COMPOSE = REPO_ROOT / "stacks/lobu/lobu/compose.yaml"
TRAEFIK_CONF = REPO_ROOT / (
    "stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml"
)


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_lobu_declares_persistent_storage_and_single_user_mode() -> None:
    """Declarative configuration invariant, not a behavioural check.

    Dropping either mount leaves Lobu healthy while making its state ephemeral,
    and dropping LOBU_SINGLE_USER removes an intentional security property
    without otherwise breaking the app. Whether signup is actually refused is
    proven by the live gate, not here.
    """
    services = load_yaml(LOBU_COMPOSE)["services"]

    assert "./appdata/postgres:/var/lib/postgresql" in services["postgres"]["volumes"]
    assert "./appdata/workspaces:/app/workspaces" in services["lobu"]["volumes"]
    assert services["lobu"]["environment"]["LOBU_SINGLE_USER"] == "1"


def test_lobu_public_router_keeps_its_negative_exposure_boundaries() -> None:
    """The router is deliberately unusual: no edge auth, endpoint-enumerated.

    Each assertion here is a failure that would broaden the public surface
    quietly rather than break the integration visibly.
    """
    router = load_yaml(TRAEFIK_CONF)["http"]["routers"]["lobu"]
    rule = router["rule"]

    # Better Auth also serves organization management, member removal, password
    # change and session revocation under /api/auth.
    assert "PathPrefix(`/api/auth" not in rule
    assert "sign-up" not in rule
    # /oauth is enumerated endpoint by endpoint on purpose.
    assert "PathPrefix(`/oauth" not in rule
    # ForwardAuth in front of the protocol endpoints would break MCP and OAuth,
    # so its absence is intentional and must stay deliberate.
    assert "middlewares" not in router
