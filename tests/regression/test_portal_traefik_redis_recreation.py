#!/usr/bin/env python3
"""Prove Portal recovers Redis-backed routes after Redis recreation."""

from __future__ import annotations

import base64
import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "stacks/portal/traefik3/compose.yaml"
STATIC_CONFIG_PATH = (
    REPO_ROOT / "stacks/portal/traefik3/appdata/traefik3/config/traefik.yaml"
)
DYNAMIC_CONFIG_PATH = STATIC_CONFIG_PATH.parent / "conf.d"
ROUTE_HOST = "bazarr.local.faviann.com"


@pytest.fixture(scope="module", autouse=True)
def require_docker() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail(
            "Docker executable is required for the Portal Traefik recreation",
            pytrace=False,
        )
    result = subprocess.run(
        [docker, "version", "--format", "{{.Server.Version}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        pytest.fail(
            f"Docker daemon is required for the Portal Traefik recreation: {detail}",
            pytrace=False,
        )


def _run(command: list[str], timeout: int = 90) -> str:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={
            **os.environ,
            "CF_DNS_API_TOKEN": "<REPLACE_ME>",
            "TRAEFIK_DASHBOARD_CREDENTIALS": "<REPLACE_ME>",
        },
    )
    if result.returncode != 0:
        raise AssertionError(
            f"{' '.join(command)} failed\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    return result.stdout


def _compose(project: str, overrides: tuple[Path, ...], *args: str) -> str:
    command = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--file",
        str(COMPOSE_PATH),
    ]
    for override in overrides:
        command.extend(("--file", str(override)))
    return _run([*command, *args], timeout=120)


def _wait_for_redis(container: str) -> None:
    for _ in range(60):
        result = subprocess.run(
            ["docker", "exec", container, "redis-cli", "ping"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip() == "PONG":
            return
        time.sleep(0.25)
    raise AssertionError("Redis did not become ready")


def _seed_route(container: str) -> None:
    values = {
        "traefik/http/routers/bazarr/rule": f"Host(`{ROUTE_HOST}`)",
        "traefik/http/routers/bazarr/service": "bazarr",
        "traefik/http/services/bazarr/loadbalancer/servers/0/url": (
            "http://backend:8081/ping"
        ),
    }
    for key, value in values.items():
        _run(["docker", "exec", container, "redis-cli", "SET", key, value])


def _wait_for_route(port: int) -> int | None:
    deadline = time.monotonic() + 30
    status = None
    last_error: OSError | TimeoutError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
                with ssl._create_unverified_context().wrap_socket(
                    connection,
                    server_hostname=ROUTE_HOST,
                ) as secure_connection:
                    secure_connection.sendall(
                        (
                            "GET /ping HTTP/1.1\r\n"
                            f"Host: {ROUTE_HOST}\r\n"
                            "Connection: close\r\n\r\n"
                        ).encode()
                    )
                    response = http.client.HTTPResponse(secure_connection)
                    response.begin()
                    status = response.status
        except (OSError, TimeoutError) as error:
            last_error = error
            status = None
        if status == 200:
            return status
        time.sleep(0.25)
    if last_error is not None:
        raise AssertionError(f"route probe failed: {last_error!r}")
    return status


def _write_disposable_acme_storage(path: Path) -> None:
    certificate = path.parent / "disposable.crt"
    private_key = path.parent / "disposable.key"
    result = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "3650",
            "-subj",
            "/CN=faviann.com",
            "-addext",
            (
                "subjectAltName=DNS:faviann.com,DNS:*.faviann.com,"
                "DNS:*.admin.faviann.com,DNS:*.home.faviann.com,"
                "DNS:*.media.faviann.com,DNS:*.public.faviann.com,"
                "DNS:*.local.faviann.com"
            ),
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"failed to create disposable TLS certificate: {result.stderr}"
        )
    private_key.chmod(0o600)
    sans = [
        "*.faviann.com",
        "*.admin.faviann.com",
        "*.home.faviann.com",
        "*.media.faviann.com",
        "*.public.faviann.com",
        "*.local.faviann.com",
    ]
    storage = {
        "cloudflare": {
            "Account": {
                "Email": "placeholder@example.invalid",
                "Registration": None,
                "PrivateKey": base64.b64encode(private_key.read_bytes()).decode(),
                "KeyType": "4096",
            },
            "Certificates": [
                {
                    "domain": {
                        "main": "faviann.com",
                        "sans": sans,
                    },
                    "certificate": base64.b64encode(certificate.read_bytes()).decode(),
                    "key": base64.b64encode(private_key.read_bytes()).decode(),
                    "Store": "default",
                }
            ],
        }
    }
    path.write_text(json.dumps(storage), encoding="utf-8")
    path.chmod(0o600)


def test_compose_recovers_redis_routes_after_redis_recreation(
    tmp_path: Path,
) -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    traefik_image = compose["services"]["traefik"]["image"]
    project = f"portal-traefik-recreation-{uuid.uuid4().hex[:12]}"
    override = tmp_path / "compose.runtime.yaml"
    redis_update = tmp_path / "compose.redis-update.yaml"
    logs = tmp_path / "logs"
    certificates = tmp_path / "certificates"
    logs.mkdir()
    certificates.mkdir()
    _write_disposable_acme_storage(certificates / "cloudflare-acme.json")
    override.write_text(
        "\n".join(
            [
                "services:",
                "  traefik-docker-socket-proxy:",
                "    container_name: !reset null",
                '    restart: "no"',
                "  traefik:",
                "    container_name: !reset null",
                '    restart: "no"',
                "    ports: !override",
                '      - "127.0.0.1::443/tcp"',
                "    volumes:",
                f"      - {STATIC_CONFIG_PATH}:/etc/traefik/traefik.yaml:ro",
                f"      - {DYNAMIC_CONFIG_PATH}:/etc/traefik/conf.d:ro",
                f"      - {certificates}:/var/traefik/certs:rw",
                f"      - {logs}:/logs:rw",
                "  redis:",
                "    container_name: !reset null",
                '    restart: "no"',
                "    ports: !reset []",
                "  backend:",
                f"    image: {traefik_image}",
                "    command:",
                "      - --entrypoints.backend.address=:8081",
                "      - --ping=true",
                "      - --ping.entrypoint=backend",
                "    networks:",
                "      - shared",
                "networks:",
                "  shared:",
                "    external: false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    redis_update.write_text(
        'services:\n  redis:\n    labels:\n      issue-88.recreation: "true"\n',
        encoding="utf-8",
    )
    overrides = (override,)
    updated_overrides = (override, redis_update)

    try:
        _compose(
            project,
            overrides,
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "60",
        )
        redis_before = _compose(project, overrides, "ps", "--quiet", "redis").strip()
        traefik_before = _compose(
            project, overrides, "ps", "--quiet", "traefik"
        ).strip()
        port = int(
            _run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{(index (index .NetworkSettings.Ports "443/tcp") 0).HostPort}}',
                    traefik_before,
                ]
            ).strip()
        )
        _wait_for_redis(redis_before)
        _seed_route(redis_before)
        assert _wait_for_route(port) == 200

        # This is the normal stack-wide reconciliation path used in production.
        _compose(project, updated_overrides, "up", "--detach")
        redis_after = _compose(
            project, updated_overrides, "ps", "--quiet", "redis"
        ).strip()
        traefik_after = _compose(
            project, updated_overrides, "ps", "--quiet", "traefik"
        ).strip()
        _wait_for_redis(redis_after)
        _seed_route(redis_after)
        recovered_port = int(
            _run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{(index (index .NetworkSettings.Ports "443/tcp") 0).HostPort}}',
                    traefik_after,
                ]
            ).strip()
        )

        assert redis_after != redis_before
        assert _wait_for_route(recovered_port) == 200
    finally:
        subprocess.run(
            [
                "docker",
                "compose",
                "--project-name",
                project,
                "--file",
                str(COMPOSE_PATH),
                "--file",
                str(override),
                "down",
                "--volumes",
                "--remove-orphans",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env={
                **os.environ,
                "CF_DNS_API_TOKEN": "<REPLACE_ME>",
                "TRAEFIK_DASHBOARD_CREDENTIALS": "<REPLACE_ME>",
            },
        )
