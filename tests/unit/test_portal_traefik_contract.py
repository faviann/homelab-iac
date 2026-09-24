#!/usr/bin/env python3
"""Focused contracts for Portal's route security and certificates."""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
TRAEFIK_STACK = REPO_ROOT / "stacks/portal/traefik3"


def load_yaml(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_docker_provider_uses_the_read_only_socket_proxy() -> None:
    compose = load_yaml(TRAEFIK_STACK / "compose.yaml")
    static = load_yaml(
        TRAEFIK_STACK / "appdata/traefik3/config/traefik.yaml"
    )
    services = compose["services"]
    proxy = services["traefik-docker-socket-proxy"]
    traefik = services["traefik"]
    docker_provider = static["providers"]["docker"]

    assert docker_provider["endpoint"] == (
        "tcp://traefik-docker-socket-proxy:2375"
    )
    assert docker_provider["exposedByDefault"] is False
    assert "traefik" in proxy["networks"]
    assert "traefik" in traefik["networks"]
    assert "/run/docker.sock:/var/run/docker.sock:ro" in proxy["volumes"]
    assert not any("docker.sock" in volume for volume in traefik["volumes"])


def test_traefik_restart_waits_for_healthy_redis() -> None:
    compose = load_yaml(TRAEFIK_STACK / "compose.yaml")
    services = compose["services"]
    redis_dependency = services["traefik"]["depends_on"]["redis"]

    assert services["redis"]["healthcheck"]["test"] == [
        "CMD",
        "redis-cli",
        "ping",
    ]
    assert redis_dependency["condition"] == "service_healthy"
    assert redis_dependency["restart"] is True


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
    assert (
        "./appdata/traefik3/data/certs/:/var/traefik/certs/:rw"
        in traefik["volumes"]
    )
    assert static["certificatesResolvers"]["cloudflare"]["acme"]["storage"] == (
        "/var/traefik/certs/cloudflare-acme.json"
    )
    assert {
        "path": "./appdata/traefik3/data/certs/cloudflare-acme.json",
        "mode": "0600",
    } in compose["x-managed-files"]


def test_wildcard_certificate_covers_every_access_tier() -> None:
    # Each tier domain serves routes under a single wildcard; dropping one
    # breaks TLS for that tier. Extra names are harmless.
    static = load_yaml(
        TRAEFIK_STACK / "appdata/traefik3/config/traefik.yaml"
    )
    (certificate,) = static["entryPoints"]["websecure"]["http"]["tls"]["domains"]

    assert certificate["main"] == "faviann.com"
    assert {
        "*.faviann.com",
        "*.admin.faviann.com",
        "*.home.faviann.com",
        "*.media.faviann.com",
        "*.public.faviann.com",
        "*.local.faviann.com",
    } <= set(certificate["sans"])


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
