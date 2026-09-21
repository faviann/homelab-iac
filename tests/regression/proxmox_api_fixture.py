"""Local TLS Proxmox API fixture for credential and observation checks."""

from __future__ import annotations

import json
import ssl
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlsplit

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

COMMON_OBSERVATION = [
    {"vmid": 5101, "name": "target-a", "node": "pve-a", "status": "stopped"},
    {"vmid": 5102, "name": "target-b", "node": "pve-b", "status": "stopped"},
    {
        "vmid": 5105,
        "name": "release-problem",
        "node": "pve-a",
        "status": "stopped",
    },
]


VERSION_API_PATH = "/api2/json/version"
CLUSTER_STATUS_API_PATH = "/api2/json/cluster/status"
NODE_STATUS_API_PATH = "/api2/json/nodes/pve-a/status"
LXC_API_PATHS = (
    "/api2/json/nodes/pve-a/lxc",
    "/api2/json/nodes/pve-b/lxc",
)


class _ProxmoxHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.server.requested_paths.append(self.path)
        if self.path == VERSION_API_PATH:
            status = 200
            payload = {"data": {"version": "9.0"}}
        elif self.path == CLUSTER_STATUS_API_PATH:
            status = 200
            payload = {"data": [{"type": "cluster", "name": "fixture"}]}
        elif self.path == NODE_STATUS_API_PATH:
            status = 200
            payload = {"data": {"status": "online"}}
        elif urlsplit(self.path).path == "/api2/json/access/permissions":
            path = parse_qs(urlsplit(self.path).query)["path"][0]
            status = 200
            payload = {
                "data": {
                    path: {} if path in self.server.denied_audit_paths else {
                        # Zero grants this path without granting descendants.
                        "VM.Audit": 1 if path == "/vms" else 0
                    }
                }
            }
        elif self.path in LXC_API_PATHS:
            status = 200
            node = self.path.split("/")[4]
            payload = {
                "data": [
                    container
                    for container in COMMON_OBSERVATION
                    if container["node"] == node
                ]
            }
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
    denied_audit_paths: tuple[str, ...] = (),
) -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProxmoxHandler)
    server.denied_audit_paths = denied_audit_paths
    server.requested_paths = []
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
