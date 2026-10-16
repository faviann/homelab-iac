"""Broodling stack guarantees that its live check-target cannot see."""

from __future__ import annotations

import sys
from pathlib import Path

import jinja2
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK = REPO_ROOT / "stacks/broodling/broodling"
COMPOSE = yaml.safe_load((STACK / "compose.yaml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]

sys.path.insert(0, str(REPO_ROOT / "playbooks/filter_plugins"))
from compose_env import credential_is_configured  # noqa: E402


def test_only_broodling_and_the_tls_proxy_publish_and_neither_beyond_the_lxc() -> None:
    publications = {name: service["ports"] for name, service in SERVICES.items() if "ports" in service}
    rendered = jinja2.Template((STACK / ".env.j2").read_text(encoding="utf-8")).render(
        ansible_facts={"default_ipv4": {"address": "192.0.2.10"}},
        stack_vars={"broodling_image": "", "dotnet": {"image": ""}},
    )

    assert publications == {
        "broodling": ["${BROODLING_HTTP_BIND:?}:8080:8080"],
        "zeroshot-tls": ["127.0.0.1:443:443"],
    }
    assert "BROODLING_HTTP_BIND=192.0.2.10" in rendered.splitlines()


def test_dispatch_credentials_reach_only_broodling() -> None:
    env_files = {name: service["env_file"] for name, service in SERVICES.items() if "env_file" in service}

    assert env_files == {"broodling": "./broodling.env"}


def test_credential_files_have_their_recipients_owner_and_mode() -> None:
    managed = {entry["path"]: (entry.get("owner"), entry.get("group"), entry["mode"]) for entry in COMPOSE["x-managed-files"]}

    assert managed == {
        "./broodling.env": (None, None, "0600"),
        "./zeroshot-dotnet-control-token": ("1654", "1654", "0400"),
        "./zeroshot-dotnet-control-token.check": ("0", "0", "0400"),
        "./zeroshot-dotnet-bootstrap-key": ("0", "0", "0400"),
        "./zeroshot-dotnet-bootstrap-key.bootstrap": ("1654", "1654", "0400"),
    }
    # Native accepts exactly 64 hex characters, and Ansible keeps a template's
    # final newline in the rendered file.
    for path in managed:
        if path.startswith("./zeroshot-dotnet-"):
            assert not (STACK / f"{path}.j2").read_bytes().endswith(b"\n"), path


def test_no_service_mounts_the_docker_socket() -> None:
    socket_mounts = [
        (name, volume) for name, service in SERVICES.items()
        for volume in service.get("volumes", []) if "docker.sock" in str(volume)
    ]

    assert socket_mounts == []


def test_vault_example_holds_only_placeholders_for_broodling_credentials() -> None:
    example = yaml.safe_load((REPO_ROOT / "inventory/vault.yml.example").read_text(encoding="utf-8"))
    broodling = {key: value for key, value in example.items() if key.startswith("vault_broodling_")}

    assert sorted(broodling) == [
        "vault_broodling_dotnet_bootstrap_key",
        "vault_broodling_dotnet_control_token",
        "vault_broodling_gateway_api_key",
        "vault_broodling_github_token",
    ]
    assert [key for key, value in broodling.items() if credential_is_configured(value)] == []
