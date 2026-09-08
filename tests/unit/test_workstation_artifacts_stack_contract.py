#!/usr/bin/env python3
"""Repository contract tests for the workstation artifact static server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_ROOT = REPO_ROOT / "stacks" / "workstation" / "artifacts"
WORKSTATION_VARS_PATH = REPO_ROOT / "inventory" / "host_vars" / "workstation.yml"
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

PUBLICATION_ROOT = "/ephemeral/workstation/artifacts"
ORIGIN_PORT = 19082


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_env_template(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )


def test_stack_runs_only_the_pinned_static_web_server() -> None:
    compose = load_yaml(STACK_ROOT / "compose.yaml")

    assert set(compose["services"]) == {"artifacts"}
    assert (
        compose["services"]["artifacts"]["image"]
        == "ghcr.io/static-web-server/static-web-server:2.44.0"
    )


def test_server_reads_only_the_publication_root_as_the_publishing_user() -> None:
    compose = load_yaml(STACK_ROOT / "compose.yaml")
    server = compose["services"]["artifacts"]

    assert compose["x-prereq-dirs"] == [PUBLICATION_ROOT]
    assert server["volumes"] == [f"{PUBLICATION_ROOT}:/srv/artifacts:ro"]
    assert server["user"] == "${PUID}:${PGID}"
    assert server["read_only"] is True


def test_server_listens_on_the_firewalled_host_port() -> None:
    compose = load_yaml(STACK_ROOT / "compose.yaml")
    server = compose["services"]["artifacts"]
    env = load_env_template(STACK_ROOT / ".env.j2")

    assert server["network_mode"] == "host"
    assert "ports" not in server
    assert server["env_file"] == [".env"]
    assert server["restart"] == "unless-stopped"
    assert env["SERVER_PORT"] == str(ORIGIN_PORT)
    assert ORIGIN_PORT in load_yaml(WORKSTATION_VARS_PATH)[
        "workstation_origin_firewall_protected_ports"
    ]


def test_server_environment_serves_the_tree_without_listing_or_fallback() -> None:
    env = load_env_template(STACK_ROOT / ".env.j2")

    assert env == {
        "PUID": "{{ docker_uid }}",
        "PGID": "{{ docker_gid }}",
        "SERVER_HOST": "0.0.0.0",
        "SERVER_PORT": "19082",
        "SERVER_ROOT": "/srv/artifacts",
        "SERVER_DIRECTORY_LISTING": "false",
        "SERVER_DISABLE_SYMLINKS": "true",
        "SERVER_IGNORE_HIDDEN_FILES": "false",
        "SERVER_LOG_LEVEL": "info",
    }


def test_origin_port_is_reserved_only_for_the_artifact_server() -> None:
    configured_paths = {
        path.relative_to(REPO_ROOT)
        for root in (REPO_ROOT / "inventory", REPO_ROOT / "stacks")
        for path in root.rglob("*")
        if path.is_file()
        and str(ORIGIN_PORT)
        in path.read_text(encoding="utf-8", errors="ignore")
    }

    assert configured_paths == {
        Path("inventory/host_vars/workstation.yml"),
        Path("stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml"),
        Path("stacks/workstation/artifacts/.env.j2"),
        Path("stacks/workstation/artifacts/README.md"),
    }


def test_server_image_has_an_intentional_update_track() -> None:
    metadata = load_yaml(STACK_ROOT / "stack.yaml")

    assert metadata["updates"] == {"mode": "images", "track": "2"}
    assert metadata["exposure"]["traefik"] == "protected"
    assert metadata["runtime"]["host_requirements"]["host_directories"] == [
        PUBLICATION_ROOT
    ]


def test_publication_root_is_not_a_persistent_home_mapping() -> None:
    defaults = load_yaml(
        REPO_ROOT
        / "playbooks"
        / "roles"
        / "config"
        / "lxc_workstation_baseline"
        / "defaults"
        / "main.yml"
    )
    targets = {
        link["target"] for link in defaults["workstation_persistent_home_links"]
    }

    assert not any(target.startswith(PUBLICATION_ROOT) for target in targets)


def test_stack_readme_records_the_shared_publishing_mapping() -> None:
    readme = (STACK_ROOT / "README.md").read_text(encoding="utf-8")

    assert PUBLICATION_ROOT in readme
    assert "https://artifacts.admin.faviann.com" in readme
    assert "dotfiles" in readme
