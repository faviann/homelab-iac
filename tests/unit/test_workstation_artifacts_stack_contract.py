#!/usr/bin/env python3
"""Repository contract tests for the workstation artifact static server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_ROOT = REPO_ROOT / "stacks" / "workstation" / "artifacts"
WORKSTATION_VARS_PATH = REPO_ROOT / "inventory" / "host_vars" / "workstation.yml"
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


def test_stack_runs_only_the_static_web_server() -> None:
    compose = load_yaml(STACK_ROOT / "compose.yaml")

    # The SERVER_* environment contract below belongs to this server.
    assert set(compose["services"]) == {"artifacts"}
    assert compose["services"]["artifacts"]["image"].startswith(
        "ghcr.io/static-web-server/static-web-server:"
    )


def test_server_reads_only_the_publication_root_as_the_publishing_user() -> None:
    compose = load_yaml(STACK_ROOT / "compose.yaml")
    server = compose["services"]["artifacts"]
    env = load_env_template(STACK_ROOT / ".env.j2")

    assert compose["x-prereq-dirs"] == [PUBLICATION_ROOT]
    assert server["volumes"] == [f"{PUBLICATION_ROOT}:/srv/artifacts:ro"]
    assert env["SERVER_ROOT"] == "/srv/artifacts"
    assert server["user"] == "${PUID}:${PGID}"
    assert env["PUID"] == "{{ docker_uid }}"
    assert env["PGID"] == "{{ docker_gid }}"
    assert server["read_only"] is True


def test_server_listens_on_the_firewalled_host_port() -> None:
    compose = load_yaml(STACK_ROOT / "compose.yaml")
    server = compose["services"]["artifacts"]
    env = load_env_template(STACK_ROOT / ".env.j2")

    assert server["network_mode"] == "host"
    assert "ports" not in server
    assert server["env_file"] == [".env"]
    assert env["SERVER_PORT"] == str(ORIGIN_PORT)
    assert ORIGIN_PORT in load_yaml(WORKSTATION_VARS_PATH)[
        "workstation_origin_firewall_protected_ports"
    ]


def test_server_serves_exact_paths_without_listing_symlinks_or_fallback() -> None:
    env = load_env_template(STACK_ROOT / ".env.j2")

    assert env["SERVER_DIRECTORY_LISTING"] == "false"
    assert env["SERVER_DISABLE_SYMLINKS"] == "true"
    # The publishing mapping promises dotted path components such as `.bare/`
    # resolve, so hidden files must be served.
    assert env["SERVER_IGNORE_HIDDEN_FILES"] == "false"
    assert "SERVER_FALLBACK_PAGE" not in env


def test_origin_port_is_reserved_only_for_the_artifact_server() -> None:
    configured_paths = {
        path.relative_to(REPO_ROOT)
        for root in (REPO_ROOT / "inventory", REPO_ROOT / "stacks")
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "README.md"
        and str(ORIGIN_PORT)
        in path.read_text(encoding="utf-8", errors="ignore")
    }

    assert configured_paths == {
        Path("inventory/host_vars/workstation.yml"),
        Path("stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml"),
        Path("stacks/workstation/artifacts/.env.j2"),
    }


def test_server_image_update_track_follows_the_running_major() -> None:
    compose = load_yaml(STACK_ROOT / "compose.yaml")
    metadata = load_yaml(STACK_ROOT / "stack.yaml")
    tag = compose["services"]["artifacts"]["image"].rpartition(":")[2]

    assert metadata["updates"]["mode"] == "images"
    assert metadata["updates"]["track"] == tag.split(".")[0]


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
