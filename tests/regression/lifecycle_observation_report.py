"""Read the fixture callback's execution evidence for single-host assertions."""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from typing import Any


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate observation key: {key}")
        result[key] = value
    return result


def assert_observations_completed(
    result: subprocess.CompletedProcess[str], names: tuple[str, ...]
) -> None:
    """Require exactly one canonical passing assertion result per expected name."""
    evidence = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    if result.returncode:
        raise AssertionError(
            f"execution proof failed: ansible-playbook exited {result.returncode}; "
            f"expected {names!r}. {evidence}"
        )
    observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        report = json.loads(result.stdout, object_pairs_hook=_unique_keys)
        assert isinstance(report, dict) and set(report) == {"plays"}
        assert isinstance(report["plays"], list)
        for play in report["plays"]:
            assert isinstance(play, dict) and set(play) == {"tasks"}
            assert isinstance(play["tasks"], list)
            for task in play["tasks"]:
                assert isinstance(task, dict) and set(task) == {"task", "hosts"}
                assert isinstance(task["task"], dict)
                name = task["task"]["name"]
                assert isinstance(name, str)
                assert isinstance(task["hosts"], dict) and len(task["hosts"]) == 1
                outcome = next(iter(task["hosts"].values()))
                assert isinstance(outcome, dict)
                observations[name].append(outcome)
    except (AssertionError, ValueError, KeyError, TypeError):
        raise AssertionError(
            f"execution proof failed: not the pinned JSON callback report; "
            f"expected {names!r}. {evidence}"
        ) from None

    for name in names:
        outcomes = observations[name]
        if len(outcomes) == 1:
            outcome = outcomes[0]
            if (
                outcome.get("action") == "ansible.builtin.assert"
                and outcome.get("changed") is False
                and outcome.get("msg") == "All assertions passed"
                and all(outcome.get(flag) is False for flag in (
                    "skipped", "failed", "unreachable"
                ))
            ):
                continue
        raise AssertionError(
            f"execution proof failed: {name!r} has no unique passing assertion "
            f"result (absent, ambiguous, incomplete, skipped, failed, or unreachable). "
            f"{evidence}"
        )
