"""Exact-image repository wiring and existing-consumer contract gate.

Explicitly run: ./validate.sh tests tests/regression/cliproxy_home_runtime_gate.py
Only temporary local Docker resources and synthetic credentials are used.
The default handoff suite does not collect this Docker-dependent filename.
Enrollment/import and matched recovery remain owned by HomeCPAPair's gate.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from ansible_test_helper import ansible_playbook_command
from cliproxy_home_recovery_gate import (
    HomeCPAPair, LEGACY_KEY, MANAGEMENT_KEY, MODEL, REPO, SyntheticProvider,
    persistent_observation,
)

pytestmark = pytest.mark.serial
CONSUMER_MODEL = "gpt-5.6-sol"


def require(condition: bool, stage: str) -> None:
    if not condition:
        pytest.fail(stage, pytrace=False)


class ContractProvider(SyntheticProvider):
    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        valid = (self.path == "/v1/chat/completions"
                 and self.headers.get("Authorization") == "Bearer synthetic-provider-key"
                 and payload.get("model") == CONSUMER_MODEL)
        self.server.observed_requests.append((valid, payload))
        if not valid:
            self.send_error(400)
            return
        body = {"id": "synthetic-contract", "created": int(time.time()), "model": CONSUMER_MODEL,
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}
        self.send_response(200)
        if payload.get("stream"):
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in (({"role": "assistant", "content": "{}"}, None), ({}, "stop")):
                item = {**body, "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                self.wfile.write(("data: " + json.dumps(item) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            raw = json.dumps({**body, "object": "chat.completion", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}]}).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)


class RuntimePair(HomeCPAPair):
    def prepare(self) -> None:
        super().prepare()
        self.provider.RequestHandlerClass = ContractProvider
        self.provider.observed_requests = []
        config = self.root / "source/config.yaml"
        config.write_text(config.read_text().replace(MODEL, CONSUMER_MODEL))
        self.stack_source = self.directory("stack-source")
        shutil.copytree(REPO / "stacks/overmind/cliproxy", self.stack_source / "cliproxy")
        self.target = self.root / "shared/stacks/cliproxy"
        self.project = self.network + "-runtime"
        self.runtime_compose = self.root / "runtime.yaml"
        self.state = self.directory("private/home")
        self.cache = self.directory("private/cpa")
        self.state.chmod(0o700)
        self.cache.chmod(0o700)

    def materialize(self, carrier: str | None) -> subprocess.CompletedProcess[str]:
        variables = {"ansible_user_uid": os.getuid(), "ansible_user_gid": os.getgid(),
            "lxc_docker_environment_internal": {
                "shared_mount_source": str(self.root / "shared"), "stacks_source": str(self.stack_source),
                "shared_owner": os.getuid(), "shared_group": os.getgid(),
                "docker_uid": os.getuid(), "docker_gid": os.getgid(), "path_ownership_overrides": []},
            "lxc_docker_env_stack_vars": {"cliproxy": {} if carrier is None else {"home_jwt": carrier}},
            "lxc_docker_env_desired_top_level_stack_dirs": []}
        tasks = []
        for register, kind, patterns, excludes in (
            ("_per_host_j2_files", "file", "*.j2", ""),
            ("_per_host_static_files", "file", "*", "*.j2,.gitkeep"),
            ("_per_host_dirs", "directory", "*", "")):
            tasks.append({"name": "Discover actual stack " + register,
                "ansible.builtin.find": {"paths": str(self.stack_source), "patterns": patterns,
                    "excludes": excludes, "hidden": True, "recurse": True, "file_type": kind},
                "register": register})
        tasks.append({"name": "Materialize through production tasks", "ansible.builtin.include_tasks":
            str(REPO / "playbooks/roles/config/lxc_stack_sync/tasks/materialize.yml")})
        playbook = self.root / "materialize.yml"
        playbook.write_text(yaml.safe_dump([{"name": "Synthetic repository stack materialization",
            "hosts": "localhost", "connection": "local", "gather_facts": False,
            "vars": variables, "tasks": tasks}]))
        playbook.chmod(0o600)
        result = subprocess.run(ansible_playbook_command(str(playbook)), cwd=REPO,
            capture_output=True, text=True, timeout=120)
        # The result can contain synthetic enrollment material; never print it.
        return result

    def compose(self, *args: str, check: bool = True):
        return self.docker("compose", "--project-name", self.project,
            "--env-file", str(self.target / ".env"), "-f", str(self.runtime_compose),
            *args, stage="actual rendered Compose operation", check=check, timeout=120)

    def deployment(self) -> None:
        document = yaml.safe_load((self.target / "compose.yaml").read_text())
        require(set(document["services"]) == {"cliproxy", "cliproxy-home"}, "permanent service topology")
        # Only resource identities, published ports, bind source paths and the
        # network differ. Commands, images, environment, dependencies and bind
        # targets are the actual materialized repository deployment.
        for name, service in document["services"].items():
            service["container_name"] = self.cpa_name if name == "cliproxy" else self.home_name
            service["ports"] = []
            service["networks"] = ["fixture"]
            volumes = []
            for mount in service["volumes"]:
                source, target, *options = mount.split(":")
                if source == "/data/overmind/cliproxy/home":
                    source = str(self.state)
                elif source == "/data/overmind/cliproxy/cpa":
                    source = str(self.cache)
                else:
                    require(source.startswith("./"), "unexpected production bind source")
                    source = str(self.target / source[2:])
                volumes.append(":".join([source, target, *options]))
            service["volumes"] = volumes
        document["networks"] = {"fixture": {"external": True, "name": self.network}}
        self.runtime_compose.write_text(yaml.safe_dump(document, sort_keys=False))
        self.compose("up", "-d", "--pull", "never")
        for name in (self.home_name, self.cpa_name):
            if name not in self.containers:
                self.containers.append(name)
        self.home_url = "http://" + self.address(self.home_name) + ":8327/v8/management"
        self.cpa_url = "http://" + self.address(self.cpa_name) + ":8317/v1"

    def raw_request(self, path: str, payload: dict) -> tuple[int, bytes]:
        request = urllib.request.Request(self.cpa_url + path, data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + LEGACY_KEY, "Content-Type": "application/json"})
        try:
            with self.client.open(request, timeout=8) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            error.close()
            return error.code, b""

    def cache_fingerprint(self) -> str:
        # Production runs as root. Observe digests inside the existing native
        # container without changing ownership or exposing private PEM bytes.
        return self.docker("exec", self.cpa_name, "sh", "-c",
            "cd /root/.cli-proxy-api && sha256sum client-crt.pem client-key.pem home-ca-crt.pem",
            stage="private issued trust fingerprints").stdout

    def private_files(self) -> bool:
        for name, directory in ((self.home_name, "/CLIProxyAPIHome/data"),
                                (self.cpa_name, "/root/.cli-proxy-api")):
            modes = self.docker("exec", name, "sh", "-c",
                "find " + directory + " -type f -exec stat -c %a {} ';'",
                stage="native private file mode observation").stdout.splitlines()
            if not modes or any(mode != "600" for mode in modes):
                return False
        return True

    def identity(self, name: str) -> str:
        return self.docker("inspect", "--format", "{{.Id}}", name, stage="container identity").stdout.strip()

    def websocket(self) -> list[dict]:
        with socket.create_connection((self.address(self.cpa_name), 8317), timeout=8) as connection:
            key = base64.b64encode(os.urandom(16)).decode()
            connection.sendall(("GET /v1/responses HTTP/1.1\r\nHost: cliproxy:8317\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: " + key +
                "\r\nSec-WebSocket-Version: 13\r\nAuthorization: Bearer " + LEGACY_KEY + "\r\n\r\n").encode())
            buffer = b""
            while b"\r\n\r\n" not in buffer:
                fragment = connection.recv(4096)
                require(bool(fragment), "WebSocket upgrade closed")
                buffer += fragment
            header, buffer = buffer.split(b"\r\n\r\n", 1)
            require(header.startswith(b"HTTP/1.1 101"), "Responses WebSocket upgrade")
            raw = json.dumps({"type": "response.create", "model": CONSUMER_MODEL,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": "synthetic"}]}]}).encode()
            mask = os.urandom(4)
            frame = (bytes([0x81, 0x80 | len(raw)]) if len(raw) < 126
                     else bytes([0x81, 0x80 | 126]) + struct.pack("!H", len(raw)))
            connection.sendall(frame + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw)))
            def exact(size):
                nonlocal buffer
                while len(buffer) < size:
                    fragment = connection.recv(4096)
                    require(bool(fragment), "Responses WebSocket closed before completion")
                    buffer += fragment
                result, buffer = buffer[:size], buffer[size:]
                return result
            items = []
            for _ in range(30):
                header = exact(2)
                size = header[1] & 127
                if size == 126:
                    size = struct.unpack("!H", exact(2))[0]
                elif size == 127:
                    size = struct.unpack("!Q", exact(8))[0]
                require(size < 1024 * 1024, "bounded synthetic WebSocket frame")
                require(header[0] & 15 == 1, "Responses WebSocket text frame")
                item = json.loads(exact(size))
                items.append(item)
                if item.get("type") in ("response.completed", "error", "response.failed"):
                    return items
            return items


@pytest.fixture
def runtime_pair():
    with tempfile.TemporaryDirectory(prefix="cliproxy-home-runtime-") as temporary:
        pair = RuntimePair(Path(temporary))
        pair.root.chmod(0o700)
        try:
            pair.prepare()
            yield pair
        finally:
            pair.close()


def test_actual_materialized_pair_and_existing_consumer_contract(runtime_pair):
    pair = runtime_pair
    require(pair.materialize(None).returncode != 0, "missing carrier materialization must reject")
    require(not (pair.target / "compose.yaml").exists(), "missing carrier wrote deployment assets")
    pair.native(pair.state, "-import", "-config", "/recovery/source/config.yaml",
        "-auth-dir", "/recovery/source/auth", stage="reused synthetic native import")
    pair.start_home(pair.state)
    node = pair.enroll()
    carrier = (pair.root / "carrier.env").read_text().removeprefix("HOME_JWT=").strip()
    pair.stop()
    require(pair.materialize(carrier).returncode == 0, "actual stack materialization")
    require((pair.target / ".env").stat().st_mode & 0o777 == 0o600, "rendered carrier environment is private")
    pair.deployment()
    pair.wait(lambda: pair.connected(node), "Compose DNS/mTLS healthy recorded identity")
    pair.wait(lambda: pair.request(pair.cpa_url + "/models", LEGACY_KEY)[0] == 200, "legacy key readiness")
    status, models = pair.request(pair.cpa_url + "/models", LEGACY_KEY)
    require(any(item["id"] == CONSUMER_MODEL for item in models["data"]), "Broodling model contract")
    require(pair.request(pair.cpa_url + "/models", "wrong-synthetic-key")[0] == 401, "Home owns client authentication")
    chat = {"model": CONSUMER_MODEL, "messages": [{"role": "user", "content": "synthetic"}],
        "tools": [{"type": "function", "function": {"name": "synthetic", "parameters": {"type": "object", "properties": {}}}}],
        "response_format": {"type": "json_object"}}
    status, raw = pair.raw_request("/chat/completions", chat)
    require(status == 200 and json.loads(raw)["choices"][0]["message"]["content"] == "{}", "legacy Chat/tools/JSON contract")
    observed = pair.provider.observed_requests[-1][1]
    require(observed.get("tools") == chat["tools"] and observed.get("response_format") == chat["response_format"], "upstream tools/JSON propagation")
    status, raw = pair.raw_request("/chat/completions", {**chat, "stream": True})
    require(status == 200 and b"[DONE]" in raw and b"{}" in raw, "Chat SSE contract")
    status, raw = pair.raw_request("/messages", {"model": CONSUMER_MODEL, "max_tokens": 20, "messages": chat["messages"]})
    require(status == 200 and json.loads(raw).get("type") == "message", "Anthropic Messages contract")
    for stream in (False, True):
        status, raw = pair.raw_request("/responses", {"model": CONSUMER_MODEL, "input": "synthetic", "stream": stream})
        require(status == 200 and (b"response.completed" in raw if stream else json.loads(raw).get("object") == "response"), "Responses HTTP/SSE contract")
    require(any(item.get("type") == "response.completed" for item in pair.websocket()), "Responses WebSocket completion")
    require(all(valid for valid, _ in pair.provider.observed_requests), "synthetic provider path/auth/model contract")
    status, _ = pair.request(pair.home_url + "/config/observability/logs/debug", MANAGEMENT_KEY, "PUT", True)
    require(status == 200, "Home runtime configuration authority")
    pair.wait(lambda: "home config changes detected" in pair.docker("logs", pair.cpa_name, stage="native config propagation observation").stdout,
        "Home configuration subscription reaches CPA")
    before = persistent_observation(pair.state)
    cache = pair.cache_fingerprint()
    identities = (pair.identity(pair.home_name), pair.identity(pair.cpa_name))
    require(pair.materialize(carrier).returncode == 0, "second synthetic materialization")
    pair.deployment()
    require(identities == (pair.identity(pair.home_name), pair.identity(pair.cpa_name)), "unchanged deployment recreated services")
    cluster = pair.stack_source / "cliproxy/appdata/config/cluster.yaml"
    document = yaml.safe_load(cluster.read_text())
    document["node"]["event-poll-interval"] = "750ms"
    cluster.write_text(yaml.safe_dump(document))
    require(pair.materialize(carrier).returncode == 0, "changed cluster materialization")
    pair.deployment()
    require(pair.identity(pair.home_name) != identities[0] and pair.identity(pair.cpa_name) == identities[1], "cluster fingerprint must recreate Home only")
    pair.wait(lambda: pair.connected(node), "cluster reread reconnects persistent identity")
    require((pair.target / "appdata/config/cluster.yaml").read_bytes() == cluster.read_bytes(), "cluster materialized content differs")
    require(pair.docker("exec", pair.home_name, "cat", "/CLIProxyAPIHome/cluster.yaml",
        stage="recreated Home native startup document observation").stdout.encode() == cluster.read_bytes(),
        "recreated Home reads old mounted cluster inode")
    status, raw = pair.raw_request("/chat/completions", chat)
    require(status == 200 and json.loads(raw)["choices"][0]["message"]["content"] == "{}",
        "cluster redeployment authenticated provider readiness")
    inspected = json.loads(pair.docker("inspect", pair.home_name, stage="cluster mount observation").stdout)[0]
    require(any(mount["Destination"] == "/CLIProxyAPIHome/cluster.yaml" and not mount["RW"] for mount in inspected["Mounts"]), "cluster mount is not read-only")
    require(inspected["Config"]["Env"] and "HOME_CLUSTER_FINGERPRINT=" + hashlib.sha256(cluster.read_bytes()).hexdigest() in inspected["Config"]["Env"], "cluster fingerprint differs from native startup document")
    pair.compose("restart", "cliproxy")
    pair.wait(lambda: pair.connected(node), "cached CPA identity restart")
    pair.wait(lambda: pair.request(pair.cpa_url + "/models", LEGACY_KEY)[0] == 200, "cached CPA client readiness")
    require(pair.cache_fingerprint() == cache, "persistent native trust changed")
    after = persistent_observation(pair.state)
    require(all(after[key] == before[key] for key in ("provider", "config", "keys", "trust", "node_metadata")), "redeployment changed durable business state")
    for root in (pair.state, pair.cache):
        require(root.stat().st_mode & 0o777 == 0o700, "private runtime directory permission")
    require(pair.private_files(), "native runtime file is not private")
    for name in (pair.home_name, pair.cpa_name):
        status = pair.docker("exec", name, "cat", "/proc/1/status", stage="native startup umask observation").stdout
        require("Umask:\t0077" in status, "native binary startup umask is not private")
    pair.compose("stop", "cliproxy-home")
    pair.wait(lambda: pair.request(pair.cpa_url + "/models", LEGACY_KEY)[0] == 503, "Home outage must reject new requests", timeout=45)
