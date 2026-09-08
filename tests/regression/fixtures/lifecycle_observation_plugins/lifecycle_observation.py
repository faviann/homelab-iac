"""Fixture-local stdout callback for lifecycle semantic observations."""

from __future__ import annotations

import json
from typing import Any

from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):
    """Emit only the task identity and outcome data the launchers consume."""

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "stdout"
    CALLBACK_NAME = "lifecycle_observation"

    def __init__(self) -> None:
        super().__init__()
        self._assertions: list[list[str]] = []

    def _record(self, result: Any, status: str) -> None:
        if result._task.action == "ansible.builtin.assert":
            self._assertions.append([result._task.get_name(), status])

    def v2_runner_on_ok(self, result: Any) -> None:
        self._record(result, "passed")

    def v2_runner_on_failed(self, result: Any, ignore_errors: bool = False) -> None:
        del ignore_errors
        self._record(result, "failed")

    def v2_runner_on_skipped(self, result: Any) -> None:
        self._record(result, "skipped")

    def v2_runner_on_unreachable(self, result: Any) -> None:
        self._record(result, "unreachable")

    def v2_playbook_on_stats(self, stats: Any) -> None:
        del stats
        self._display.display(json.dumps(self._assertions))
