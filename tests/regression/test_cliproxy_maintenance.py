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
    if "NetworkSettings" in args[3]:
        print(" ".join(item["networks"]))
    elif "Config.Image" in args[3]:
        print("eceasy/fixture:v1@sha256:" + "a" * 64)
    else:
        print(item["status"])
elif verb == ["container", "stop"]:
    if fail == "stop:" + target:
        raise SystemExit(1)
    if fail != "survives:" + target:
        containers[target]["status"] = "exited"
elif verb == ["network", "disconnect"]:
    containers[target]["networks"].remove(args[-2])
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
    if "-db-export" in args[-1]:
        (paths["/recovery"] / "home.zip").write_bytes(b"synthetic-snapshot")
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
                        "cp", "sha256sum", "mktemp", "mv", "unshare"):
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
        bootstrap = name == "cliproxy-home-bootstrap"
        return {"status": status, "networks": ["cliproxy_default"] if bootstrap else []}

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
            if event[0] == "docker" and event[2] in ("stop", "start", "rm", "disconnect")
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
def test_stop_stops_home_before_cpa_and_detaches_bootstrap(rehearsal, home):
    if home == "cliproxy-home-bootstrap":
        del rehearsal.containers["cliproxy-home"]
        rehearsal.containers[home] = rehearsal.container(home)
    result = rehearsal.run()
    assert result.returncode == 0, result.stderr
    expected = [("stop", home), ("stop", "cliproxy")]
    if home == "cliproxy-home-bootstrap":
        expected.append(("disconnect", home))
    assert rehearsal.effects() == expected
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


def test_remove_bootstrap_refuses_a_running_bootstrap(rehearsal):
    del rehearsal.containers["cliproxy-home"]
    rehearsal.containers["cliproxy-home-bootstrap"] = rehearsal.container("cliproxy-home-bootstrap")
    result = rehearsal.run("remove-bootstrap")
    assert result.returncode != 0
    assert rehearsal.effects() == []


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
    script = rehearsal.root / "scripts/maintenance.sh"
    script.parent.mkdir()
    # Local git revision stays tied to the actual checkout, while remote paths
    # are the only production inputs replaced for this controlled rehearsal.
    script.write_text(SCRIPT.read_text().replace("/data/overmind/cliproxy", str(data))
                      .replace("/backups/overmind/cliproxy", str(backups))
                      .replace('git -C "$(dirname "$0")/.."', f'git -C "{SCRIPT.parents[1]}"'))
    try:
        yield rehearsal, script, data, backups
    finally:
        shutil.rmtree(data)
        shutil.rmtree(backups)


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
