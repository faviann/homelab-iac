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
        for command in ("bash", "flock", "timeout", "grep", "sed"):
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

    def run(self, action="stop", *, fail=""):
        self.state_file.write_text(json.dumps({"containers": self.containers, "fail": fail}))
        return subprocess.run(
            [str(self.bin / "bash"), str(SCRIPT), action],
            text=True,
            capture_output=True,
            timeout=30,
            env={"PATH": str(self.bin), "HOME": str(self.home), "REHEARSAL_ROOT": str(self.root)},
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
