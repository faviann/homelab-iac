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
        self._tasks: list[dict[str, Any]] = []

    def _record(self, result: Any, status: str) -> None:
        task = result._task
        outcome = {
            "action": task.action,
            "changed": bool(result._result.get("changed", False)),
            "failed": status == "failed",
            "skipped": status == "skipped",
            "unreachable": status == "unreachable",
        }
        if "msg" in result._result:
            outcome["msg"] = result._result["msg"]
        self._tasks.append(
            {
                "task": {"name": task.get_name()},
                "hosts": {result._host.get_name(): outcome},
            }
        )

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
        self._display.display(json.dumps({"plays": [{"tasks": self._tasks}]}))
