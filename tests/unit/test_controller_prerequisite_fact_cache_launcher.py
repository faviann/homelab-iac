"""Public invocation coverage for the controller prerequisite cache fixture."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml


LAUNCHER_PATH = (
    Path(__file__).resolve().parents[1]
    / "regression"
    / "test_controller_prerequisite_fact_cache.py"
)
sys.path.insert(0, str(LAUNCHER_PATH.parent))
try:
    SPEC = importlib.util.spec_from_file_location(
        "controller_prerequisite_cache_regression", LAUNCHER_PATH
    )
    assert SPEC is not None and SPEC.loader is not None
    launcher = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(launcher)
finally:
    sys.path.pop(0)


def test_launcher_injects_fixture_local_empty_collection_requirements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured_command: list[str] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_command.extend(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(launcher.subprocess, "run", run)

    launcher.run_prerequisites(tmp_path / "cache")

    injected = (
        f"control_node_collection_requirements="
        f"{launcher.FIXTURE_COLLECTION_REQUIREMENTS}"
    )
    assert injected in captured_command
    assert yaml.safe_load(
        launcher.FIXTURE_COLLECTION_REQUIREMENTS.read_text(encoding="utf-8")
    ) == {"collections": []}
    assert str(launcher.REPO_ROOT / "collections" / "requirements.yml") not in (
        captured_command
    )
