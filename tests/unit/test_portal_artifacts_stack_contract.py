#!/usr/bin/env python3
"""Repository contract tests for the portal artifact static server."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_ROOT = REPO_ROOT / "stacks" / "portal" / "artifacts"
PUBLICATION_ROOT = "/ephemeral/workstation/artifacts"
SERVER_CONFIG_PATH = "/etc/static-web-server/config.toml"


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
    assert server["volumes"] == [
        f"{PUBLICATION_ROOT}:/srv/artifacts:ro",
        f"./appdata/config.toml:{SERVER_CONFIG_PATH}:ro",
    ]
    assert env["SERVER_ROOT"] == "/srv/artifacts"
    assert server["user"] == "${PUID}:${PGID}"
    assert env["PUID"] == "{{ docker_uid }}"
    assert env["PGID"] == "{{ docker_gid }}"
    assert server["read_only"] is True


def test_server_is_reachable_only_through_traefik() -> None:
    server = load_yaml(STACK_ROOT / "compose.yaml")["services"]["artifacts"]

    assert "ports" not in server
    assert "network_mode" not in server
    assert server["networks"] == ["shared"]


def test_route_is_public_without_leaking_artifact_urls() -> None:
    labels = load_yaml(STACK_ROOT / "compose.yaml")["services"]["artifacts"][
        "labels"
    ]

    # Deliberately public: no forward auth and no local-ip-restriction, so
    # external services can fetch artifact URLs without logging in.
    assert labels == {
        "traefik.enable": True,
        "traefik.http.routers.artifacts.rule": "Host(`artifacts.public.faviann.com`)",
        "traefik.http.routers.artifacts.middlewares": "artifacts-no-leak-headers",
        "traefik.http.middlewares.artifacts-no-leak-headers.headers.referrerPolicy": "no-referrer",
        "traefik.http.middlewares.artifacts-no-leak-headers.headers.customResponseHeaders.X-Robots-Tag": "noindex, nofollow",
    }


def test_server_serves_exact_paths_without_listing_symlinks_or_fallback() -> None:
    env = load_env_template(STACK_ROOT / ".env.j2")

    assert env["SERVER_DIRECTORY_LISTING"] == "false"
    assert env["SERVER_DISABLE_SYMLINKS"] == "true"
    # The publishing mapping promises dotted path components such as `.bare/`
    # resolve, so hidden files must be served.
    assert env["SERVER_IGNORE_HIDDEN_FILES"] == "false"
    assert "SERVER_FALLBACK_PAGE" not in env


def test_markdown_is_served_as_utf8_plain_text_and_nothing_else_changes() -> None:
    env = load_env_template(STACK_ROOT / ".env.j2")
    config = tomllib.loads(
        (STACK_ROOT / "appdata" / "config.toml").read_text(encoding="utf-8")
    )

    assert env["SERVER_CONFIG_FILE"] == SERVER_CONFIG_PATH
    # A [general] table would silently override the SERVER_* boundary above.
    assert config == {
        "advanced": {
            "headers": [
                {
                    "source": "**/*.[mM][dD]",
                    "headers": {"Content-Type": "text/plain; charset=utf-8"},
                }
            ]
        }
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
