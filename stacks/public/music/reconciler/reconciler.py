#!/usr/bin/env python3
"""Synchronize Authentik media users into Navidrome."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from urllib import error, parse, request


LOGGER = logging.getLogger("navidrome-reconciler")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _json_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout: int = 15,
) -> Any:
    body = None
    request_headers = {"Accept": "application/json", **headers}
    if payload is not None:
                request_headers["Content-Type"] = "application/json"
                body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_body = response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {detail}") from exc
    if not response_body:
        return None
    return json.loads(response_body)


def _paginated_get(url: str, *, headers: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    next_url = url
    while next_url:
        payload = _json_request("GET", next_url, headers=headers)
        if isinstance(payload, dict) and "results" in payload:
            results.extend(payload["results"])
            next_url = payload.get("next")
            continue
        if isinstance(payload, list):
            results.extend(payload)
            break
        raise RuntimeError(f"Unexpected response shape from {next_url!r}")
    return results


def _bearer_auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _navidrome_api_headers(base_url: str, username: str, password: str) -> dict[str, str]:
    payload = _json_request(
        "POST",
        f"{base_url.rstrip('/')}/auth/login",
        headers={},
        payload={"username": username, "password": password},
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected Navidrome /auth/login response shape")

    token = _clean(payload.get("token"))
    if not token:
        raise RuntimeError("Navidrome /auth/login did not return a token")

    return {
        "Accept": "application/json",
        "X-ND-Authorization": f"Bearer {token}",
    }


def _authentik_media_user(user: dict[str, Any]) -> bool:
    return any(group.get("name") == "media" for group in user.get("groups_obj", []))


def _resolve_disabled_field(user: dict[str, Any]) -> tuple[str, bool]:
    if "isDisabled" in user:
        return "isDisabled", bool(user.get("isDisabled", False))
    if "disabled" in user:
        return "disabled", bool(user.get("disabled", False))
    if "isActive" in user:
        return "isActive", not bool(user.get("isActive", True))
    return "isDisabled", False


def _resolve_admin_field(user: dict[str, Any]) -> tuple[str, bool]:
    if "isAdmin" in user:
        return "isAdmin", bool(user.get("isAdmin", False))
    if "admin" in user:
        return "admin", bool(user.get("admin", False))
    return "isAdmin", False


def _navidrome_username_map(users: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        _clean(user.get("userName")): user
        for user in users
        if _clean(user.get("userName"))
    }


def _build_update_payload(
    existing_user: dict[str, Any],
    *,
    email: str,
    disabled: bool | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    username = _clean(existing_user.get("userName"))
    admin_field, is_admin = _resolve_admin_field(existing_user)
    disabled_field, currently_disabled = _resolve_disabled_field(existing_user)
    payload: dict[str, Any] = {
        "userName": username,
        "email": email,
        admin_field: is_admin,
    }
    if disabled is None:
        payload[disabled_field] = currently_disabled if disabled_field != "isActive" else not currently_disabled
    else:
        payload[disabled_field] = (not disabled) if disabled_field == "isActive" else disabled
    if password is not None:
        payload["password"] = password
    return payload


def plan_reconciliation(
    authentik_users: list[dict[str, Any]],
    navidrome_users: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    navidrome_by_username = _navidrome_username_map(navidrome_users)
    operations: list[dict[str, Any]] = []

    for authentik_user in authentik_users:
        username = _clean(authentik_user.get("username"))
        if not username:
            continue
        should_enable = bool(authentik_user.get("is_active")) and _authentik_media_user(authentik_user)
        email = _clean(authentik_user.get("email"))
        existing_user = navidrome_by_username.get(username)

        if should_enable:
            if existing_user is None:
                operations.append(
                    {
                        "action": "create",
                        "username": username,
                        "payload": {
                            "userName": username,
                            "email": email,
                            "isAdmin": False,
                        },
                    }
                )
                continue

            _, is_disabled = _resolve_disabled_field(existing_user)
            existing_email = _clean(existing_user.get("email"))
            if is_disabled or existing_email != email:
                operations.append(
                    {
                        "action": "update",
                        "username": username,
                        "user_id": existing_user["id"],
                        "payload": _build_update_payload(existing_user, email=email, disabled=False),
                    }
                )
            continue

        if existing_user is None:
            continue

        _, is_disabled = _resolve_disabled_field(existing_user)
        if not is_disabled:
            operations.append(
                {
                    "action": "update",
                    "username": username,
                    "user_id": existing_user["id"],
                    "payload": _build_update_payload(existing_user, email=email, disabled=True),
                }
            )

    return operations


class AuthentikClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = _bearer_auth_header(token)

    def list_users(self) -> list[dict[str, Any]]:
        return _paginated_get(f"{self.base_url}/api/v3/core/users/?page_size=200", headers=self.headers)


class NavidromeClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

    def _headers(self) -> dict[str, str]:
        return _navidrome_api_headers(self.base_url, self.username, self.password)

    def list_users(self) -> list[dict[str, Any]]:
        payload = _json_request("GET", f"{self.base_url}/api/user", headers=self._headers())
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected Navidrome /api/user response shape")
        return payload

    def create_user(self, payload: dict[str, Any]) -> None:
        _json_request("POST", f"{self.base_url}/api/user", headers=self._headers(), payload=payload)

    def update_user(self, user_id: Any, payload: dict[str, Any]) -> None:
        quoted_user_id = parse.quote(str(user_id), safe="")
        _json_request(
            "PUT",
            f"{self.base_url}/api/user/{quoted_user_id}",
            headers=self._headers(),
            payload=payload,
        )


def sync_once(authentik_client: AuthentikClient, navidrome_client: NavidromeClient) -> None:
    operations = plan_reconciliation(authentik_client.list_users(), navidrome_client.list_users())
    if not operations:
        LOGGER.info("no Navidrome sync changes required")
        return

    for operation in operations:
        username = operation["username"]
        try:
            if operation["action"] == "create":
                navidrome_client.create_user(operation["payload"])
                LOGGER.info("created Navidrome user %s", username)
            elif operation["action"] == "update":
                navidrome_client.update_user(operation["user_id"], operation["payload"])
                disabled_field, is_disabled = _resolve_disabled_field(operation["payload"])
                if disabled_field == "isActive":
                    is_disabled = not bool(operation["payload"][disabled_field])
                LOGGER.info(
                    "%s Navidrome user %s",
                    "disabled" if is_disabled else "updated",
                    username,
                )
            else:
                raise RuntimeError(f"Unsupported action {operation['action']!r}")
        except Exception as exc:  # noqa: BLE001 - best-effort reconciler
            LOGGER.exception("failed to reconcile %s: %s", username, exc)


def load_config() -> dict[str, Any]:
    config = {
        "authentik_url": _clean(os.environ.get("AUTHENTIK_URL")),
        "authentik_token": _clean(os.environ.get("AUTHENTIK_TOKEN")),
        "navidrome_url": _clean(os.environ.get("NAVIDROME_URL")),
        "navidrome_admin_user": _clean(os.environ.get("NAVIDROME_ADMIN_USER")),
        "navidrome_admin_password": _clean(os.environ.get("NAVIDROME_ADMIN_PASSWORD")),
        "sync_interval_seconds": int(os.environ.get("SYNC_INTERVAL_SECONDS", "600")),
    }
    missing = [key for key, value in config.items() if key != "sync_interval_seconds" and not value]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(sorted(missing))}")
    return config


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = load_config()
    authentik_client = AuthentikClient(config["authentik_url"], config["authentik_token"])
    navidrome_client = NavidromeClient(
        config["navidrome_url"],
        config["navidrome_admin_user"],
        config["navidrome_admin_password"],
    )

    while True:
        try:
            sync_once(authentik_client, navidrome_client)
        except Exception as exc:  # noqa: BLE001 - keep the loop alive on partial failures
            LOGGER.exception("reconciliation loop failed: %s", exc)
        time.sleep(config["sync_interval_seconds"])


if __name__ == "__main__":
    raise SystemExit(main())