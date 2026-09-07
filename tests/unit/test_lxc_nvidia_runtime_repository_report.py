"""Behavioral tests for NVIDIA runtime execution-proof reporting."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


LAUNCHER_PATH = (
    Path(__file__).resolve().parents[1]
    / "regression"
    / "test_lxc_nvidia_runtime_repository.py"
)
sys.path.insert(0, str(LAUNCHER_PATH.parent))
try:
    SPEC = importlib.util.spec_from_file_location(
        "nvidia_runtime_regression", LAUNCHER_PATH
    )
    assert SPEC is not None and SPEC.loader is not None
    launcher = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(launcher)
finally:
    sys.path.pop(0)


def completed(report: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["ansible-playbook"],
        returncode=0,
        stdout=json.dumps(report),
        stderr="",
    )


def test_launcher_uses_fixture_local_observation_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_environment: dict[str, Any] = {}

    def run(*args: object, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_environment.update(kwargs["env"])
        callback_path = Path(kwargs["env"]["ANSIBLE_CALLBACK_PLUGINS"])
        assert (callback_path / "lifecycle_observation.py").is_file()
        return completed({"plays": []})

    monkeypatch.setattr(launcher.subprocess, "run", run)

    launcher.run_isolated_playbook(launcher.PLAYBOOK, "fixture-tag")

    assert captured_environment["ANSIBLE_STDOUT_CALLBACK"] == "lifecycle_observation"
    assert "ansible.posix" not in captured_environment["ANSIBLE_STDOUT_CALLBACK"]


@pytest.mark.parametrize(
    "outcome", [{"skipped": True}, {"failed": True}, {"unreachable": True}]
)
def test_nonpassing_observation_fails_closed(outcome: dict[str, object]) -> None:
    task_name = "required semantic assertion"
    report = {
        "plays": [
            {
                "tasks": [
                    {
                        "task": {"name": task_name},
                        "hosts": {"localhost": outcome},
                    }
                ]
            }
        ]
    }

    with pytest.raises(AssertionError, match=task_name):
        launcher.assert_observation_completed(completed(report), task_name)


def test_structurally_incomplete_observation_fails_closed() -> None:
    task_name = "required semantic assertion"
    report = {
        "plays": [
            {
                "tasks": [
                    {
                        "task": {"name": task_name},
                        "hosts": {"localhost": {}},
                    }
                ]
            }
        ]
    }

    with pytest.raises(AssertionError, match=task_name):
        launcher.assert_observation_completed(completed(report), task_name)


def test_absent_observation_fails_closed() -> None:
    task_name = "required semantic assertion"

    with pytest.raises(AssertionError, match=task_name):
        launcher.assert_observation_completed(
            completed({"plays": [{"tasks": []}]}), task_name
        )


def passing_report() -> dict[str, object]:
    return {
        "plays": [{"tasks": [{
            "task": {"name": "required semantic assertion"},
            "hosts": {"localhost": {
                "action": "ansible.builtin.assert",
                "changed": False,
                "msg": "All assertions passed",
                "skipped": False,
                "failed": False,
                "unreachable": False,
            }},
        }]}]
    }


def test_unique_passing_assertion_is_accepted() -> None:
    launcher.assert_observation_completed(
        completed(passing_report()), "required semantic assertion"
    )


@pytest.mark.parametrize("second", ["passed", "skipped", "failed", "unreachable"])
def test_duplicate_or_conflicting_assertions_fail_closed(second: str) -> None:
    report = passing_report()
    duplicate = passing_report()["plays"][0]["tasks"][0]
    if second != "passed":
        duplicate["hosts"]["localhost"][second] = True
    report["plays"][0]["tasks"].append(duplicate)
    with pytest.raises(AssertionError, match="ambiguous"):
        launcher.assert_observation_completed(
            completed(report), "required semantic assertion"
        )


@pytest.mark.parametrize("report", [None, [], {"plays": None}, {"plays": [None]},
                                   {"plays": [{"tasks": None}]}])
def test_malformed_report_fails_closed(report: object) -> None:
    with pytest.raises(AssertionError, match="pinned JSON callback report"):
        launcher.assert_observation_completed(
            completed(report), "required semantic assertion"
        )


def test_duplicate_json_keys_fail_closed() -> None:
    result = completed(passing_report())
    result.stdout = result.stdout.replace('"failed": false', '"failed": true, "failed": false')
    with pytest.raises(AssertionError, match="pinned JSON callback report"):
        launcher.assert_observation_completed(result, "required semantic assertion")


def test_candidate_failure_overrides_passing_observation() -> None:
    result = completed(passing_report())
    result.returncode = 1
    with pytest.raises(AssertionError, match="exited 1"):
        launcher.assert_observation_completed(result, "required semantic assertion")
