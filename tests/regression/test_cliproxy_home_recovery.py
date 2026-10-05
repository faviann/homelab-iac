"""Mandatory pinned-image, synthetic Home snapshot and matched CPA recovery.

Run through ./validate.sh tests tests/regression/test_cliproxy_home_recovery.py.
Only temporary local Docker resources are used. Snapshot ZIPs contain plaintext
secrets: native output and artifacts stay private and are never failure messages.
The reusable pair fixture also supplies the native enrollment seam for #481.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
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


pytestmark = pytest.mark.serial
HOME_IMAGE = "eceasy/cli-proxy-api-home:v1.1.0@sha256:14e666f537b26a3fe1cb1a17b458000ff80898edbd7d6cafd83a4d5f7450a49c"
CPA_IMAGE = "eceasy/cli-proxy-api:v7.3.8@sha256:6c2c8a7904799bd29a3f7f92a598555d8321b6a5682000b87af4495c5704fa72"
HOME_REVISION = "c098d84d36f57b765e1545dcb53cb6717a673654"
CPA_REVISION = "c93978c4ea2e908255a2a06c37599fda3651554a"
CACHE_FILES = ("client-crt.pem", "client-key.pem", "home-ca-crt.pem")
MANAGEMENT_KEY = "synthetic-recovery-management"
LEGACY_KEY = "synthetic-recovery-legacy"
NAMED_KEY = "synthetic-recovery-named"
MODEL = "synthetic-recovery-model"


def require(condition: bool, stage: str) -> None:
    """Do not let assertion rewriting disclose secret operands or native output."""
    if not condition:
        pytest.fail(stage, pytrace=False)


def private_file(path: Path, value: str) -> None:
    __tracebackhide__ = True
    with open(path, "w", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        stream.write(value)
    path.chmod(0o600)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def private_modes(root: Path) -> bool:
    return all(path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
               for path in [root, *root.rglob("*")])


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
        current = self.root
        for part in path.relative_to(self.root).parts:
            current = current / part
            current.mkdir(mode=0o700, exist_ok=True)
            current.chmod(0o700)
        return path

    def docker(self, *args: str, stage: str, check: bool = True, timeout: int = 90) -> subprocess.CompletedProcess[str]:
        __tracebackhide__ = True
        # No check=True or command/body dumps: a native diagnostic can contain a
        # credential even when this fixture only generated synthetic credentials.
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
        private_file(self.root / "native-output.log", result.stdout + result.stderr)
        if check:
            require(result.returncode == 0, stage + ": Docker operation failed")
        return result

    def prepare(self) -> None:
        require(shutil.which("docker") is not None, "mandatory Docker CLI is missing")
        self.docker("version", "--format", "{{.Server.Version}}", stage="mandatory local Docker daemon")
        for image in (HOME_IMAGE, CPA_IMAGE):
            available = self.docker("image", "inspect", "--format", "{{.Id}}", image, stage="pinned image lookup", check=False)
            if available.returncode:
                self.docker("pull", image, stage="mandatory exact pinned image pull", timeout=300)
            self.docker("image", "inspect", "--format", "{{.Id}}", image, stage="exact pinned image resolution")
        self.docker("network", "create", "--internal", self.network, stage="isolated network creation")
        self.network_created = True
        info = json.loads(self.docker("network", "inspect", self.network, stage="network isolation observation").stdout)[0]
        require(info["Internal"] is True, "runtime network must block external egress")
        gateway = info["IPAM"]["Config"][0]["Gateway"]
        # Bind only this private bridge, never wildcard, loopback or a LAN IP.
        self.provider = http.server.ThreadingHTTPServer((gateway, 0), SyntheticProvider)
        threading.Thread(target=self.provider.serve_forever, daemon=True).start()
        self.directory("source/auth")
        private_file(self.root / "cluster.yaml", "sqlite:\n  path: /CLIProxyAPIHome/data/home.db\nnode:\n  external-ip: cliproxy-home\n  port: 8327\n")
        private_file(self.root / "source/config.yaml", f'''host: ""
port: 8317
api-keys:
  - "{LEGACY_KEY}"
remote-management:
  allow-remote: true
  secret-key: "{MANAGEMENT_KEY}"
  disable-control-panel: true
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
        private_file(self.root / "source/auth/synthetic-codex.json", json.dumps({
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
                                        stage="private runtime address observation").stdout)
        require(not observed["Ports"] or all(not value for value in observed["Ports"].values()), "zero published ports required")
        require(set(observed["Networks"]) == {self.network}, "runtime attached outside fixture network")
        return observed["Networks"][self.network]["IPAddress"]

    def request(self, url: str, key: str, method: str = "GET", body: object = None) -> tuple[int, object]:
        __tracebackhide__ = True
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
        require(status == 200, "native pending certificate creation")
        private_file(self.root / "carrier.env", "HOME_JWT=" + result["home_jwt"] + "\n")
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
        # Home first prevents an administrator or native writer changing state
        # while CPA drains. Never export if any writer survived its bounded stop.
        for name in (self.home_name, self.cpa_name):
            if name in self.containers:
                self.docker("container", "stop", "--time", "15", name, stage="bounded writer stop")
                running = self.docker("container", "inspect", "--format", "{{.State.Running}}", name, stage="stopped writer observation").stdout.strip()
                require(running == "false", "writer survived stop")
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


def test_full_snapshot_restores_business_state_and_matching_cpa(home_cpa_pair, capsys):
    pair = home_cpa_pair
    source = pair.directory("source-state")
    cache_home = pair.directory("source-cpa")
    pair.native(source, "-import", "-config", "/recovery/source/config.yaml", "-auth-dir", "/recovery/source/auth", stage="synthetic native seed import")
    pair.start_home(source)
    status, _ = pair.request(pair.home_url + "/access/api-keys", MANAGEMENT_KEY, "POST", {
        "api_key": NAMED_KEY, "display_name": "synthetic-recovery-consumer", "user_id": None, "channels": [], "model_groups": [],
    })
    require(status in (200, 201), "synthetic consumer metadata creation")
    status, _ = pair.request(pair.home_url + "/config/observability/logs/debug", MANAGEMENT_KEY, "PUT", True)
    require(status == 200, "native persistent configuration edit")
    node_id = pair.enroll()
    pair.start_cpa(cache_home)
    pair.wait(lambda: pair.connected(node_id), "native CPA enrollment")
    startup = pair.docker("container", "logs", pair.cpa_name, stage="protected CPA build observation")
    build = re.search(r"CLIProxyAPI Version: v?7\.3\.8, Commit: ([a-f0-9]+)", startup.stdout + startup.stderr)
    require(build is not None and len(build[1]) >= 7 and CPA_REVISION.startswith(build[1]), "enrolled CPA source revision changed")
    pair.wait(lambda: pair.chat(NAMED_KEY), "synthetic provider accounting request")
    pair.wait(lambda: any(row[1] == NAMED_KEY and row[5] == 3 and not row[6] for row in persistent_observation(source)["usage"]), "persisted synthetic accounting")
    pair.stop()
    require(private_modes(source) and private_modes(cache_home), "SQLite/WAL or native CPA cache modes are not private")
    before = persistent_observation(source)
    require(len(before["provider"]) == 1 and bool(before["provider"][0][2]), "disabled synthetic provider record missing")
    require("synthetic-unused-refresh" in before["provider"][0][3] and "recovery@example.invalid" in before["provider"][0][3], "synthetic provider metadata missing")
    require(len(before["keys"]) == 2, "both synthetic consumer keys must persist")
    require(any(row[0] == node_id and not row[3] and row[6] for row in before["trust"]), "enrollment was not completed and consumed")

    recovery = pair.directory("recovery-set")
    cache = pair.directory("recovery-set/cpa")
    pair.native(source, "-db-export", "/recovery/recovery-set/home.zip", stage="native post-enrollment full database export")
    snapshot = recovery / "home.zip"
    with zipfile.ZipFile(snapshot) as archive:
        native_manifest = json.loads(archive.read("manifest.json"))
    require(native_manifest["format"] == "cliproxyapihome-database-snapshot", "legacy exchange export is not a full snapshot")
    require(native_manifest["home_version"].removeprefix("v") == "1.1.0", "snapshot exporter Home version changed")
    require(len(native_manifest["home_commit"]) >= 7 and HOME_REVISION.startswith(native_manifest["home_commit"]), "snapshot exporter Home source revision changed")
    tables = {table["name"]: table for table in native_manifest["tables"]}
    require(all(tables[name]["restore"] and tables[name]["rows"] > 0 for name in ("auth", "config", "api_key", "usage", "certificate", "cpa_node_metadata")), "full snapshot lacks persistent recovery state")
    require(not tables["cluster"]["restore"] and not tables["cpa_node"]["restore"], "transient cluster membership must be rebuilt")
    for name in CACHE_FILES:
        shutil.copyfile(cache_home / ".cli-proxy-api" / name, cache / name)
        (cache / name).chmod(0o600)
    cache_hashes = {name: digest(cache / name) for name in CACHE_FILES}
    private_file(recovery / "image-revision-manifest.json", json.dumps({
        "home_image": HOME_IMAGE, "home_revision": HOME_REVISION,
        "cpa_image": CPA_IMAGE, "cpa_revision": CPA_REVISION,
        "snapshot_sha256": digest(snapshot), "cpa_cache_sha256": cache_hashes,
    }, indent=2) + "\n")
    require(private_modes(recovery), "recovery set modes are not private")

    target = pair.directory("restored-state")
    require(not list(target.iterdir()), "restore target must be new and empty")
    pair.native(target, "-db-import", "/recovery/recovery-set/home.zip", stage="native empty-target full restore")
    require(persistent_observation(target) == before, "restored persistent business state differs")
    rejection = pair.native(target, "-db-import", "/recovery/recovery-set/home.zip", stage="populated-target rejection", check=False)
    require(rejection.returncode != 0 and "is not empty" in rejection.stderr + rejection.stdout, "native restore accepted a populated persistent target")
    require(persistent_observation(target) == before, "rejected restore changed populated business state")

    restored_home = pair.directory("restored-cpa")
    shutil.copytree(cache, restored_home / ".cli-proxy-api")
    pair.start_home(target)
    pair.start_cpa(restored_home)
    pair.wait(lambda: pair.connected(node_id), "same native CPA identity reconnect without reenrollment")
    pair.wait(lambda: pair.chat(LEGACY_KEY), "restored legacy key/provider request")
    pair.wait(lambda: pair.chat(NAMED_KEY), "restored named key/provider request")
    require(all(digest(restored_home / ".cli-proxy-api" / name) == value for name, value in cache_hashes.items()), "matching recovered cache was replaced")
    pair.stop()
    after = persistent_observation(target)
    require(all(after[name] == before[name] for name in before if name != "usage"), "reconnect changed recovered persistent metadata or trust")
    require(all(row in after["usage"] for row in before["usage"]), "reconnect lost pre-snapshot accounting")

    # The consumed carrier is still needed for target/identity configuration,
    # but cannot enroll a new key after loss of the matching persisted cache.
    pair.start_home(target)
    lost_cache_home = pair.directory("lost-cache-cpa")
    pair.start_cpa(lost_cache_home)
    pair.wait(lambda: pair.docker("container", "inspect", "--format", "{{.State.Running}}", pair.cpa_name,
                                 stage="missing-cache startup observation").stdout.strip() == "false", "consumed-carrier cache loss fails startup")
    # Pinned CPA returns from main (exit 0) on invalid Home enrollment, so an
    # exit-code check would incorrectly describe its native failure contract.
    failure = pair.docker("container", "logs", pair.cpa_name, stage="protected missing-cache failure observation")
    require("invalid -home-jwt:" in failure.stdout + failure.stderr, "missing cache did not reject consumed enrollment")
    require(not (lost_cache_home / ".cli-proxy-api/client-crt.pem").exists()
            and not (lost_cache_home / ".cli-proxy-api/home-ca-crt.pem").exists(), "missing cache unexpectedly received renewed trust")
    # Home retains recent topology records. The exited native client, rejected
    # carrier and absence of issued certificates prove this startup failed;
    # topology-record absence is not a supported connection observation.
    with capsys.disabled():
        print("\ncliproxy recovery: pinned Home 1.1.0 / CPA 7.3.8; "
              f"snapshot format={native_manifest['format_version']}; "
              + ", ".join(f"{name}={len(rows)}" for name, rows in before.items())
              + "; matched restore/reconnect, populated-target rejection and cache-loss rejection passed")
