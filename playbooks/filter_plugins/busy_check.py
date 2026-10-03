"""The x-busy-check declaration contract read by the lifecycle."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, NamedTuple

import yaml


COMPOSE_FILES = ("compose.yaml", "compose.yml", "compose.override.yaml", "compose.override.yml")
KEYS = {"service", "command", "timeout"}
MAX_TIMEOUT = 60
# A top-level key at the start of a line is how a stack opts in.
DECLARATION = re.compile(r"^x-busy-check\s*:", re.MULTILINE)
PROBE_STATES = ("idle", "busy", "check_failed", "not_deployed")


class BusyCheckError(NamedTuple):
    path: str
    message: str


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def read_busy_check(stack_dir: Path) -> dict[str, Any] | BusyCheckError | None:
    """Return the stack's normalized declaration, None when it has none, or why it is invalid."""
    def declares(path: Path) -> bool:
        return bool(DECLARATION.search(path.read_text(encoding="utf-8", errors="replace")))

    # A stack that never opts in keeps its pre-feature path, even when its Compose files are broken.
    compose_paths = [stack_dir / name for name in COMPOSE_FILES if (stack_dir / name).is_file()]
    templates = sorted(stack_dir.glob("compose*.j2"))
    if not any(map(declares, compose_paths + templates)):
        return None
    for template in templates:
        if declares(template):
            return BusyCheckError(
                "compose.x-busy-check",
                f"x-busy-check is not supported in a template ({template.name})",
            )
    services: set[str] = set()
    blocks = []
    for path in compose_paths:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            return BusyCheckError("compose", f"{path.name} could not be read as YAML")
        if not isinstance(loaded, dict):
            continue
        if isinstance(loaded.get("services"), dict):
            services.update(loaded["services"])
        if "x-busy-check" in loaded:
            blocks.append(loaded["x-busy-check"])
    if not blocks:
        return BusyCheckError("compose.x-busy-check", "x-busy-check must be a top-level Compose key")
    if len(blocks) > 1:
        return BusyCheckError(
            "compose.x-busy-check", "x-busy-check must be declared in only one Compose file"
        )
    block = blocks[0]
    if not isinstance(block, dict) or set(block) != KEYS:
        return BusyCheckError(
            "compose.x-busy-check", "x-busy-check must contain only service, command, and timeout"
        )
    if not _nonempty_string(block["service"]) or block["service"] not in services:
        return BusyCheckError(
            "compose.x-busy-check.service", "service must name a service in the stack's Compose files"
        )
    command = block["command"]
    if not isinstance(command, list) or not command or not all(map(_nonempty_string, command)):
        return BusyCheckError(
            "compose.x-busy-check.command", "command must be a non-empty list of non-empty strings"
        )
    timeout = block["timeout"]
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT:
        return BusyCheckError(
            "compose.x-busy-check.timeout",
            f"timeout must be an integer number of seconds from 1 to {MAX_TIMEOUT}",
        )
    return {
        "stack": stack_dir.name,
        "service": block["service"],
        "command": command,
        "timeout": timeout,
    }


def busy_check_declarations(stacks_source: str) -> list[dict[str, Any]]:
    """Every declaring stack under a host's stack source, as a declaration or {stack, error}."""
    entries = []
    root = Path(stacks_source)
    for stack_dir in sorted(root.iterdir()) if root.is_dir() else ():
        if not stack_dir.is_dir():
            continue
        outcome = read_busy_check(stack_dir)
        if isinstance(outcome, BusyCheckError):
            entries.append({"stack": stack_dir.name, "error": f"{outcome.path}: {outcome.message}"})
        elif outcome is not None:
            entries.append(outcome)
    return entries


def _probe_outcome(probe: dict[str, Any]) -> tuple[str, str]:
    lines = probe.get("stdout_lines") or [""]
    if probe.get("unreachable"):
        return "check_failed", "guest unreachable"
    if probe.get("rc") != 0 or lines[0] not in PROBE_STATES:
        detail = probe.get("stderr", probe.get("msg", "")).strip()
        return "check_failed", "probe failed" + (f": {detail}" if detail else "")
    return lines[0], " ".join(lines[1:])


def busy_check_result(declarations: list[dict[str, Any]], probes: dict[str, Any]) -> dict[str, Any]:
    """The gate's result from parser entries and the probe task's registered loop result."""
    outcomes = [
        (entry["stack"], "check_failed", entry["error"]) for entry in declarations if "error" in entry
    ]
    outcomes += [(probe["item"]["stack"], *_probe_outcome(probe)) for probe in probes.get("results", [])]
    deferred = [
        {"stack": stack, "state": state, "reason": reason.strip()}
        for stack, state, reason in outcomes
        if state in ("busy", "check_failed")
    ]
    return {"deferred_stacks": deferred, "host_deferred": bool(deferred)}


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {
            "busy_check_declarations": busy_check_declarations,
            "busy_check_result": busy_check_result,
        }
