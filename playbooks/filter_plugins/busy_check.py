"""The x-busy-check declaration contract, shared by stack validation and the lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

import yaml


COMPOSE_FILES = ("compose.yaml", "compose.yml", "compose.override.yaml", "compose.override.yml")
KEYS = {"service", "command", "timeout"}
MAX_TIMEOUT = 60


class BusyCheckError(NamedTuple):
    path: str
    message: str


class _ComposeLoader(yaml.SafeLoader):
    pass


def _untagged(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


# Compose's own tags (!reset, !override) are valid and must not make a stack unreadable.
_ComposeLoader.add_multi_constructor("!", _untagged)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def read_busy_check(stack_dir: Path) -> dict[str, Any] | BusyCheckError | None:
    """Return the stack's normalized declaration, None when it has none, or why it is invalid."""
    for template in sorted(stack_dir.glob("compose*.j2")):
        if "x-busy-check" in template.read_text(encoding="utf-8", errors="replace"):
            return BusyCheckError(
                "compose.x-busy-check",
                f"x-busy-check is not supported in a template ({template.name})",
            )
    services: set[str] = set()
    blocks = []
    for name in COMPOSE_FILES:
        path = stack_dir / name
        if not path.is_file():
            continue
        try:
            loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader)
        except (OSError, UnicodeError, yaml.YAMLError):
            return BusyCheckError("compose", f"{name} could not be read as YAML")
        if not isinstance(loaded, dict):
            continue
        if isinstance(loaded.get("services"), dict):
            services.update(loaded["services"])
        if "x-busy-check" in loaded:
            blocks.append(loaded["x-busy-check"])
    if not blocks:
        return None
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
    return {"stack": stack_dir.name, "service": block["service"], "command": command, "timeout": timeout}


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


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {"busy_check_declarations": busy_check_declarations}
