"""The shared assertion reader fails closed on missing or ambiguous evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "regression"))
try:
    from lifecycle_observation_report import assert_observations_completed
finally:
    sys.path.pop(0)


def completed(report: object, *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["ansible-playbook"],
        returncode=returncode,
        stdout=json.dumps(report),
        stderr="",
    )


def test_every_required_assertion_must_pass_once() -> None:
    result = completed([["first", "passed"], ["second", "passed"]])
    assert_observations_completed(result, ("first", "second"))
    with pytest.raises(AssertionError, match="missing"):
        assert_observations_completed(result, ("first", "second", "missing"))


@pytest.mark.parametrize("events", [
    [],
    [["other", "passed"]],
    [["required", "skipped"]],
    [["required", "failed"]],
    [["required", "unreachable"]],
    [["required", "passed"], ["required", "passed"]],
    [["required", "passed"], ["required", "skipped"]],
    [["required", "passed"], ["required", "failed"]],
    [["required", "passed"], ["required", "unreachable"]],
])
def test_absent_nonpassing_or_ambiguous_assertions_fail(events: object) -> None:
    with pytest.raises(AssertionError, match="no unique passing assertion"):
        assert_observations_completed(completed(events), ("required",))


@pytest.mark.parametrize("report", [
    None, {}, "text", [None], [[]], [["required"]],
    [["required", "passed", "extra"]], [[1, "passed"]],
    [["required", True]], [["required", "unknown"]],
    [["required", "passed"], {}],
])
def test_malformed_evidence_fails_even_with_a_passing_assertion(report: object) -> None:
    with pytest.raises(AssertionError, match="malformed assertion callback report"):
        assert_observations_completed(completed(report), ("required",))


@pytest.mark.parametrize("stdout", [
    "not json", '[ ["required", "passed"]',
    '[["required", "passed"]] []',
    'preamble\n[["required", "passed"]]',
])
def test_stdout_must_be_one_complete_machine_report(stdout: str) -> None:
    result = completed([])
    result.stdout = stdout
    with pytest.raises(AssertionError, match="malformed assertion callback report"):
        assert_observations_completed(result, ("required",))


def test_candidate_failure_overrides_passing_assertion() -> None:
    with pytest.raises(AssertionError, match="exited 1"):
        assert_observations_completed(
            completed([["required", "passed"]], returncode=1), ("required",)
        )
