#!/usr/bin/env python3
"""Focused contracts for Portal's route security and certificates."""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
TRAEFIK_STACK = REPO_ROOT / "stacks/portal/traefik3"


def load_yaml(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_representative_local_and_remote_routes_preserve_access_tiers() -> None:
    portal_entry = load_yaml(REPO_ROOT / "stacks/portal/portal-entry/compose.yaml")
    bazarr = load_yaml(REPO_ROOT / "stacks/servarr/bazarr/compose.yaml")
    jellyfin = load_yaml(REPO_ROOT / "stacks/jellyfin/jellyfin/compose.yaml")
    immich = load_yaml(REPO_ROOT / "stacks/public/immich/compose.override.yaml")

    portal_labels = portal_entry["services"]["portal-entry"]["labels"]
    bazarr_labels = bazarr["services"]["bazarr"]["labels"]
    jellyfin_labels = jellyfin["services"]["jellyfin"]["labels"]
    immich_labels = immich["services"]["immich-server"]["labels"]

    assert portal_labels["traefik.enable"] is True
    assert portal_labels["traefik.http.routers.portal-entry.rule"] == (
        "Host(`faviann.com`)"
    )
    assert portal_labels["traefik.http.routers.portal-entry.middlewares"] == (
        "protected-edge-auth@file"
    )
    assert bazarr_labels["traefik.enable"] is True
    assert bazarr_labels["traefik.http.routers.bazarr.middlewares"] == (
        "protected-edge-auth@file"
    )
    assert jellyfin_labels["traefik.enable"] is True
    assert not any("middlewares" in label for label in jellyfin_labels)
    assert immich_labels["traefik.enable"] is True
    assert not any("middlewares" in label for label in immich_labels)


def test_cloudflare_certificate_storage_is_one_coupled_contract() -> None:
    compose = load_yaml(TRAEFIK_STACK / "compose.yaml")
    static = load_yaml(
        TRAEFIK_STACK / "appdata/traefik3/config/traefik.yaml"
    )
    traefik = compose["services"]["traefik"]
    websecure_tls = static["entryPoints"]["websecure"]["http"]["tls"]

    assert websecure_tls["certResolver"] == "cloudflare"
    assert websecure_tls["domains"] == [
        {
            "main": "faviann.com",
            "sans": [
                "*.faviann.com",
                "*.admin.faviann.com",
                "*.home.faviann.com",
                "*.media.faviann.com",
                "*.public.faviann.com",
                "*.local.faviann.com",
            ],
        }
    ]
    assert (
        "./appdata/traefik3/data/certs/:/var/traefik/certs/:rw"
        in traefik["volumes"]
    )
    assert static["certificatesResolvers"]["cloudflare"]["acme"]["storage"] == (
        "/var/traefik/certs/cloudflare-acme.json"
    )
    assert compose["x-managed-files"] == [
        {
            "path": "./appdata/traefik3/data/certs/cloudflare-acme.json",
            "mode": "0600",
        }
    ]


def test_protected_edge_auth_chain_keeps_its_forward_auth_address() -> None:
    middleware = load_yaml(
        TRAEFIK_STACK
        / "appdata/traefik3/config/conf.d/middleware-authentik.yaml"
    )["http"]["middlewares"]

    assert middleware["protected-edge-auth"] == {
        "chain": {"middlewares": ["forwardAuth-authentik"]}
    }
    assert middleware["forwardAuth-authentik"]["forwardAuth"]["address"] == (
        "http://auth.faviann.vms:9000/outpost.goauthentik.io/auth/traefik"
    )
