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


def test_proxmox_spice_proxy_is_a_local_only_raw_tcp_forward() -> None:
    compose = load_yaml(TRAEFIK_STACK / "compose.yaml")
    static = load_yaml(
        TRAEFIK_STACK / "appdata/traefik3/config/traefik.yaml"
    )
    dynamic = load_yaml(
        TRAEFIK_STACK / "appdata/traefik3/config/conf.d/externalservice.yaml"
    )
    tcp = dynamic["tcp"]
    router = tcp["routers"]["proxmox-spice"]
    servers = tcp["services"][router["service"]]["loadBalancer"]["servers"]

    assert "3128:3128/tcp" in compose["services"]["traefik"]["ports"]
    assert static["entryPoints"]["spice"]["address"] == ":3128/tcp"
    # A catch-all TCP router on websecure would take over HTTPS, so spice must
    # be its only entrypoint.
    assert router["entryPoints"] == ["spice"]
    # Remote Viewer opens a plaintext HTTP CONNECT to spiceproxy and runs SPICE
    # TLS inside that tunnel. Only HostSNI(`*`) matches a non-TLS connection,
    # and any tls block would terminate or pass through TLS.
    assert router["rule"] == "HostSNI(`*`)"
    assert "tls" not in router
    assert router["service"] == "proxmox-spice"
    assert "local-ip-restriction" in router["middlewares"]
    assert [server["address"] for server in servers] == ["proxmox.lan:3128"]
    assert set(
        tcp["middlewares"]["local-ip-restriction"]["ipAllowList"]["sourceRange"]
    ) == set(
        dynamic["http"]["middlewares"]["local-ip-restriction"]["IPAllowList"][
            "sourceRange"
        ]
    )
