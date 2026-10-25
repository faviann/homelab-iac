#!/usr/bin/env python3
"""Sign in to Authentik once, then GET each URL with that session, following redirects.

Prints one probe-format line per URL and exits 0 when every URL passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from urllib import error, parse, request

MAX_REDIRECTS = 15
TIMEOUT_SECONDS = 15
SIGN_IN_FLOW = "default-authentication-flow"
SIGNED_IN = "xak-flow-redirect"
SIGN_IN_ANSWERS = {
    "ak-stage-identification": lambda username, password: {"uid_field": username},
    "ak-stage-password": lambda username, password: {"password": password},
}
# Short cookie values are flags such as a language, not credentials. Scrubbing
# them would rewrite ordinary text in the line.
MIN_SECRET_LENGTH = 8
SIGN_IN_PATHS = ("/flows/", "/if/flow/")


@dataclass(frozen=True)
class Outcome:
    url: str
    status: int
    final_url: str
    hops: tuple[str, ...]
    elapsed: float
    location: str
    content_type: str
    detail: str
    body: str


def without_query(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0]


def passed(outcome: Outcome, auth_host: str) -> bool:
    final = parse.urlsplit(outcome.final_url)
    on_sign_in = final.hostname == auth_host and final.path.startswith(SIGN_IN_PATHS)
    return 200 <= outcome.status < 300 and not on_sign_in


def format_line(outcome: Outcome, auth_host: str) -> str:
    verdict = "PASS" if passed(outcome, auth_host) else "FAIL"
    return (
        f"{verdict} {outcome.url} status={outcome.status} elapsed={int(outcome.elapsed)}s"
        f" location={outcome.location} content_type={outcome.content_type}"
        f" detail={json.dumps(outcome.detail)} hops={','.join(outcome.hops) or '-'}"
        f" body={' '.join(outcome.body.split())[:160]}"
    )


def scrub(text: str, secrets: Iterable[str]) -> str:
    for secret in sorted({s for s in secrets if len(s) >= MIN_SECRET_LENGTH}, key=len, reverse=True):
        text = text.replace(secret, "<redacted>")
    return text


class _NoRedirects(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def open_once(opener: request.OpenerDirector, url: str, answer: dict | None = None):
    data = None if answer is None else json.dumps(answer).encode()
    headers = {} if answer is None else {"Content-Type": "application/json"}
    try:
        sent = request.Request(url, data=data, headers=headers)
        with opener.open(sent, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.headers, response.read(), response.reason
    except error.HTTPError as response:
        with response:
            return response.code, response.headers, response.read(), response.reason


def challenge(opener: request.OpenerDirector, url: str, answer: dict | None = None) -> dict:
    status, headers, body, _ = open_once(opener, url, answer)
    for _ in range(MAX_REDIRECTS):
        location = headers.get("Location")
        if not (300 <= status < 400 and location):
            break
        status, headers, body, _ = open_once(opener, parse.urljoin(url, location))
    return json.loads(body)


def sign_in(opener: request.OpenerDirector, auth_url: str, username: str, password: str) -> str | None:
    """Return None once signed in, else why the flow stopped."""
    executor = f"{auth_url}/api/v3/flows/executor/{SIGN_IN_FLOW}/?query="
    answered: set[str] = set()
    current = challenge(opener, executor)
    while current.get("component") != SIGNED_IN:
        component = current.get("component")
        answer = SIGN_IN_ANSWERS.get(component)
        if answer is None or component in answered:
            errors = current.get("response_errors")
            return f"sign-in stopped at {component}" + (f" {json.dumps(errors)}" if errors else "")
        answered.add(component)
        current = challenge(opener, executor, {"component": component, **answer(username, password)})
    return None


def walk(opener: request.OpenerDirector, url: str) -> Outcome:
    started = time.monotonic()
    hops: list[str] = []
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            status, headers, body, reason = open_once(opener, current)
            hops.append(f"{status}:{without_query(current)}")
            location = headers.get("Location")
            if not (300 <= status < 400 and location):
                break
            current = parse.urljoin(current, location)
        else:
            reason = f"more than {MAX_REDIRECTS} redirects"
    except (OSError, http.client.HTTPException) as exc:
        return Outcome(
            url, -1, current, tuple(hops), time.monotonic() - started, "-", "-", f"Request failed: {exc}", ""
        )
    return Outcome(
        url=url,
        status=status,
        final_url=current,
        hops=tuple(hops),
        elapsed=time.monotonic() - started,
        location=without_query(location) if location else "-",
        content_type=headers.get("Content-Type", "-"),
        detail=reason,
        body=body.decode("utf-8", errors="replace"),
    )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", required=True, type=Path)
    parser.add_argument("urls", nargs="+")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    password = args.password_file.read_text(encoding="utf-8").strip()
    auth_host = parse.urlsplit(args.auth_url).hostname
    jar = CookieJar()
    opener = request.build_opener(request.HTTPCookieProcessor(jar), _NoRedirects())

    try:
        failure = sign_in(opener, args.auth_url, args.username, password)
    except (OSError, http.client.HTTPException, ValueError) as exc:
        failure = f"sign-in failed: {exc}"
    if failure is None:
        outcomes = [walk(opener, url) for url in args.urls]
    else:
        outcomes = [
            Outcome(url, -1, url, (), 0, "-", "-", f"not walked: {failure}", "") for url in args.urls
        ]

    secrets = [password, *(cookie.value for cookie in jar if cookie.value)]
    print("\n".join(scrub(format_line(outcome, auth_host), secrets) for outcome in outcomes))
    return 0 if all(passed(outcome, auth_host) for outcome in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
