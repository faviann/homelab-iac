"""Native consumer identity/revocation gate for the exact Home/CPA pins.

Explicitly run: ./validate.sh tests tests/regression/cliproxy_home_identity_gate.py
Uses the existing recovery fixture, local internal Docker and synthetic keys.
The default handoff suite does not collect this Docker-dependent filename.
Existing stream/retained same-model selection behavior is checked only at the
revocation boundary; this is not a general protocol compatibility suite.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from cliproxy_home_recovery_gate import (
    HomeCPAPair, LEGACY_KEY, MANAGEMENT_KEY, MODEL, SyntheticProvider,
)

pytestmark = pytest.mark.serial
RETAINED_MODEL = "synthetic-retained-model"


def require(condition: bool, stage: str) -> None:
    if not condition:
        pytest.fail(stage, pytrace=False)


@contextmanager
def guarded(stage: str):
    # Never expose exception text, request objects, response bodies or locals.
    try:
        yield
    except Exception:
        pytest.fail(stage, pytrace=False)


class RevocationProvider(SyntheticProvider):
    def do_GET(self) -> None:
        # Only the local native Codex exchange needed to retain a selection.
        # No OAuth, external provider or general WebSocket implementation.
        with guarded_provider(self.server):
            self.connection.settimeout(8)
            if not self.path.endswith("/responses"):
                raise ValueError
            accept = base64.b64encode(hashlib.sha1((self.headers["Sec-WebSocket-Key"]
                + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.server.native_connections += 1
            for turn in range(2):
                header = self.rfile.read(2)
                if not header or header[0] & 15 == 8:
                    return
                if len(header) != 2 or header[0] != 0x81 or not header[1] & 0x80:
                    raise ValueError
                size = header[1] & 127
                if size == 126:
                    size = struct.unpack("!H", self.rfile.read(2))[0]
                if size > 65536 or size == 127:
                    raise ValueError
                mask = self.rfile.read(4)
                raw = self.rfile.read(size)
                payload = json.loads(bytes(value ^ mask[index % 4] for index, value in enumerate(raw)))
                if payload.get("type") != "response.create" or (turn and payload.get("previous_response_id") != "synthetic-retained-1"):
                    raise ValueError
                self.server.native_turns += 1
                self.server.served += 1
                raw = json.dumps({"type": "response.completed", "response": {
                    "id": "synthetic-retained-" + str(turn + 1), "object": "response", "status": "completed", "output": [],
                    "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}}}).encode()
                self.wfile.write(bytes([0x81, 126]) + struct.pack("!H", len(raw)) + raw)
                self.wfile.flush()
            # Retain the upstream socket until the fixture tears down CPA.
            self.rfile.read(2)

    def do_POST(self) -> None:
        with guarded_provider(self.server):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.server.served += 1
            if not payload.get("stream"):
                body = json.dumps({"id": "synthetic-identity", "object": "chat.completion",
                    "created": int(time.time()), "model": MODEL,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "recovered"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunk = {"id": "synthetic-identity", "object": "chat.completion.chunk",
                "created": int(time.time()), "model": MODEL,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": "recovered"}, "finish_reason": None}]}
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.flush()
            if any(message.get("content") == "held-revocation" for message in payload.get("messages", [])):
                self.server.stream_started.set()
                if not self.server.stream_release.wait(30):
                    self.server.failed = True
                    return
            chunk["choices"] = [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            chunk["usage"] = {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())
            self.wfile.flush()


@contextmanager
def guarded_provider(server):
    # ThreadingHTTPServer otherwise prints exception tracebacks independently
    # of pytest's guards. A boolean is all the gate needs for failure evidence.
    try:
        yield
    except Exception:
        server.failed = True


class RetainedResponses:
    """Small masked client for one local same-model retained-selection probe."""

    def __init__(self, url: str, key: str):
        target = urllib.parse.urlsplit(url)
        self.socket = socket.create_connection((target.hostname, target.port), timeout=8)
        self.reader = self.socket.makefile("rb")
        nonce = base64.b64encode(os.urandom(16)).decode()
        self.socket.sendall((f"GET {target.path} HTTP/1.1\r\nHost: {target.netloc}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n"
            f"Authorization: Bearer {key}\r\n\r\n").encode())
        self.status = int(self.reader.readline(4096).split()[1])
        self.previous_response_id = ""
        for _ in range(30):
            if self.reader.readline(4096) == b"\r\n":
                break
        else:
            require(False, "bounded WebSocket upgrade headers")

    def turn(self) -> bool:
        payload = {"type": "response.create", "model": RETAINED_MODEL,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "revocation selection"}]}]}
        if self.previous_response_id:
            payload["previous_response_id"] = self.previous_response_id
        raw = json.dumps(payload).encode()
        mask = os.urandom(4)
        head = bytes([0x81, 0x80 | len(raw)]) if len(raw) < 126 else bytes([0x81, 0xfe]) + struct.pack("!H", len(raw))
        self.socket.sendall(head + mask + bytes(value ^ mask[index % 4] for index, value in enumerate(raw)))
        for _ in range(100):
            header = self.reader.read(2)
            require(len(header) == 2, "retained WebSocket frame header")
            size = header[1] & 127
            if size == 126:
                size = struct.unpack("!H", self.reader.read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.reader.read(8))[0]
            require(size <= 65536 and not header[1] & 0x80, "bounded local WebSocket frame")
            raw = self.reader.read(size)
            if header[0] & 15 == 8:
                return False
            item = json.loads(raw)
            if item.get("type") in ("response.completed", "error", "response.failed"):
                if item["type"] == "response.completed":
                    self.previous_response_id = item["response"]["id"]
                return item["type"] == "response.completed"
        return False

    def close(self) -> None:
        self.reader.close()
        self.socket.close()


@pytest.fixture
def identity_pair():
    with tempfile.TemporaryDirectory(prefix="cliproxy-home-identity-") as temporary:
        pair = HomeCPAPair(Path(temporary))
        pair.root.chmod(0o700)
        try:
            with guarded("synthetic identity fixture setup"):
                pair.prepare()
                pair.provider.served = 0
                pair.provider.failed = False
                pair.provider.native_connections = 0
                pair.provider.native_turns = 0
                pair.provider.stream_started = threading.Event()
                pair.provider.stream_release = threading.Event()
                pair.provider.RequestHandlerClass = RevocationProvider
                source = pair.root / "source/config.yaml"
                config = yaml.safe_load(source.read_text())
                config["codex-api-key"] = [{"api-key": base64.urlsafe_b64encode(os.urandom(32)).decode(),
                    "base-url": config["openai-compatibility"][0]["base-url"], "websockets": True,
                    "models": [{"name": RETAINED_MODEL, "alias": RETAINED_MODEL}]}]
                source.write_text(yaml.safe_dump(config))
                source.chmod(0o600)
            yield pair
        finally:
            with guarded("synthetic identity fixture cleanup"):
                if pair.provider is not None and hasattr(pair.provider, "stream_release"):
                    pair.provider.stream_release.set()
                pair.close()


def keys(pair):
    status, result = pair.request(pair.home_url + "/access/api-keys", MANAGEMENT_KEY)
    require(status == 200, "native identity listing")
    return result["items"]


def attributed(pair, identities: set[int]) -> bool:
    status, result = pair.request(pair.home_url + "/usage/records?limit=200&status=success", MANAGEMENT_KEY)
    if status != 200:
        return False
    observed = {row["client"]["api_key_id"] for row in result["items"]
        if row["model"] == MODEL and row["tokens"]["total_tokens"] == 3}
    return identities <= observed


def test_native_consumer_identities_and_revocation(identity_pair):
    with guarded("native consumer identity/revocation gate"):
        verify_identities(identity_pair)


def verify_identities(pair) -> None:
    state = pair.directory("state")
    pair.native(state, "-import", "-config", "/recovery/source/config.yaml",
        "-auth-dir", "/recovery/source/auth", stage="synthetic identity import")
    pair.start_home(state)
    node = pair.enroll()
    pair.start_cpa(pair.directory("cpa-cache"))
    pair.wait(lambda: pair.connected(node), "identity pair enrollment readiness")
    pair.wait(lambda: pair.chat(LEGACY_KEY), "imported legacy request readiness")

    imported = keys(pair)
    require(len(imported) == 1 and imported[0]["api_key"] == LEGACY_KEY, "literal legacy import")
    legacy = imported[0]
    status, result = pair.request(pair.home_url + "/access/api-keys", MANAGEMENT_KEY, "PATCH",
        {"id": legacy["id"], "display_name": "legacy-shared"})
    require(status == 200, "individual legacy label update")
    labeled = result["api_key"]
    require(all(labeled[field] == legacy[field] for field in ("id", "api_key", "user_id", "channels", "model_groups"))
        and labeled["display_name"] == "legacy-shared", "legacy metadata update preserves identity and credential")

    credentials = [base64.urlsafe_b64encode(os.urandom(32)).decode() for _ in range(3)]
    records = []
    for name, credential in zip(("synthetic-consumer-one", "synthetic-consumer-two", "synthetic-sacrificial"), credentials):
        status, result = pair.request(pair.home_url + "/access/api-keys", MANAGEMENT_KEY, "POST",
            {"api_key": credential, "display_name": name, "user_id": None, "channels": [], "model_groups": []})
        require(status == 201, "individual named identity creation")
        record = result["api_key"]
        require(record["display_name"] == name and record["user_id"] is None
            and record["channels"] == [] and record["model_groups"] == [], "named unowned unrestricted identity")
        records.append(record)
    ids = {legacy["id"], *(record["id"] for record in records)}
    require(len(ids) == 4 and {record["id"] for record in keys(pair)} == ids, "distinct stable identities without list replacement")
    for credential in [LEGACY_KEY, *credentials]:
        before = pair.provider.served
        require(pair.chat(credential) and pair.provider.served == before + 1, "each identity serves through the shared fake provider")
    pair.wait(lambda: attributed(pair, ids), "native usage attribution by stable identity")
    status, aggregates = pair.request(pair.home_url + "/usage/aggregates?group_by=client_key", MANAGEMENT_KEY)
    require(status == 200 and ids <= {item["metadata"]["api_key_id"] for item in aggregates["items"]
        if item["label"] == "api-key-" + str(item["metadata"]["api_key_id"])},
        "native aggregate stable IDs with api-key-ID display labels")

    retained = None
    held = None
    try:
        retained = RetainedResponses(pair.cpa_url + "/responses", credentials[2])
        require(retained.status == 101 and retained.turn() and pair.provider.native_connections == 1
            and pair.provider.native_turns == 1, "native sacrificial WebSocket selection established before deletion")
        held = pair.client.open(urllib.request.Request(pair.cpa_url + "/chat/completions",
            data=json.dumps({"model": MODEL, "stream": True,
                "messages": [{"role": "user", "content": "held-revocation"}]}).encode(),
            headers={"Authorization": "Bearer " + credentials[2], "Content-Type": "application/json"}), timeout=8)
        require(held.status == 200 and held.readline().startswith(b"data:")
            and pair.provider.stream_started.wait(3) and not pair.provider.stream_release.is_set(),
            "sacrificial HTTP stream accepted and held before deletion")
        status, _ = pair.request(pair.home_url + "/access/api-keys?id=" + str(records[2]["id"]), MANAGEMENT_KEY, "DELETE")
        require(status == 200, "individual sacrificial deletion by stable ID")
        before = pair.provider.served
        status, _ = pair.request(pair.cpa_url + "/chat/completions", credentials[2], "POST",
            {"model": MODEL, "messages": [{"role": "user", "content": "new after deletion"}]})
        require(status == 401 and pair.provider.served == before,
            "immediate independent request rejection after deletion before upstream")
        require(retained.turn() and pair.provider.native_connections == 1 and pair.provider.native_turns == 2,
            "retained same-model native WebSocket selection survives key deletion on the same upstream connection")
        pair.provider.stream_release.set()
        require(b"[DONE]" in held.read(), "accepted HTTP stream completes after key deletion")
    finally:
        pair.provider.stream_release.set()
        if held is not None:
            held.close()
        if retained is not None:
            retained.close()
    require({record["id"] for record in keys(pair)} == ids - {records[2]["id"]}, "only sacrificial identity deleted")
    for credential in [LEGACY_KEY, *credentials[:2]]:
        require(pair.chat(credential), "other named and legacy identities remain usable")
    require(not pair.provider.failed, "shared synthetic provider completed without errors")
