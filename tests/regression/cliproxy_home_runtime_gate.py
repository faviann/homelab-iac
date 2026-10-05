"""Exact-image gate for this repository's rendered cliproxy stack wiring.

Explicitly run: ./validate.sh tests tests/regression/cliproxy_home_runtime_gate.py
Only temporary local Docker resources and synthetic credentials are used.
The default handoff suite does not collect this Docker-dependent filename.
Enrollment, cached-trust restart and matched recovery remain owned by
cliproxy_home_recovery_gate.py; protocol behavior belongs to the pinned images.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import yaml

from ansible_test_helper import ansible_playbook_command
from cliproxy_home_recovery_gate import (
    HomeCPAPair, LEGACY_KEY, MODEL, REPO, SyntheticProvider,
)

pytestmark = pytest.mark.serial
CONSUMER_MODEL = "gpt-5.6-sol"


def require(condition: bool, stage: str) -> None:
    if not condition:
        pytest.fail(stage, pytrace=False)


class ContractProvider(SyntheticProvider):
    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.observed_requests.append(payload)
        raw = json.dumps({"id": "synthetic-contract", "object": "chat.completion", "created": int(time.time()),
            "model": CONSUMER_MODEL, "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}]}).encode()
        self.send_response(200)
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

    def identity(self, name: str) -> str:
        return self.docker("inspect", "--format", "{{.Id}}", name, stage="container identity").stdout.strip()


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


def test_actual_materialized_pair_wiring(runtime_pair):
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
    _, models = pair.request(pair.cpa_url + "/models", LEGACY_KEY)
    require(any(item["id"] == CONSUMER_MODEL for item in models["data"]), "Broodling model contract")
    chat = {"model": CONSUMER_MODEL, "messages": [{"role": "user", "content": "synthetic"}],
        "tools": [{"type": "function", "function": {"name": "synthetic", "parameters": {"type": "object", "properties": {}}}}],
        "response_format": {"type": "json_object"}}
    status, result = pair.request(pair.cpa_url + "/chat/completions", LEGACY_KEY, "POST", chat)
    require(status == 200 and result["choices"][0]["message"]["content"] == "{}", "legacy Broodling Chat/tools/JSON contract")
    observed = pair.provider.observed_requests[-1]
    require(observed.get("tools") == chat["tools"] and observed.get("response_format") == chat["response_format"],
        "upstream tools/JSON propagation")

    identities = (pair.identity(pair.home_name), pair.identity(pair.cpa_name))
    require(pair.materialize(carrier).returncode == 0, "second synthetic materialization")
    pair.deployment()
    require(identities == (pair.identity(pair.home_name), pair.identity(pair.cpa_name)),
        "unchanged deployment recreated services")
    cluster = pair.stack_source / "cliproxy/appdata/config/cluster.yaml"
    document = yaml.safe_load(cluster.read_text())
    document["node"]["event-poll-interval"] = "750ms"
    cluster.write_text(yaml.safe_dump(document))
    require(pair.materialize(carrier).returncode == 0, "changed cluster materialization")
    pair.deployment()
    require(pair.identity(pair.home_name) != identities[0] and pair.identity(pair.cpa_name) == identities[1],
        "cluster change must recreate Home only")
    require(pair.docker("exec", pair.home_name, "cat", "/CLIProxyAPIHome/cluster.yaml",
        stage="recreated Home startup document observation").stdout.encode() == cluster.read_bytes(),
        "recreated Home reads the old cluster document")
    inspected = json.loads(pair.docker("inspect", pair.home_name, stage="cluster mount observation").stdout)[0]
    require(any(mount["Destination"] == "/CLIProxyAPIHome/cluster.yaml" and not mount["RW"]
        for mount in inspected["Mounts"]), "cluster mount is not read-only")
    pair.wait(lambda: pair.connected(node), "cluster reread reconnects persistent identity")
    for name in (pair.home_name, pair.cpa_name):
        status = pair.docker("exec", name, "cat", "/proc/1/status", stage="native startup umask observation").stdout
        require("Umask:\t0077" in status, "native binary startup umask is not private")
