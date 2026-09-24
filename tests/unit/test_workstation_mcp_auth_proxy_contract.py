#!/usr/bin/env python3
"""Repository contract tests for the workstation MCP auth proxy."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_ROOT = REPO_ROOT / "stacks" / "workstation" / "mcp-auth-proxy"
WORKSTATION_VARS_PATH = REPO_ROOT / "inventory" / "host_vars" / "workstation.yml"
PORTAL_VARS_PATH = REPO_ROOT / "inventory" / "host_vars" / "portal.yml"
AUTH_VARS_PATH = REPO_ROOT / "inventory" / "host_vars" / "auth.yml"
VAULT_EXAMPLE_PATH = REPO_ROOT / "inventory" / "vault.yml.example"
OIDC_MANIFEST_PATH = REPO_ROOT / "stacks" / "auth" / "auth" / "appdata" / "authentik" / "oidc-apps.yaml"
TRAEFIK_CONFIG_PATH = (
    REPO_ROOT
    / "stacks"
    / "portal"
    / "traefik3"
    / "appdata"
    / "traefik3"
    / "config"
    / "conf.d"
    / "externalservice.yaml"
)
VAULT_BINDING = re.compile(r"\{\{ (vault_\w+) \}\}")


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_env_template(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )


def proxy_env() -> dict[str, str]:
    return load_env_template(STACK_ROOT / ".env.j2")


def listener_port() -> int:
    return int(proxy_env()["LISTEN"].removeprefix(":"))


def authentik_app_for_proxy() -> dict[str, Any]:
    client_id = proxy_env()["OIDC_CLIENT_ID"]
    (app,) = [
        app for app in load_yaml(OIDC_MANIFEST_PATH)["apps"] if app["client_id"] == client_id
    ]
    return app


def vault_variable(binding: str) -> str:
    match = VAULT_BINDING.fullmatch(binding)
    assert match, f"{binding!r} is not a direct vault binding"
    return match.group(1)


def traefik_rule_selects_path(rule: str, path: str) -> bool:
    exact_paths = re.findall(r"Path\(`([^`]+)`\)", rule)
    prefixes = re.findall(r"PathPrefix\(`([^`]+)`\)", rule)
    return path in exact_paths or any(path.startswith(prefix) for prefix in prefixes)


def test_stack_runs_only_the_sigbit_proxy_on_its_declared_track() -> None:
    compose = load_yaml(STACK_ROOT / "compose.yaml")
    track = load_yaml(STACK_ROOT / "stack.yaml")["updates"]["track"]

    assert set(compose["services"]) == {"mcp-auth-proxy"}
    repository, tag = compose["services"]["mcp-auth-proxy"]["image"].rsplit(":", 1)
    assert repository == "ghcr.io/sigbit/mcp-auth-proxy"
    assert tag.removeprefix("v").split(".")[:2] == track.split(".")


def test_proxy_image_has_an_intentional_update_track() -> None:
    metadata = load_yaml(STACK_ROOT / "stack.yaml")

    assert metadata["updates"] == {"mode": "images", "track": "2.10"}


def test_proxy_reaches_the_loopback_backend_without_rewriting_paths() -> None:
    compose = load_yaml(STACK_ROOT / "compose.yaml")
    proxy = compose["services"]["mcp-auth-proxy"]

    assert proxy["network_mode"] == "host"
    assert proxy["command"] == ["http://127.0.0.1:8080"]
    assert "ports" not in proxy


def test_local_oauth_repository_is_persistent() -> None:
    compose = load_yaml(STACK_ROOT / "compose.yaml")
    proxy = compose["services"]["mcp-auth-proxy"]
    env = proxy_env()

    assert compose["x-prereq-dirs"] == ["./appdata/data"]
    assert proxy["volumes"] == [f"./appdata/data:{env['DATA_PATH']}"]
    assert env["REPOSITORY_BACKEND"] == "local"


def test_compose_loads_the_rendered_environment() -> None:
    compose = load_yaml(STACK_ROOT / "compose.yaml")
    proxy = compose["services"]["mcp-auth-proxy"]

    assert proxy["env_file"] == [".env"]
    assert proxy["restart"] == "unless-stopped"


def test_proxy_environment_keeps_its_protections() -> None:
    env = proxy_env()

    assert {
        "NO_AUTO_TLS": "true",
        "PROXY_FORWARD_AUTHORIZATION": "false",
        "TRUSTED_PROXIES": "{{ stack_vars.trusted_proxies }}",
        "OIDC_CLIENT_SECRET": "{{ stack_vars.oidc_client_secret | compose_env }}",
        "AUTH_HMAC_SECRET": "{{ stack_vars.auth_hmac_secret | compose_env }}",
        "JWT_PRIVATE_KEY": "'{{ stack_vars.jwt_private_key | compose_env }}'",
    }.items() <= env.items()


def test_authentik_client_matches_the_proxy_configuration() -> None:
    env = proxy_env()
    app = authentik_app_for_proxy()
    # The generator binds the managed openid and profile mappings to every provider.
    supplied_scopes = {"openid", "profile"} | {
        mapping["scope_name"] for mapping in app.get("custom_scope_mappings", [])
    }
    requested_scopes = set(env["OIDC_SCOPES"].split(","))

    assert env["OIDC_CONFIGURATION_URL"] == (
        f"https://auth.faviann.com/application/o/{app['slug']}/.well-known/openid-configuration"
    )
    assert app["issuer_mode"] == "per_provider"
    assert app["redirect_uris"] == [f"{env['EXTERNAL_URL']}/.auth/oidc/callback"]
    # The OIDC flow needs openid, and sigbit resolves the user via the userinfo `/email` pointer.
    assert {"openid", "email"} <= requested_scopes
    assert requested_scopes <= supplied_scopes
    assert app["sub_mode"] == "user_email"
    # Authentik >= 2026.5 rejects any grant absent from the provider's list,
    # and sigbit only ever performs the upstream authorization-code exchange.
    assert app["grant_types"] == ["authorization_code"]
    assert app["group"] == "admins"


def test_both_sides_bind_the_same_client_secret() -> None:
    app = authentik_app_for_proxy()
    auth_stack_vars = load_yaml(AUTH_VARS_PATH)["lxc_docker_env_stack_vars"]["auth"]
    proxy_stack_vars = load_yaml(WORKSTATION_VARS_PATH)["lxc_docker_env_stack_vars"]["mcp-auth-proxy"]

    assert app["client_secret_var"].startswith("stack_vars.")
    authentik_secret = auth_stack_vars[app["client_secret_var"].removeprefix("stack_vars.")]
    assert vault_variable(authentik_secret) == vault_variable(proxy_stack_vars["oidc_client_secret"])


def test_proxy_secrets_and_trusted_source_have_render_bindings() -> None:
    workstation_vars = load_yaml(WORKSTATION_VARS_PATH)
    proxy_stack_vars = workstation_vars["lxc_docker_env_stack_vars"]["mcp-auth-proxy"]
    portal_source = ipaddress.ip_network(load_yaml(PORTAL_VARS_PATH)["portal_traefik_source_cidr"])
    vault_example = load_yaml(VAULT_EXAMPLE_PATH)

    for name in ("oidc_client_secret", "auth_hmac_secret", "jwt_private_key"):
        assert vault_variable(proxy_stack_vars[name]) in vault_example
    assert proxy_stack_vars["trusted_proxies"] == "{{ hostvars['portal'].portal_traefik_source_cidr }}"
    assert portal_source.prefixlen == portal_source.max_prefixlen
    assert workstation_vars["workstation_origin_firewall_allowed_hosts"] == ["portal"]


def test_public_router_selects_only_mcp_and_proxy_oauth_paths() -> None:
    env = proxy_env()
    host = urlparse(env["EXTERNAL_URL"]).hostname
    callback_path = urlparse(authentik_app_for_proxy()["redirect_uris"][0]).path
    config = load_yaml(TRAEFIK_CONFIG_PATH)
    matching_routers = [
        name
        for name, router in config["http"]["routers"].items()
        if host in router["rule"]
    ]
    rule = config["http"]["routers"]["mcp-auth-proxy"]["rule"]

    assert matching_routers == ["mcp-auth-proxy"]
    assert f"Host(`{host}`)" in rule
    assert "/.well-known/oauth-protected-resource/mcp" not in rule
    assert all(
        traefik_rule_selects_path(rule, path)
        for path in (
            "/mcp",
            "/.well-known/oauth-protected-resource",
            "/.idp/register",
            callback_path,
        )
    )
    assert not any(
        traefik_rule_selects_path(rule, path)
        for path in ("/", "/mcp/extra", "/api/v1/capabilities", "/api/v1/status")
    )


def test_public_router_preserves_paths_and_uses_the_firewalled_listener() -> None:
    config = load_yaml(TRAEFIK_CONFIG_PATH)
    router = config["http"]["routers"]["mcp-auth-proxy"]
    load_balancer = config["http"]["services"][router["service"]]["loadBalancer"]

    assert "middlewares" not in router
    assert router["priority"] == 1000
    assert load_balancer["servers"] == [
        {"url": f"http://workstation.faviann.vms:{listener_port()}"}
    ]
    assert load_balancer.get("passHostHeader", True) is True


def test_listener_port_is_consistent_and_reserved_only_for_the_proxy() -> None:
    port = listener_port()
    workstation_vars = load_yaml(WORKSTATION_VARS_PATH)

    assert port in workstation_vars["workstation_origin_firewall_protected_ports"]

    configured_paths = {
        path.relative_to(REPO_ROOT)
        for root in (REPO_ROOT / "inventory", REPO_ROOT / "stacks")
        for path in root.rglob("*")
        if path.is_file() and str(port) in path.read_text(encoding="utf-8", errors="ignore")
    }
    assert configured_paths == {
        Path("inventory/host_vars/workstation.yml"),
        Path("stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml"),
        Path("stacks/workstation/mcp-auth-proxy/.env.j2"),
    }
