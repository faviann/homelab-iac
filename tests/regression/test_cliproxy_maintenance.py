"""Run the human maintenance script with real flock and SSH/Docker stand-ins.

These observations cover our ordering, scope and fail-closed decisions. Docker
shutdown, network behavior and CPA readiness need later real-image acceptance.
"""

from __future__ import annotations

import fcntl
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/cliproxy-maintenance.sh"

# A fixed interpreter and restricted PATH prevent accidental live SSH or Docker.
STAND_IN = f'''#!{sys.executable}
import json, os, subprocess, sys
from pathlib import Path

root = Path(os.environ["REHEARSAL_ROOT"])
name, args = Path(sys.argv[0]).name, sys.argv[1:]
with (root / "events.jsonl").open("a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
if name == "ssh":
    remote = args[args.index("overmind") + 1:]
    if os.environ.get("OFFLINE_REHEARSAL"):
        remote = ["unshare", "-Ur", *remote]
    raise SystemExit(subprocess.run(remote).returncode)

state = json.loads((root / "state.json").read_text())
containers, fail = state["containers"], state["fail"]
verb, target = args[:2], args[-1]
if verb == ["container", "ls"]:
    print("\\n".join(containers))
elif verb == ["container", "inspect"]:
    if fail == "inspect:" + target:
        raise SystemExit(1)
    item = containers[target]
    if "Config.Image" in args[3]:
        print("eceasy/fixture:v1@sha256:" + "a" * 64)
    else:
        print(item["status"])
elif verb == ["container", "stop"]:
    if fail == "stop:" + target:
        raise SystemExit(1)
    if fail != "survives:" + target:
        containers[target]["status"] = "exited"
elif verb == ["container", "rm"]:
    if containers[target]["status"] == "running":
        raise SystemExit("attempted removal of a running container")
    del containers[target]
elif verb == ["container", "start"]:
    if fail != "start":
        containers[target]["status"] = "running"
elif args[0] == "run":
    if fail == "native":
        raise SystemExit(1)
    mounts = [args[i + 1] for i, arg in enumerate(args) if arg == "--mount"]
    paths = {{item.split("dst=")[1].split(",")[0]: Path(item.split("src=")[1].split(",")[0]) for item in mounts}}
    if "--detach" in args:
        containers[args[args.index("--name") + 1]] = {{"status": "running"}}
    elif "-db-export" in args[-1]:
        (paths["/recovery"] / "home.zip").write_bytes(b"synthetic-snapshot")
    elif "-export -export-dir" in args[-1]:
        (paths["/export"] / "config.yaml").write_text("synthetic-current-config")
        (paths["/export"] / "auths").mkdir()
        (paths["/export"] / "auths/current.json").write_text('{{"refresh_token":"synthetic-current"}}')
    elif "-import -config" in args[-1]:
        for path in (paths["/bootstrap"] / "auth").glob("*.json"):
            payload = json.loads(path.read_text())
            payload["uuid"] = "synthetic-added-uuid"
            path.write_text(json.dumps(payload))
        (paths["/CLIProxyAPIHome/data"] / "home.db").write_bytes(b"synthetic-imported-db")
    else:
        (paths["/CLIProxyAPIHome/data"] / "home.db").write_bytes(b"synthetic-restored-db")
else:
    raise SystemExit("unapproved Docker operation: " + repr(args))
(root / "state.json").write_text(json.dumps(state))
'''


class Rehearsal:
    def __init__(self, root: Path):
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        self.home = root / "home"
        (self.home / ".ansible").mkdir(parents=True)
        for command in ("bash", "flock", "timeout", "grep", "sed", "git", "stat", "mkdir",
                        "cp", "sha256sum", "mktemp", "mv", "unshare", "find", "wc", "chmod"):
            self.bin.joinpath(command).symlink_to(shutil.which(command))
        for command in ("ssh", "docker"):
            shim = self.bin / command
            shim.write_text(STAND_IN)
            shim.chmod(0o755)
        self.containers = {
            "cliproxy": self.container("cliproxy"),
            "cliproxy-home": self.container("cliproxy-home"),
        }

    @staticmethod
    def container(name: str, status: str = "running") -> dict:
        return {"status": status}

    def run(self, action="stop", *arguments, fail="", script=SCRIPT, offline=False):
        self.state_file.write_text(json.dumps({"containers": self.containers, "fail": fail}))
        return subprocess.run(
            [str(self.bin / "bash"), str(script), action, *arguments],
            text=True,
            capture_output=True,
            timeout=30,
            env={"PATH": str(self.bin), "HOME": str(self.home), "REHEARSAL_ROOT": str(self.root),
                 "OFFLINE_REHEARSAL": "1" if offline else ""},
        )

    @property
    def state_file(self) -> Path:
        return self.root / "state.json"

    def final(self) -> dict:
        return json.loads(self.state_file.read_text())["containers"]

    def events(self):
        log = self.root / "events.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def effects(self):
        """Mutating Docker calls as (verb, container)."""
        return [
            (event[2], event[-1]) for event in self.events()
            if event[0] == "docker" and event[2] in ("stop", "start", "rm")
        ]


@pytest.fixture
def rehearsal(tmp_path):
    return Rehearsal(tmp_path)


def test_contended_lock_performs_no_ssh_or_docker(rehearsal):
    lock = rehearsal.home / ".ansible/homelab-iac-lifecycle.lock"
    with lock.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = rehearsal.run()
    assert result.returncode == 75
    assert rehearsal.events() == []


@pytest.mark.parametrize("home", ["cliproxy-home", "cliproxy-home-bootstrap"])
def test_stop_stops_home_before_cpa(rehearsal, home):
    if home == "cliproxy-home-bootstrap":
        del rehearsal.containers["cliproxy-home"]
        rehearsal.containers[home] = rehearsal.container(home)
    result = rehearsal.run()
    assert result.returncode == 0, result.stderr
    assert rehearsal.effects() == [("stop", home), ("stop", "cliproxy")]
    assert all(item["status"] == "exited" for item in rehearsal.final().values())


@pytest.mark.parametrize("fail", ["stop:cliproxy-home", "survives:cliproxy-home"])
def test_home_that_does_not_stop_leaves_cpa_untouched(rehearsal, fail):
    result = rehearsal.run(fail=fail)
    assert result.returncode != 0
    assert rehearsal.effects() == [("stop", "cliproxy-home")]


@pytest.mark.parametrize("action", ["stop", "remove-home", "restart-cpa"])
def test_cpa_that_does_not_stop_blocks_later_effects(rehearsal, action):
    rehearsal.containers["cliproxy-home-bootstrap"] = rehearsal.container("cliproxy-home-bootstrap", "exited")
    result = rehearsal.run(action, fail="survives:cliproxy")
    assert result.returncode != 0
    assert all(verb == "stop" for verb, _ in rehearsal.effects())


def test_failed_inspection_is_not_absence(rehearsal):
    result = rehearsal.run(fail="inspect:cliproxy-home")
    assert result.returncode != 0
    assert rehearsal.effects() == []


def test_two_running_home_instances_abort_before_effects(rehearsal):
    rehearsal.containers["cliproxy-home-bootstrap"] = rehearsal.container("cliproxy-home-bootstrap")
    result = rehearsal.run()
    assert result.returncode != 0
    assert rehearsal.effects() == []


@pytest.mark.parametrize("action,removed,pair", [
    ("remove-bootstrap", ["cliproxy-home-bootstrap"], "running"),
    ("remove-home", ["cliproxy-home-bootstrap", "cliproxy-home"], "exited"),
])
def test_removal_is_limited_to_named_home_containers(rehearsal, action, removed, pair):
    rehearsal.containers["cliproxy-home-bootstrap"] = rehearsal.container("cliproxy-home-bootstrap", "exited")
    rehearsal.containers["unrelated"] = rehearsal.container("unrelated")
    result = rehearsal.run(action)
    assert result.returncode == 0, result.stderr
    assert [name for verb, name in rehearsal.effects() if verb == "rm"] == removed
    final = rehearsal.final()
    assert final["unrelated"]["status"] == "running"
    assert final["cliproxy"]["status"] == pair
    if action == "remove-bootstrap":
        assert final["cliproxy-home"]["status"] == "running"


def test_restart_cpa_touches_only_cpa_and_requires_it_running(rehearsal):
    result = rehearsal.run("restart-cpa")
    assert result.returncode == 0, result.stderr
    assert rehearsal.effects() == [("stop", "cliproxy"), ("start", "cliproxy")]
    assert rehearsal.final()["cliproxy-home"]["status"] == "running"
    assert rehearsal.run("restart-cpa", fail="start").returncode != 0


@pytest.fixture
def offline_rehearsal(rehearsal):
    """Map only fixed private paths; namespace root models guest root."""
    data = rehearsal.root / "private-data"
    backups = rehearsal.root / "private-backups"
    for path in (data, backups, data / "home", data / "cpa"):
        path.mkdir(mode=0o700, exist_ok=True)
    (data / "home/home.db").write_bytes(b"synthetic-failed-db")
    (data / "home/home.db-wal").write_bytes(b"synthetic-wal")
    for name in ("client-crt.pem", "client-key.pem", "home-ca-crt.pem"):
        (data / "cpa" / name).write_bytes(b"synthetic-cache")
    legacy = rehearsal.root / "legacy"
    for path in (legacy / "config", legacy / "auth", legacy / "auth/static"):
        path.mkdir(parents=True, mode=0o700)
    for path, payload in ((legacy / "config/config.yaml", b"synthetic-original-config"),
                          (legacy / "auth/original.json", b'{"type":"codex","refresh_token":"synthetic-original"}'),
                          (legacy / "auth/static/panel.html", b"synthetic-panel")):
        path.write_bytes(payload)
        path.chmod(0o600)
    script = rehearsal.root / "scripts/maintenance.sh"
    script.parent.mkdir()
    # Local git revision stays tied to the actual checkout, while remote paths
    # are the only production inputs replaced for this controlled rehearsal.
    script.write_text(SCRIPT.read_text().replace("/data/overmind/cliproxy", str(data))
                      .replace("/backups/overmind/cliproxy", str(backups))
                      .replace("/conf/docker/stacks/cliproxy/appdata", str(legacy))
                      .replace('git -C "$(dirname "$0")/.."', f'git -C "{SCRIPT.parents[1]}"'))
    try:
        yield rehearsal, script, data, backups
    finally:
        shutil.rmtree(data)
        shutil.rmtree(backups)


def test_bootstrap_serves_imported_home_on_loopback_only(offline_rehearsal):
    rehearsal, script, data, _ = offline_rehearsal
    for container in rehearsal.containers.values():
        container["status"] = "exited"
    result = rehearsal.run("start-bootstrap", script=script, offline=True)
    assert result.returncode == 0, result.stderr
    native, = [event for event in rehearsal.events() if event[:2] == ["docker", "run"]]
    assert native[native.index("--publish") + 1] == "127.0.0.1:8327:8327"
    assert f"type=bind,src={data / 'home'},dst=/CLIProxyAPIHome/data" in native


@pytest.mark.parametrize("owner", ["cliproxy", "cliproxy-home"])
def test_bootstrap_refuses_running_writers(offline_rehearsal, owner):
    rehearsal, script, _, _ = offline_rehearsal
    for container in rehearsal.containers.values():
        container["status"] = "exited"
    rehearsal.containers[owner]["status"] = "running"
    result = rehearsal.run("start-bootstrap", script=script, offline=True)
    assert result.returncode != 0
    assert rehearsal.effects() == []
    assert not any(event[:2] == ["docker", "run"] for event in rehearsal.events())


def test_bootstrap_requires_imported_state(offline_rehearsal):
    rehearsal, script, data, _ = offline_rehearsal
    for container in rehearsal.containers.values():
        container["status"] = "exited"
    (data / "home/home.db").unlink()
    result = rehearsal.run("start-bootstrap", script=script, offline=True)
    assert result.returncode != 0
    assert not any(event[:2] == ["docker", "run"] for event in rehearsal.events())


def test_snapshot_and_repeated_restore_preserve_failed_state_and_remain_stopped(offline_rehearsal):
    rehearsal, script, data, _ = offline_rehearsal
    result = rehearsal.run("snapshot", "baseline", script=script, offline=True)
    assert result.returncode == 0, result.stderr
    assert rehearsal.effects() == [("stop", "cliproxy-home"), ("stop", "cliproxy")]
    for _ in range(2):
        result = rehearsal.run("restore", "baseline", script=script, offline=True)
        assert result.returncode == 0, result.stderr
    attempts = list(data.glob("restore-baseline-*"))
    assert len(attempts) == 2
    assert all((attempt / "failed-home/home.db").is_file() for attempt in attempts)
    assert any((attempt / "failed-home/home.db-wal").is_file() for attempt in attempts)
    native = [event for event in rehearsal.events() if event[:2] == ["docker", "run"]]
    assert len(native) == 3
    assert all(event[event.index("--network") + 1] == "none" for event in native)
    assert all(item["status"] == "exited" for item in rehearsal.final().values())


def test_offline_snapshot_failure_retains_candidate_and_never_restarts(offline_rehearsal):
    rehearsal, script, _, backups = offline_rehearsal
    result = rehearsal.run("snapshot", "failed", fail="native", script=script, offline=True)
    assert result.returncode != 0
    assert (backups / "failed").exists()
    assert all(verb == "stop" for verb, _ in rehearsal.effects())


def test_import_uses_only_writable_copy_and_preserves_frozen_source(offline_rehearsal):
    rehearsal, script, data, backups = offline_rehearsal
    shutil.rmtree(data / "home")
    result = rehearsal.run("import-legacy", "initial", script=script, offline=True)
    assert result.returncode == 0, result.stderr
    candidate = backups / "initial"
    original = candidate / "original/auth/original.json"
    copied = candidate / "bootstrap/auth/original.json"
    assert "uuid" not in json.loads(original.read_text())
    assert json.loads(copied.read_text())["uuid"] == "synthetic-added-uuid"
    assert (candidate / "original/auth/static/panel.html").exists()
    assert not (candidate / "bootstrap/auth/static").exists()
    assert original.stat().st_mode & 0o777 == 0o600
    assert "oauth_files=1" in (candidate / "import.txt").read_text()
    native = [event for event in rehearsal.events() if event[:2] == ["docker", "run"]]
    assert len(native) == 1
    assert native[0][native[0].index("--network") + 1] == "none"
    assert "-import -config /bootstrap/config.yaml" in native[0][-1]
    assert all(item["status"] == "exited" for item in rehearsal.final().values())


def test_import_rejects_nonempty_home_without_native_or_source_changes(offline_rehearsal):
    rehearsal, script, _, backups = offline_rehearsal
    result = rehearsal.run("import-legacy", "initial", script=script, offline=True)
    assert result.returncode != 0
    assert not (backups / "initial").exists()
    assert not any(event[:2] == ["docker", "run"] for event in rehearsal.events())


@pytest.mark.parametrize("branch", ["original", "current"])
def test_standalone_rollback_replaces_auth_preserves_state_and_removes_orphans(offline_rehearsal, branch):
    rehearsal, script, data, backups = offline_rehearsal
    rehearsal.containers["cliproxy-home-bootstrap"] = rehearsal.container("cliproxy-home-bootstrap", "exited")
    legacy = rehearsal.root / "legacy"
    if branch == "original":
        shutil.rmtree(data / "home")
        result = rehearsal.run("import-legacy", "candidate", script=script, offline=True)
        assert result.returncode == 0, result.stderr
        expected_file = "original.json"
        expected_payload = "synthetic-original"
    else:
        # No enrollment/cache requirement: preserve incomplete CPA state as evidence.
        shutil.rmtree(data / "cpa")
        result = rehearsal.run("export-current", "candidate", script=script, offline=True)
        assert result.returncode == 0, result.stderr
        assert (backups / "candidate/home/home.db-wal").exists()
        assert not (backups / "candidate/cpa").exists()
        assert (legacy / "auth/original.json").exists()  # Export is not replacement.
        expected_file = "current.json"
        expected_payload = "synthetic-current"
    (legacy / "auth/stale.json").write_bytes(b"synthetic-stale")
    result = rehearsal.run("rollback-" + branch, "candidate", script=script, offline=True)
    assert result.returncode == 0, result.stderr
    assert not (legacy / "auth/stale.json").exists()
    restored = legacy / "auth" / expected_file
    assert json.loads(restored.read_text())["refresh_token"] == expected_payload
    if branch == "current":
        assert not (legacy / "auth/original.json").exists()
    attempt, = backups.glob("rollback-" + branch + "-candidate-*")
    assert (attempt / "replaced-auth/stale.json").exists()
    removed = [target for verb, target in rehearsal.effects() if verb == "rm"]
    assert removed == ["cliproxy-home-bootstrap", "cliproxy-home"]
    assert list(rehearsal.final()) == ["cliproxy"]
    assert rehearsal.final()["cliproxy"]["status"] == "exited"


def test_current_export_failure_keeps_whole_private_state_and_partial_candidate(offline_rehearsal):
    rehearsal, script, _, backups = offline_rehearsal
    result = rehearsal.run("export-current", "failed", fail="native", script=script, offline=True)
    assert result.returncode != 0
    candidate = backups / "failed"
    assert (candidate / "home/home.db-wal").exists()
    assert (candidate / "cpa/client-key.pem").exists()
    assert (candidate / "export").exists()
    assert all(verb == "stop" for verb, _ in rehearsal.effects())
