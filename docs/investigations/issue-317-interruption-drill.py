#!/usr/bin/env python3
"""Short, evidence-only interruption/cleanup drill for two child groups."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time


def run_children(
    children: dict[str, subprocess.Popen[str]],
    reason: str,
    interrupted: dict[str, str | None],
) -> dict[str, object]:
    actions: list[dict[str, str]] = []
    failure_phase = None
    while True:
        if reason == "interrupt" and interrupted["signal"] is None:
            time.sleep(0.05)
        for name, child in children.items():
            returncode = child.poll()
            if returncode is None:
                continue
            if (
                returncode != 0
                and failure_phase is None
                and interrupted["signal"] is None
            ):
                failure_phase = name
                for sibling_name, sibling in children.items():
                    if sibling_name != name and sibling.poll() is None:
                        os.killpg(sibling.pid, signal.SIGTERM)
                        actions.append({"phase": sibling_name, "signal": "SIGTERM"})
        if all(child.poll() is not None for child in children.values()):
            break
        if interrupted["signal"] is not None:
            for name, child in children.items():
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    actions.append({"phase": name, "signal": "SIGTERM"})
        time.sleep(0.05)
    for child in children.values():
        child.wait(timeout=2)
    remaining_groups = []
    for name, child in children.items():
        try:
            os.killpg(child.pid, 0)
        except ProcessLookupError:
            continue
        remaining_groups.append(name)
    return {
        "interrupted_signal": interrupted["signal"],
        "failure_phase": failure_phase,
        "returncodes": {name: child.returncode for name, child in children.items()},
        "termination_actions": actions,
        "all_children_awaited": True,
        "remaining_process_groups": remaining_groups,
        "cleanup_scope": "driver-started child process groups only",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=("failure", "interrupt"))
    scenario = parser.parse_args().scenario
    out = Path(f"/tmp/homelab-317/{scenario}-drill")
    out.mkdir(parents=True, exist_ok=True)
    if scenario == "failure":
        commands = {
            "failing-child": ["bash", "-c", "sleep 1; exit 7"],
            "failure-sibling": [
                "bash",
                "-c",
                "trap 'exit 143' TERM INT; sleep 30",
            ],
        }
    else:
        commands = {
            name: ["bash", "-c", "trap 'exit 143' TERM INT; sleep 30"]
            for name in ("first", "second")
        }
    children = {
        name: subprocess.Popen(
            command,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for name, command in commands.items()
    }
    interrupted = {"signal": None}

    def receive(signum: int, _frame: object) -> None:
        interrupted["signal"] = signal.Signals(signum).name

    signal.signal(signal.SIGTERM, receive)
    signal.signal(signal.SIGINT, receive)
    if scenario == "interrupt":
        threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
        summary = run_children(children, "interrupt", interrupted)
    else:
        summary = run_children(children, "failure", interrupted)
    summary["driver_scenario"] = scenario
    summary["interrupted_signal"] = interrupted["signal"]
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary))
    expected = (
        scenario == "interrupt"
        and interrupted["signal"] == "SIGTERM"
        and not summary["remaining_process_groups"]
    ) or (
        scenario == "failure"
        and summary["failure_phase"] == "failing-child"
        and not summary["remaining_process_groups"]
    )
    return 0 if expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
