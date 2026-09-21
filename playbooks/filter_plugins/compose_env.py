"""Filters for validating and rendering selected service credentials."""

from __future__ import annotations

from ansible.errors import AnsibleFilterError
from jinja2.runtime import Undefined


def credential_is_configured(value: object) -> bool:
    """Report whether a credential has a non-placeholder value."""
    if isinstance(value, Undefined):
        return False

    text = str(value)
    classification = text.strip()
    return not (
        not classification
        or classification in {"REPLACE_ME", "<REPLACE_ME>"}
        or classification.startswith("REPLACE_WITH_")
    )


def required_credential(value: object) -> str:
    """Return configured credential text without disclosing invalid values."""
    if not credential_is_configured(value):
        raise AnsibleFilterError("selected credential is missing or not configured")
    return str(value)


def compose_env(value: object) -> str:
    """Validate a credential and escape it for Docker Compose."""
    return required_credential(value).replace("$", "$$")


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {
            "compose_env": compose_env,
            "credential_is_configured": credential_is_configured,
            "required_credential": required_credential,
        }
