"""Filters for values rendered into Docker Compose-consumed files."""

from __future__ import annotations


def compose_env(value: object) -> str:
    """Escape values so Docker Compose preserves literal dollar signs."""
    return str(value).replace("$", "$$")


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {
            "compose_env": compose_env,
        }
