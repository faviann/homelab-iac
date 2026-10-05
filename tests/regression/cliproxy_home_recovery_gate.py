"""Pinned-pair gate: native enrollment, durable trust and matched full recovery.

Run it whenever a CPA or Home pin changes:
    ./validate.sh tests tests/regression/cliproxy_home_recovery_gate.py
The filename lacks the test_ prefix so the no-argument handoff run never needs
Docker or image pulls; pytest still collects a file named on its command line.
Only temporary local Docker resources and synthetic credentials are used.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.serial
REPO = Path(__file__).resolve().parents[2]
HOME_IMAGE = "eceasy/cli-proxy-api-home:v1.1.0@sha256:14e666f537b26a3fe1cb1a17b458000ff80898edbd7d6cafd83a4d5f7450a49c"
# Follow the deployed pin so a Renovate bump is what this gate exercises.
CPA_IMAGE = yaml.safe_load((REPO / "stacks/overmind/cliproxy/compose.yaml").read_text())["services"]["cliproxy"]["image"]
MANAGEMENT_KEY = "synthetic-recovery-management"
# Fixed bcrypt for the synthetic password above; no password override is used.
MANAGEMENT_HASH = "$2b$04$abcdefghijklmnopqrstuuL5kK5AjodL87dV3psemwSoS1kK8E1Eq"
LEGACY_KEY = "synthetic-recovery-legacy"
NAMED_KEY = "synthetic-recovery-named"
MODEL = "synthetic-recovery-model"


class SyntheticProvider(http.server.BaseHTTPRequestHandler):
    """Local successful usage with no external connections or request logging."""

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps({
            "id": "synthetic-recovery-completion",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "recovered"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass


class HomeCPAPair:
    def __init__(self, root: Path):
        self.root = root
        self.network = "home-recovery-" + uuid.uuid4().hex[:12]
        self.home_name = self.network + "-home"
        self.cpa_name = self.network + "-cpa"
        self.containers: list[str] = []
        self.provider: http.server.ThreadingHTTPServer | None = None
        self.network_created = False
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.home_url = ""
        self.cpa_url = ""

    def directory(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def docker(self, *args: str, stage: str, check: bool = True, timeout: int = 90) -> subprocess.CompletedProcess[str]:
        __tracebackhide__ = True
        environment = os.environ.copy()
        for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
            environment.pop(name, None)
        try:
            # A caller's remote Docker context must never move synthetic state
            # onto a managed host. Every operation uses this local Unix socket.
            result = subprocess.run(["docker", "--host", "unix:///var/run/docker.sock", *args],
                                    capture_output=True, text=True, timeout=timeout, env=environment)
        except (OSError, subprocess.TimeoutExpired):
            pytest.fail(stage + ": Docker unavailable or timed out", pytrace=False)
        if check and result.returncode:
            pytest.fail(f"{stage}: Docker operation failed (exit {result.returncode})", pytrace=False)
        return result

    def prepare(self) -> None:
        assert shutil.which("docker"), "Docker CLI is missing"
        self.docker("version", "--format", "{{.Server.Version}}", stage="mandatory local Docker daemon")
        for image in (HOME_IMAGE, CPA_IMAGE):
            available = self.docker("image", "inspect", "--format", "{{.Id}}", image, stage="pinned image lookup", check=False)
            if available.returncode:
                self.docker("pull", image, stage="mandatory exact pinned image pull", timeout=300)
        self.docker("network", "create", "--internal", self.network, stage="isolated network creation")
        self.network_created = True
        info = json.loads(self.docker("network", "inspect", self.network, stage="network observation").stdout)[0]
        gateway = info["IPAM"]["Config"][0]["Gateway"]
        # Bind only this private bridge, never wildcard, loopback or a LAN IP.
        self.provider = http.server.ThreadingHTTPServer((gateway, 0), SyntheticProvider)
        threading.Thread(target=self.provider.serve_forever, daemon=True).start()
        self.directory("source/auth")
        shutil.copy2(REPO / "stacks/overmind/cliproxy/appdata/config/cluster.yaml", self.root / "cluster.yaml")
        (self.root / "source/config.yaml").write_text(f'''host: ""
port: 8317
api-keys:
  - "{LEGACY_KEY}"
remote-management:
  allow-remote: true
  secret-key: "{MANAGEMENT_HASH}"
  disable-control-panel: false
  disable-auto-update-panel: true
logging-to-file: false
usage-statistics-enabled: true
openai-compatibility:
  - name: "synthetic-recovery-provider"
    base-url: "http://{gateway}:{self.provider.server_port}/v1"
    api-key-entries:
      - api-key: "synthetic-provider-key"
    models:
      - name: "{MODEL}"
        alias: "{MODEL}"
''')
        (self.root / "source/auth/synthetic-codex.json").write_text(json.dumps({
            "type": "codex", "email": "recovery@example.invalid", "disabled": True,
            "access_token": "synthetic-unused-access", "refresh_token": "synthetic-unused-refresh",
            "expired": "2100-01-01T00:00:00Z",
        }))

    def mounts(self, state: Path, home: Path) -> list[str]:
        return ["--user", f"{os.getuid()}:{os.getgid()}", "--env", "HOME=/root",
                "--mount", f"type=bind,src={home},dst=/root",
                "--mount", f"type=bind,src={state},dst=/CLIProxyAPIHome/data",
                "--mount", f"type=bind,src={self.root / 'cluster.yaml'},dst=/CLIProxyAPIHome/cluster.yaml,readonly",
                "--mount", f"type=bind,src={self.root},dst=/recovery"]

    def native(self, state: Path, *args: str, stage: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        # Export AutoMigrate requires the whole SQLite/WAL directory writable.
        return self.docker("run", "--rm", "--pull", "never", "--network", "none",
                           *self.mounts(state, self.directory("offline-home")),
                           "--entrypoint", "/bin/sh", HOME_IMAGE, "-c",
                           'umask 077; exec ./CLIProxyAPIHome -sqlite-path /CLIProxyAPIHome/data/home.db "$@"',
                           "native-tool", *args, stage=stage, check=check)

    def start_home(self, state: Path) -> None:
        self.containers.append(self.home_name)
        self.docker("run", "-d", "--pull", "never", "--name", self.home_name,
                    "--network", self.network, "--network-alias", "cliproxy-home",
                    *self.mounts(state, self.directory("runtime-home")), "--entrypoint", "/bin/sh",
                    HOME_IMAGE, "-c", "umask 077; exec ./CLIProxyAPIHome", stage="Home startup")
        self.home_url = "http://" + self.address(self.home_name) + ":8327/v8/management"
        self.wait(lambda: self.request(self.home_url + "/access/api-keys", MANAGEMENT_KEY)[0] == 200,
                  "authenticated Home readiness")

    def start_cpa(self, cache_home: Path) -> None:
        self.containers.append(self.cpa_name)
        self.docker("run", "-d", "--pull", "never", "--name", self.cpa_name,
                    "--network", self.network, "--user", f"{os.getuid()}:{os.getgid()}",
                    "--env", "HOME=/root", "--env-file", str(self.root / "carrier.env"),
                    "--mount", f"type=bind,src={cache_home},dst=/root",
                    "--entrypoint", "/bin/sh", CPA_IMAGE, "-c", "umask 077; exec ./CLIProxyAPI",
                    stage="CPA startup")
        self.cpa_url = "http://" + self.address(self.cpa_name) + ":8317/v1"

    def address(self, name: str) -> str:
        observed = json.loads(self.docker("container", "inspect", "--format", "{{json .NetworkSettings}}", name,
                                        stage="runtime address observation").stdout)
        return observed["Networks"][self.network]["IPAddress"]

    def request(self, url: str, key: str, method: str = "GET", body: object = None) -> tuple[int, object]:
        headers = {"Authorization": "Bearer " + key}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            with self.client.open(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            error.close()
            return error.code, None
        except (OSError, ValueError):
            return 0, None

    @staticmethod
    def wait(observe, stage: str, timeout: int = 45) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if observe():
                return
            time.sleep(0.25)
        pytest.fail(stage + ": timed out", pytrace=False)

    def enroll(self) -> str:
        status, result = self.request(self.home_url + "/certificates/clients", MANAGEMENT_KEY, "POST", {"node_name": "synthetic-recovery-node"})
        assert status == 200, "native pending certificate creation"
        (self.root / "carrier.env").write_text("HOME_JWT=" + result["home_jwt"] + "\n")
        return result["id"]

    def connected(self, node_id: str) -> bool:
        status, result = self.request(self.home_url + "/nodes", MANAGEMENT_KEY)
        return status == 200 and any(node["node_id"] == node_id and node["node_name"] == "synthetic-recovery-node"
                                    and node["healthy"] for node in result["nodes"])

    def chat(self, key: str) -> bool:
        status, result = self.request(self.cpa_url + "/chat/completions", key, "POST", {
            "model": MODEL, "messages": [{"role": "user", "content": "synthetic recovery"}],
        })
        return status == 200 and result["choices"][0]["message"]["content"] == "recovered"

    def stop(self) -> None:
        for name in (self.home_name, self.cpa_name):
            if name in self.containers:
                self.docker("container", "stop", "--time", "15", name, stage="bounded writer stop")
                running = self.docker("container", "inspect", "--format", "{{.State.Running}}", name, stage="stopped writer observation").stdout.strip()
                assert running == "false", "writer survived stop"
                self.docker("container", "rm", name, stage="fixture stopped-container removal")
                self.containers.remove(name)

    def close(self) -> None:
        try:
            self.stop()
        finally:
            if self.provider is not None:
                self.provider.shutdown()
                self.provider.server_close()
            if self.network_created:
                self.docker("network", "rm", self.network, stage="fixture network cleanup")


@pytest.fixture
def home_cpa_pair():
    # Keep all generated plaintext state outside pytest's retained temp tree.
    with tempfile.TemporaryDirectory(prefix="cliproxy-home-recovery-") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        pair = HomeCPAPair(root)
        try:
            pair.prepare()
            yield pair
        finally:
            pair.close()


def persistent_observation(state: Path) -> dict[str, list[tuple]]:
    """Read only synthetic persistent records; never seed through SQLite.

    v7's accounting payload lacks some v8 API attribution fields, so observe
    the stored nonexpired usage instead. Runtime membership/events and expiring
    KV caches are intentionally absent from this business-state comparison.
    """
    queries = {
        "provider": "select uuid, provider, disabled, auth_json from auth where provider = 'codex' order by uuid",
        "config": "select key, value from config where key in ('remote-management', 'openai-compatibility', 'debug') order by key",
        "keys": "select id, api_key, display_name, user_id, channels, model_groups from api_key order by id",
        "usage": "select id, api_key, model, input_tokens, output_tokens, total_tokens, failed from usage order by id",
        "trust": "select id, certificate_fingerprint, ca_fingerprint, enrollment_secret_hash, is_ca, is_server, is_client from certificate order by id",
        "node_metadata": "select node_id, node_name from cpa_node_metadata order by node_id",
    }
    with sqlite3.connect(f"file:{state / 'home.db'}?mode=ro", uri=True) as db:
        return {name: db.execute(query).fetchall() for name, query in queries.items()}


def test_full_snapshot_restores_business_state_and_matching_cpa(home_cpa_pair):
    pair = home_cpa_pair
    source = pair.directory("source-state")
    cache_home = pair.directory("source-cpa")
    pair.native(source, "-import", "-config", "/recovery/source/config.yaml", "-auth-dir", "/recovery/source/auth", stage="synthetic native seed import")
    # Readiness logs in remotely with the plaintext of the imported hash.
    pair.start_home(source)
    assert pair.request(pair.home_url + "/access/api-keys", "synthetic-wrong-password")[0] in (401, 403), "native management accepts incorrect password"
    with pair.client.open(pair.home_url.replace("/v8/management", "/management.html"), timeout=3) as response:
        assert response.status == 200, "embedded management panel unavailable"
    status, _ = pair.request(pair.home_url + "/access/api-keys", MANAGEMENT_KEY, "POST", {
        "api_key": NAMED_KEY, "display_name": "synthetic-recovery-consumer", "user_id": None, "channels": [], "model_groups": [],
    })
    assert status in (200, 201), "synthetic consumer metadata creation"
    status, _ = pair.request(pair.home_url + "/config/observability/logs/debug", MANAGEMENT_KEY, "PUT", True)
    assert status == 200, "native persistent configuration edit"
    node_id = pair.enroll()
    pair.start_cpa(cache_home)
    pair.wait(lambda: pair.connected(node_id), "native CPA enrollment")
    pair.wait(lambda: pair.chat(NAMED_KEY), "synthetic provider accounting request")
    pair.wait(lambda: any(row[1] == NAMED_KEY and row[5] == 3 and not row[6] for row in persistent_observation(source)["usage"]), "persisted synthetic accounting")
    pair.stop()
    before = persistent_observation(source)
    provider_count, key_count = len(before["provider"]), len(before["keys"])
    assert provider_count == 1 and key_count == 2
    enrolled = any(row[0] == node_id and not row[3] and row[6] for row in before["trust"])
    if not enrolled:
        pytest.fail("enrollment was not completed and consumed", pytrace=False)

    cache = cache_home / ".cli-proxy-api"
    assert cache.stat().st_mode & 0o777 == 0o700, "issued cache directory is not private"
    pem_names = ("client-crt.pem", "client-key.pem", "home-ca-crt.pem")
    for name in pem_names:
        assert (cache / name).stat().st_mode & 0o777 == 0o600, "issued PEM is not private"
    cached_bytes = {name: (cache / name).read_bytes() for name in pem_names}
    pair.start_home(source)
    pair.start_cpa(cache_home)
    pair.wait(lambda: pair.connected(node_id), "consumed carrier restart with same native identity")
    pair.wait(lambda: pair.chat(LEGACY_KEY), "cached trust restart client readiness")
    if any((cache / name).read_bytes() != value for name, value in cached_bytes.items()):
        pytest.fail("cached trust changed on restart", pytrace=False)
    pair.stop()
    before = persistent_observation(source)

    recovery = pair.directory("recovery-set")
    pair.native(source, "-db-export", "/recovery/recovery-set/home.zip", stage="native full database export")
    with zipfile.ZipFile(recovery / "home.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["format"] == "cliproxyapihome-database-snapshot", "export is not a full Home snapshot"
    shutil.copytree(cache_home / ".cli-proxy-api", recovery / "cpa")

    # A consumed enrollment cannot recreate issued trust. The pinned CPA can
    # exit zero and write a private key on failure, so neither is success.
    lost_cache_home = pair.directory("lost-cache-cpa")
    pair.start_home(source)
    pair.start_cpa(lost_cache_home)
    pair.wait(lambda: pair.docker("container", "inspect", "--format", "{{.State.Running}}", pair.cpa_name,
                                stage="cache-loss stopped CPA observation").stdout.strip() == "false",
              "consumed carrier cache-loss rejection")
    lost_cache = lost_cache_home / ".cli-proxy-api"
    assert not (lost_cache / "client-crt.pem").exists() and not (lost_cache / "home-ca-crt.pem").exists(), "consumed carrier recreated issued trust"
    pair.stop()

    target = pair.directory("restored-state")
    pair.native(target, "-db-import", "/recovery/recovery-set/home.zip", stage="native empty-target full restore")
    restored = persistent_observation(target) == before
    if not restored:
        pytest.fail("restored persistent business state differs", pytrace=False)

    restored_home = pair.directory("restored-cpa")
    shutil.copytree(recovery / "cpa", restored_home / ".cli-proxy-api")
    pair.start_home(target)
    pair.start_cpa(restored_home)
    pair.wait(lambda: pair.connected(node_id), "same native CPA identity reconnect without reenrollment")
    pair.wait(lambda: pair.chat(LEGACY_KEY), "restored legacy key/provider request")
    pair.wait(lambda: pair.chat(NAMED_KEY), "restored named key/provider request")
