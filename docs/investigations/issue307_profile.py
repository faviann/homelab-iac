"""Minimal callback for issue #307 attributable task timing."""

from __future__ import annotations

import json
import time
from collections import defaultdict

from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "issue307_profile"
    CALLBACK_NEEDS_WHITELIST = False

    def __init__(self):
        super().__init__()
        self._task_started = {}
        self._plays = []
        self._events = []

    def v2_playbook_on_play_start(self, play):
        self._plays.append({"name": play.get_name(), "started": time.monotonic()})

    def v2_playbook_on_play_end(self, play):
        if self._plays and self._plays[-1]["name"] == play.get_name():
            self._plays[-1]["ended"] = time.monotonic()

    def v2_playbook_on_task_start(self, task, is_conditional):
        self._task_started[task._uuid] = {
            "name": task.get_name(),
            "started": time.monotonic(),
            "play": self._plays[-1]["name"] if self._plays else "<unknown>",
        }

    def _record(self, result, status):
        task = self._task_started.get(result._task._uuid, {})
        started = task.get("started", time.monotonic())
        item = result._result.get("item")
        self._events.append(
            {
                "play": task.get("play", "<unknown>"),
                "task": task.get("name", result._task.get_name()),
                "status": status,
                "item": str(item) if item is not None else None,
                "seconds_from_task_start": round(time.monotonic() - started, 6),
            }
        )

    def v2_runner_on_ok(self, result):
        self._record(result, "ok")

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._record(result, "failed")

    def v2_runner_on_unreachable(self, result):
        self._record(result, "unreachable")

    def v2_runner_on_skipped(self, result):
        self._record(result, "skipped")

    def v2_runner_item_on_ok(self, result):
        self._record(result, "item_ok")

    def v2_runner_item_on_failed(self, result):
        self._record(result, "item_failed")

    def v2_runner_item_on_skipped(self, result):
        self._record(result, "item_skipped")

    def v2_playbook_on_stats(self, stats):
        print(
            "ISSUE307_PROFILE "
            + json.dumps({"plays": self._plays, "events": self._events}, sort_keys=True)
        )
