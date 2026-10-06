"""The x-restart-on-change declaration contract read by stack sync."""

from __future__ import annotations

import posixpath
from typing import Any

import yaml
from ansible.errors import AnsibleFilterError


def restart_on_change_declarations(
    compose_sources: list[dict[str, str]], plan: dict[str, Any]
) -> list[dict[str, str]]:
    """Every declared {stack, service, path}, with path relative to the stack directory.

    compose_sources are the planner's {target_dir, content} entries; Compose files
    sit at the stack root, so target_dir is the stack directory.

    A declared path must be a file this stack syncs from the repo, so a declaration
    can neither reach outside the stack nor track a file only the app writes.
    """
    synced = {
        file["dest_path"] for file in plan.get("files_to_render", []) + plan.get("files_to_copy", [])
    }
    composes = [
        (source["target_dir"], yaml.safe_load(source["content"])) for source in compose_sources
    ]
    services: dict[str, set[str]] = {}
    for stack_dir, compose in composes:
        if isinstance(compose, dict) and isinstance(compose.get("services"), dict):
            services.setdefault(stack_dir, set()).update(compose["services"])

    declarations = []
    for stack_dir, compose in composes:
        stack = posixpath.basename(stack_dir)
        if not isinstance(compose, dict) or "x-restart-on-change" not in compose:
            continue
        block = compose["x-restart-on-change"]

        def fail(message: str) -> AnsibleFilterError:
            return AnsibleFilterError(f"stack {stack}: x-restart-on-change {message}")

        if not isinstance(block, dict):
            raise fail("must map service names to lists of paths")
        for service, paths in block.items():
            if service not in services.get(stack_dir, set()):
                raise fail(f"names unknown service {service}")
            if not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths):
                raise fail(f"{service} must be a list of paths")
            for path in paths:
                resolved = posixpath.normpath(posixpath.join(stack_dir, path))
                if not resolved.startswith(stack_dir + "/") or resolved not in synced:
                    raise fail(f"path {path} is not a file the stack syncs from the repo")
                declarations.append({
                    "stack": stack,
                    "service": service,
                    "path": posixpath.relpath(resolved, stack_dir),
                })
    return declarations


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {"restart_on_change_declarations": restart_on_change_declarations}
