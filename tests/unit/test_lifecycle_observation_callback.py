"""Exercise execution proof through the actual callback and its report reader."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REGRESSION_ROOT = Path(__file__).resolve().parents[1] / "regression"
sys.path.insert(0, str(REGRESSION_ROOT))
try:
    from lifecycle_observation_report import assert_observations_completed
finally:
    sys.path.pop(0)

CALLBACK_PATH = (
    REGRESSION_ROOT / "fixtures/lifecycle_observation_plugins/lifecycle_observation.py"
)
SPEC = importlib.util.spec_from_file_location("assertion_callback", CALLBACK_PATH)
assert SPEC is not None and SPEC.loader is not None
callback_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(callback_module)


@pytest.mark.parametrize("action,events,passes", [
    ("ansible.builtin.assert", ("ok",), True),
    ("ansible.builtin.debug", ("ok",), False),
    ("ansible.builtin.assert", ("skipped",), False),
    ("ansible.builtin.assert", ("failed",), False),
    ("ansible.builtin.assert", ("unreachable",), False),
    ("ansible.builtin.assert", ("ok", "skipped"), False),
])
def test_callback_events_prove_only_unique_passing_assertions(
    monkeypatch: pytest.MonkeyPatch, action: str, events: tuple[str, ...], passes: bool
) -> None:
    callback = callback_module.CallbackModule()
    output = []
    monkeypatch.setattr(callback._display, "display", output.append)
    result = SimpleNamespace(
        _task=SimpleNamespace(action=action, get_name=lambda: "required"),
    )
    for event in events:
        handler = getattr(callback, f"v2_runner_on_{event}")
        if event == "failed":
            handler(result, ignore_errors=True)
        else:
            handler(result)
    callback.v2_playbook_on_stats(None)
    process = subprocess.CompletedProcess(
        args=["ansible-playbook"], returncode=0, stdout="\n".join(output), stderr=""
    )
    if passes:
        assert_observations_completed(process, ("required",))
    else:
        with pytest.raises(AssertionError, match="no unique passing assertion"):
            assert_observations_completed(process, ("required",))
