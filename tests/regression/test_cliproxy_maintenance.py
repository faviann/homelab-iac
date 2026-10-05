"""Execute the human runbook with real flock and isolated SSH/Docker stand-ins.

These observations cover our ordering, scope and fail-closed decisions. Docker
shutdown, network behavior and CPA readiness require later real-image acceptance.
"""

from __future__ import annotations

import fcntl
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


RUNBOOK = Path(__file__).resolve().parents[2] / "docs/cliproxy-maintenance.md"

# A fixed interpreter and restricted PATH prevent accidental live SSH or Docker.
STAND_IN = f'''#!{sys.executable}
import json, os, subprocess, sys
from pathlib import Path

root = Path(os.environ["REHEARSAL_ROOT"])
name, args = Path(sys.argv[0]).name, sys.argv[1:]
with (root / "events.jsonl").open("a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
if name == "ssh":
    script = sys.stdin.read()
    # The documented remote directory is validated without entering a host path.
    prelude = 'cd() {{ [[ "$1" == /conf/docker/stacks/cliproxy ]]; }}\\n'
    result = subprocess.run(["bash", "-se"], input=prelude + script, text=True)
    raise SystemExit(result.returncode)

state = json.loads((root / "state.json").read_text())
fail = state.get("fail")
if args[:1] == ["info"]:
    raise SystemExit(1 if fail == "info" else 0)
if args[:2] == ["container", "ls"]:
    if fail == "ls":
        raise SystemExit(1)
    print("\\n".join(state["containers"]))
elif args[:2] == ["container", "inspect"]:
    container = args[-1]
    if fail == "inspect:" + container:
        raise SystemExit(1)
    item = state["containers"][container]
    if ".NetworkSettings" in args[3]:
        print("\\n".join(item.get("networks", [])))
    else:
        status = item["status"]
        print("|".join([item["project"], item["service"], status,
                        "true" if status in ("running", "paused", "restarting") else "false"]))
elif args[:2] == ["container", "stop"]:
    container = args[-1]
    if fail == "stop:" + container:
        raise SystemExit(1)
    if fail != "survives:" + container:
        state["containers"][container]["status"] = "exited"
elif args[:2] == ["network", "disconnect"]:
    if fail == "detach":
        raise SystemExit(1)
    if fail != "attached":
        state["containers"][args[-1]]["networks"].remove(args[-2])
elif args[:2] == ["container", "rm"]:
    container = args[-1]
    if state["containers"][container]["status"] == "running":
        raise SystemExit("attempted removal of a writer")
    del state["containers"][container]
elif args[:2] == ["container", "start"]:
    if fail != "start":
        state["containers"][args[-1]]["status"] = "running"
else:
    raise SystemExit("unapproved Docker operation: " + repr(args))
(root / "state.json").write_text(json.dumps(state))
'''


def documented_block(name: str) -> str:
    text = RUNBOOK.read_text()
    match = re.search(rf"<!-- rehearsal: {name} -->\n```bash\n(.*?)\n```", text, re.S)
    assert match, f"missing executable rehearsal block {name}"
    return match[1]


class Rehearsal:
    def __init__(self, root: Path):
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        self.home = root / "home"
        (self.home / ".ansible").mkdir(parents=True)
        for command in ("bash", "flock", "timeout"):
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
        return {
            "project": "" if bootstrap else "cliproxy",
            "service": "" if bootstrap else name,
            "status": status,
            "networks": ["cliproxy_default"] if bootstrap else [],
        }

    def run(self, action="maintenance", *, fail=""):
        (self.root / "state.json").write_text(
            json.dumps({"containers": self.containers, "fail": fail})
        )
        script = documented_block("maintenance")
        if action != "maintenance":
            script = script.replace(
                "stop_all_writers\ndetach_bootstrap\nREMOTE",
                documented_block(action) + "\nREMOTE",
            )
        return subprocess.run(
            ["bash", "-se"],
            input=script,
            text=True,
            capture_output=True,
            timeout=10,
            env={
                "PATH": str(self.bin),
                "HOME": str(self.home),
                "REHEARSAL_ROOT": str(self.root),
            },
        )

    def events(self):
        log = self.root / "events.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def effects(self):
        return [
            event for event in self.events()
            if event[:3] in (
                ["docker", "container", "stop"],
                ["docker", "container", "start"],
                ["docker", "container", "rm"],
                ["docker", "network", "disconnect"],
            )
        ]


@pytest.fixture
def rehearsal(tmp_path):
    return Rehearsal(tmp_path)


def test_contended_existing_lock_performs_no_ssh_or_docker(rehearsal):
    lock = rehearsal.home / ".ansible/homelab-iac-lifecycle.lock"
    with lock.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = rehearsal.run()
    assert result.returncode == 75
    assert rehearsal.events() == []


@pytest.mark.parametrize("temporary", [False, True])
def test_offline_stops_home_before_cpa_and_observes_exits(rehearsal, temporary):
    home = "cliproxy-home-bootstrap" if temporary else "cliproxy-home"
    if temporary:
        del rehearsal.containers["cliproxy-home"]
        rehearsal.containers[home] = rehearsal.container(home)
    result = rehearsal.run()
    assert result.returncode == 0, result.stderr
    effects = rehearsal.effects()
    expected = [
        ["docker", "container", "stop", "--time", "30", home],
        ["docker", "container", "stop", "--time", "30", "cliproxy"],
    ]
    if temporary:
        expected += [["docker", "network", "disconnect", "cliproxy_default", home]]
    assert effects == expected
    # A stop's return status alone is insufficient: state is observed afterwards.
    events = rehearsal.events()
    for stop in expected[:2]:
        index = events.index(stop)
        assert events[index + 1][:3] == ["docker", "container", "inspect"]
        assert events[index + 1][-1] == stop[-1]
    assert all(
        item["status"] == "exited"
        for item in json.loads((rehearsal.root / "state.json").read_text())["containers"].values()
    )


def test_standalone_allows_absent_optional_home_and_bootstrap(rehearsal):
    del rehearsal.containers["cliproxy-home"]
    result = rehearsal.run()
    assert result.returncode == 0, result.stderr
    assert rehearsal.effects() == [["docker", "container", "stop", "--time", "30", "cliproxy"]]


@pytest.mark.parametrize("fail", ["info", "ls", "inspect:cliproxy-home", "inspect:cliproxy"])
def test_unavailable_docker_or_failed_inspection_is_not_absence(rehearsal, fail):
    result = rehearsal.run(fail=fail)
    assert result.returncode != 0
    assert rehearsal.effects() == []


@pytest.mark.parametrize("fail", ["stop:cliproxy-home", "survives:cliproxy-home"])
def test_home_stop_failure_or_remaining_writer_prevents_cpa_stop(rehearsal, fail):
    result = rehearsal.run(fail=fail)
    assert result.returncode != 0
    assert rehearsal.effects() == [["docker", "container", "stop", "--time", "30", "cliproxy-home"]]


@pytest.mark.parametrize("action", ["maintenance", "home-remove", "emergency"])
def test_cpa_remaining_writer_prevents_detach_removal_or_restart(rehearsal, action):
    rehearsal.containers["cliproxy-home-bootstrap"] = rehearsal.container("cliproxy-home-bootstrap", "exited")
    result = rehearsal.run(action, fail="survives:cliproxy")
    assert result.returncode != 0
    assert all(event[2] == "stop" for event in rehearsal.effects())


@pytest.mark.parametrize("status", ["paused", "restarting", "dead"])
def test_unexpected_writer_state_aborts_before_effects(rehearsal, status):
    rehearsal.containers["cliproxy-home"]["status"] = status
    result = rehearsal.run()
    assert result.returncode != 0
    assert rehearsal.effects() == []


@pytest.mark.parametrize("fault", ["two-home", "wrong-project", "missing-cpa"])
def test_unexpected_ownership_or_missing_cpa_aborts_before_effects(rehearsal, fault):
    if fault == "two-home":
        rehearsal.containers["cliproxy-home-bootstrap"] = rehearsal.container("cliproxy-home-bootstrap")
    elif fault == "wrong-project":
        rehearsal.containers["cliproxy"]["project"] = "unrelated"
    else:
        del rehearsal.containers["cliproxy"]
    result = rehearsal.run()
    assert result.returncode != 0
    assert rehearsal.effects() == []


@pytest.mark.parametrize("action,removed", [
    ("maintenance", []),
    ("bootstrap-remove", ["cliproxy-home-bootstrap"]),
    ("home-remove", ["cliproxy-home-bootstrap", "cliproxy-home"]),
])
def test_cleanup_is_named_and_bootstrap_retained_until_acceptance(rehearsal, action, removed):
    rehearsal.containers["cliproxy-home-bootstrap"] = rehearsal.container("cliproxy-home-bootstrap", "exited")
    rehearsal.containers["unrelated"] = rehearsal.container("unrelated")
    result = rehearsal.run(action)
    assert result.returncode == 0, result.stderr
    assert [event[-1] for event in rehearsal.effects() if event[2] == "rm"] == removed
    state = json.loads((rehearsal.root / "state.json").read_text())["containers"]
    assert state["unrelated"]["status"] == "running"
    expected_status = "running" if action == "bootstrap-remove" else "exited"
    assert state["cliproxy"]["status"] == expected_status
    if action == "bootstrap-remove":
        assert state["cliproxy-home"]["status"] == "running"
        assert not any(event[2] == "stop" for event in rehearsal.effects())
    assert [event for event in rehearsal.effects() if event[2] == "disconnect"] == [
        ["docker", "network", "disconnect", "cliproxy_default", "cliproxy-home-bootstrap"]
    ]


@pytest.mark.parametrize("fail", ["detach", "attached"])
def test_failed_or_ineffective_detach_prevents_removal(rehearsal, fail):
    rehearsal.containers["cliproxy-home-bootstrap"] = rehearsal.container("cliproxy-home-bootstrap", "exited")
    result = rehearsal.run("bootstrap-remove", fail=fail)
    assert result.returncode != 0
    assert not any(event[2] in ("rm", "start") for event in rehearsal.effects())


def test_emergency_restart_interrupts_only_cpa_and_verifies_restart(rehearsal):
    result = rehearsal.run("emergency")
    assert result.returncode == 0, result.stderr
    assert rehearsal.effects() == [
        ["docker", "container", "stop", "--time", "30", "cliproxy"],
        ["docker", "container", "start", "cliproxy"],
    ]
    result = rehearsal.run("emergency", fail="start")
    assert result.returncode != 0


def test_documented_stop_and_client_deadlines_are_applied(rehearsal):
    # Record actual timeout invocations, delegating to the real local utility.
    real_timeout = shutil.which("timeout")
    shim = rehearsal.bin / "timeout"
    shim.unlink()
    shim.write_text(
        f"#!{sys.executable}\nimport json, os, sys\n"
        "from pathlib import Path\n"
        "with (Path(os.environ['REHEARSAL_ROOT']) / 'deadlines.jsonl').open('a') as log:\n"
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"os.execv({real_timeout!r}, [{real_timeout!r}, *sys.argv[1:]])\n"
    )
    shim.chmod(0o755)
    result = rehearsal.run()
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in (rehearsal.root / "deadlines.jsonl").read_text().splitlines()]
    assert calls[0][:4] == ["--signal=TERM", "--kill-after=5s", "180s", "ssh"]
    stops = [call for call in calls if call[4:6] == ["container", "stop"]]
    assert len(stops) == 2
    assert all(call[:7] == ["--signal=TERM", "--kill-after=5s", "40s", "docker", "container", "stop", "--time"] for call in stops)
    assert all(call[:3] == ["--signal=TERM", "--kill-after=5s", "10s"] for call in calls[1:] if call not in stops)


def test_bootstrap_cleanup_rejects_running_writer_and_unexpected_network(rehearsal):
    rehearsal.containers["cliproxy-home-bootstrap"] = rehearsal.container("cliproxy-home-bootstrap")
    result = rehearsal.run("bootstrap-remove")
    assert result.returncode != 0
    assert rehearsal.effects() == []
    rehearsal.containers["cliproxy-home-bootstrap"]["status"] = "exited"
    rehearsal.containers["cliproxy-home-bootstrap"]["networks"] = ["unrelated-network"]
    result = rehearsal.run("bootstrap-remove")
    assert result.returncode != 0
    assert rehearsal.effects() == []
