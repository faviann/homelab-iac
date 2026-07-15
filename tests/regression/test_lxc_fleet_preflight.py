#!/usr/bin/env python3
"""Thin runner for fleet preflight behavior through the lifecycle facade."""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Iterator

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "regression" / "fixtures"
INVENTORY = FIXTURES / "lxc_fleet_preflight_inventory.yml"
VALIDATION_PREREQUISITE_INVENTORY = (
    FIXTURES / "lxc_validation_prerequisite_inventory.yml"
)
PLAYBOOK = FIXTURES / "lxc_fleet_preflight_test.yml"
ROLE_INTERFACE_INVENTORY = FIXTURES / "lxc_fleet_preflight_interface_inventory.yml"
ROLE_INTERFACE_PLAYBOOK = FIXTURES / "lxc_fleet_preflight_interface_test.yml"
STANDALONE_PLAYBOOK = FIXTURES / "lxc_standalone_validation_test.yml"
MISSING_HOSTNAME_PLAYBOOK = FIXTURES / "lxc_fleet_missing_hostname_test.yml"
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()
DUMMY_API_USER = "dummy@pam"
DUMMY_API_TOKEN_ID = "dummy-token"
DUMMY_API_TOKEN_SECRET = "<REPLACE_ME>"
EXPECTED_AUTHORIZATION = (
    f"PVEAPIToken={DUMMY_API_USER}!{DUMMY_API_TOKEN_ID}={DUMMY_API_TOKEN_SECRET}"
)
VERSION_API_PATH = "/api2/json/version"
NODES_API_PATH = "/api2/json/nodes"
CLUSTER_RESOURCES_API_PATH = "/api2/json/cluster/resources?type=vm"
LXC_API_PATH = "/api2/json/nodes/pve-a/lxc"
EXPECTED_SUCCESS_PATHS = (
    VERSION_API_PATH,
    NODES_API_PATH,
    CLUSTER_RESOURCES_API_PATH,
    LXC_API_PATH,
)

COMMON_OBSERVATION = [
    {"vmid": 5101, "name": "target-a", "status": "stopped"},
    {"vmid": 5102, "name": "target-b", "status": "stopped"},
    {"vmid": 5105, "name": "release-problem", "status": "stopped"},
]


class _ProxmoxHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.server.requests.append(  # type: ignore[attr-defined]
            (self.path, self.headers.get("Authorization"))
        )
        configured_status = self.server.response_status  # type: ignore[attr-defined]
        if configured_status != 200:
            status = configured_status
            payload = {"errors": "controlled Proxmox failure"}
        elif self.path == VERSION_API_PATH:
            status = 200
            payload = {"data": {"version": "9.0"}}
        elif self.path == NODES_API_PATH:
            status = 200
            payload = {"data": [{"node": "pve-a", "status": "online"}]}
        elif self.path == CLUSTER_RESOURCES_API_PATH:
            status = 200
            payload = {
                "data": [
                    {
                        **container,
                        "id": f"lxc/{container['vmid']}",
                        "node": "pve-a",
                        "type": "lxc",
                    }
                    for container in COMMON_OBSERVATION
                ]
            }
        elif self.path == LXC_API_PATH:
            status = 200
            payload = {"data": COMMON_OBSERVATION}
        else:
            status = 404
            payload = {"errors": "unknown test endpoint"}
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def local_proxmox_server(
    certificate: Path,
    private_key: Path,
    *,
    status: int,
) -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProxmoxHandler)
    server.requests = []  # type: ignore[attr-defined]
    server.response_status = status  # type: ignore[attr-defined]
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, private_key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def run_actual_query_case(
    certificate: Path,
    private_key: Path,
    *,
    limit: str,
    status: int,
    check_mode: bool = False,
) -> bool:
    with local_proxmox_server(certificate, private_key, status=status) as server:
        api_port = server.server_address[1]
        extra_vars = {
            "proxmox_fleet_observation_override": None,
            "proxmox_api_host": "127.0.0.1",
            "proxmox_api_port": api_port,
            "proxmox_api_user": DUMMY_API_USER,
            "proxmox_api_token_id": DUMMY_API_TOKEN_ID,
            "proxmox_api_token_secret": DUMMY_API_TOKEN_SECRET,
            "proxmox_default_node": "pve-a",
            "proxmox_verify_ssl": False,
        }
        command = [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(INVENTORY),
            str(PLAYBOOK),
            "--limit",
            limit,
            "--extra-vars",
            json.dumps(extra_vars),
        ]
        if check_mode:
            command.append("--check")
        env = os.environ.copy()
        for key in (
            "ALL_PROXY",
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "all_proxy",
            "https_proxy",
            "http_proxy",
        ):
            env.pop(key, None)
        env["NO_PROXY"] = "127.0.0.1,localhost"
        env["no_proxy"] = "127.0.0.1,localhost"
        proc = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        requests = server.requests[:]  # type: ignore[attr-defined]

    expected_paths = EXPECTED_SUCCESS_PATHS if status == 200 else (VERSION_API_PATH,)
    expected_requests = [
        (path, EXPECTED_AUTHORIZATION) for path in expected_paths
    ]
    if proc.returncode == 0 and requests == expected_requests:
        return True

    paths = [path for path, _authorization in requests]
    authorization_matches = bool(requests) and all(
        authorization == EXPECTED_AUTHORIZATION
        for _path, authorization in requests
    )
    print(
        f"actual query case {limit!r} status={status} check={check_mode} "
        f"made {len(requests)} request(s); paths={paths!r}; "
        f"authorization matched={authorization_matches}",
        file=sys.stderr,
    )
    print(f"{proc.stdout}\n{proc.stderr}", file=sys.stderr)
    return False


def generate_localhost_certificate(certificate: Path, private_key: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private_key.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    private_key.chmod(0o600)


def run_case(limit: str) -> bool:
    env = os.environ.copy()
    env["ANSIBLE_VAULT_PASSWORD_FILE"] = str(
        Path.home() / ".ansible" / "vault-pass"
    )
    command = [
        *ANSIBLE_PLAYBOOK,
        "-i",
        str(INVENTORY),
        str(PLAYBOOK),
        "--limit",
        limit,
    ]
    proc = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode == 0:
        return True

    print(f"fleet preflight case {limit!r} failed unexpectedly", file=sys.stderr)
    print(f"{proc.stdout}\n{proc.stderr}", file=sys.stderr)
    return False


def main() -> int:
    cases = (
        "target_conflict",
        "hostname_conflict",
    )
    if not all(run_case(case) for case in cases):
        return 1

    role_interface = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(ROLE_INTERFACE_INVENTORY),
            str(ROLE_INTERFACE_PLAYBOOK),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if role_interface.returncode != 0:
        print("fleet preflight role interface seam failed", file=sys.stderr)
        print(f"{role_interface.stdout}\n{role_interface.stderr}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="lxc-fleet-https-") as temp_dir:
        temp_root = Path(temp_dir)
        certificate = temp_root / "certificate.pem"
        private_key = temp_root / "private-key.pem"
        generate_localhost_certificate(certificate, private_key)
        actual_cases = (
            run_actual_query_case(
                certificate,
                private_key,
                limit="target_a,target_b",
                status=200,
            ),
            run_actual_query_case(
                certificate,
                private_key,
                limit="target_a,target_b",
                status=200,
                check_mode=True,
            ),
            run_actual_query_case(
                certificate,
                private_key,
                limit="access_target",
                status=503,
            ),
        )
        if not all(actual_cases):
            return 1

    missing_hostname = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(INVENTORY),
            str(MISSING_HOSTNAME_PLAYBOOK),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if missing_hostname.returncode != 0:
        print("incomplete hostname reservations were not aggregated", file=sys.stderr)
        print(f"{missing_hostname.stdout}\n{missing_hostname.stderr}", file=sys.stderr)
        return 1

    validation_tasks = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(INVENTORY),
            "site.yml",
            "--list-tasks",
            "--tags",
            "validation",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    normal_tasks = subprocess.run(
        [*ANSIBLE_PLAYBOOK, "-i", str(INVENTORY), "site.yml", "--list-tasks"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if (
        validation_tasks.returncode != 0
        or "Run aggregate standalone lifecycle validation" not in validation_tasks.stdout
        or normal_tasks.returncode != 0
        or "Run aggregate standalone lifecycle validation" in normal_tasks.stdout
        or "Compile desired LXC specification" not in normal_tasks.stdout
    ):
        print("site.yml validation tag routing is incorrect", file=sys.stderr)
        print(f"validation route:\n{validation_tasks.stdout}\n{validation_tasks.stderr}", file=sys.stderr)
        print(f"normal route:\n{normal_tasks.stdout}\n{normal_tasks.stderr}", file=sys.stderr)
        return 1

    missing_domain = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(VALIDATION_PREREQUISITE_INVENTORY),
            "site.yml",
            "--tags",
            "validation",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    missing_domain_output = f"{missing_domain.stdout}\n{missing_domain.stderr}"
    if (
        missing_domain.returncode == 0
        or "missing `default_domain`" not in missing_domain_output
        or "missing_domain" not in missing_domain_output
    ):
        print("site validation did not reject missing default_domain", file=sys.stderr)
        print(missing_domain_output, file=sys.stderr)
        return 1

    env = os.environ.copy()
    proc = subprocess.run(
        [
            *ANSIBLE_PLAYBOOK,
            "-i",
            str(INVENTORY),
            str(STANDALONE_PLAYBOOK),
            "--limit",
            "target_conflict,release_problem",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    aggregate_output = f"{proc.stdout}\n{proc.stderr}"
    aggregate_fragments = (
        "Standalone lifecycle validation found",
        "Target identity conflict",
        "VMID 5199",
        "Guest release observation is required",
        "release_problem",
    )
    if proc.returncode == 0 or not all(
        fragment in aggregate_output for fragment in aggregate_fragments
    ):
        print("standalone validation did not aggregate all problems", file=sys.stderr)
        print(aggregate_output, file=sys.stderr)
        return 1

    print("ok: fleet preflight shares observations and standalone validation aggregates problems")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
