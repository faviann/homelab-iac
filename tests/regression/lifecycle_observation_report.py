"""Require execution evidence from the fixture's assertion callbacks."""

from __future__ import annotations

import json
import subprocess


def assert_observations_completed(
    result: subprocess.CompletedProcess[str], names: tuple[str, ...]
) -> None:
    """Require exactly one passing assertion event per expected name."""
    evidence = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    if result.returncode:
        raise AssertionError(
            f"execution proof failed: ansible-playbook exited {result.returncode}; "
            f"expected {names!r}. {evidence}"
        )
    try:
        observations = json.loads(result.stdout)
        assert isinstance(observations, list)
        assert all(
            isinstance(event, list)
            and len(event) == 2
            and isinstance(event[0], str)
            and event[1] in ("passed", "skipped", "failed", "unreachable")
            for event in observations
        )
    except (AssertionError, ValueError):
        raise AssertionError(
            f"execution proof failed: malformed assertion callback report; "
            f"expected {names!r}. {evidence}"
        ) from None

    for name in names:
        outcomes = [status for task_name, status in observations if task_name == name]
        if outcomes != ["passed"]:
            raise AssertionError(
                f"execution proof failed: {name!r} has no unique passing assertion "
                f"result (absent, ambiguous, skipped, failed, or unreachable). {evidence}"
            )
