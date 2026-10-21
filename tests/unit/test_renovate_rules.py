#!/usr/bin/env python3
"""Renovate's own rule engine, at the deployed version, decides each case."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = Path(__file__).with_name("renovate_rule_outcomes.mjs")

CASES = {
    "sonarr patch": (
        "stacks/servarr/sonarr/compose.yaml", "lscr.io/linuxserver/sonarr", "patch",
        {"automerge": True, "schedule": ["* * * * 6"], "groupName": "stack images"},
    ),
    "sonarr digest": (
        "stacks/servarr/sonarr/compose.yaml", "lscr.io/linuxserver/sonarr", "digest",
        {"automerge": True},
    ),
    "seerr minor": (
        "stacks/jellyfin/seerr/compose.yaml", "ghcr.io/seerr-team/seerr", "minor",
        {"automerge": False},
    ),
    "authentik patch": (
        "stacks/auth/auth/.env.j2", "ghcr.io/goauthentik/server", "patch",
        {"automerge": True, "dependencyDashboardApproval": False, "schedule": ["at any time"]},
    ),
    "authentik minor": (
        "stacks/auth/auth/.env.j2", "ghcr.io/goauthentik/server", "minor",
        {"automerge": False, "dependencyDashboardApproval": True},
    ),
    "immich patch": (
        "stacks/public/immich/.env.j2", "ghcr.io/immich-app/immich-server", "patch",
        {"automerge": False},
    ),
    "traefik pinDigest": (
        "stacks/portal/traefik3/compose.yaml", "docker.io/library/traefik", "pinDigest",
        {"automerge": False, "dependencyDashboardApproval": True},
    ),
    "renovate patch": (
        "stacks/devserver/renovate/compose.yaml", "ghcr.io/renovatebot/renovate", "patch",
        {"automerge": False},
    ),
    "postgres digest": (
        "stacks/overmind/sub2api/compose.yaml", "docker.io/library/postgres", "digest",
        {"automerge": False, "groupName": None},
    ),
}


def deployed_renovate_version() -> str:
    compose = yaml.safe_load(
        (REPO_ROOT / "stacks/devserver/renovate/compose.yaml").read_text(encoding="utf-8")
    )
    image = compose["services"]["renovate"]["image"]
    return image.split("@")[0].rsplit(":", 1)[1]


def npx_renovate(*arguments: str, stdin: str | None = None) -> str:
    npx = shutil.which("npx")
    if npx is None:
        # A skip would let a broken rule set pass ./validate.sh unnoticed.
        pytest.fail("npx is required to run Renovate's rule engine", pytrace=False)
    result = subprocess.run(
        [npx, "-y", "--package", f"renovate@{deployed_renovate_version()}", *arguments],
        cwd=REPO_ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_renovate_rules_decide_each_update() -> None:
    # Without a path argument the validator checks renovate.json as repository
    # config; with one it checks it as global config.
    npx_renovate("renovate-config-validator", "--strict")

    updates = [
        {
            "packageFile": package_file,
            "manager": "regex" if package_file.endswith(".env.j2") else "docker-compose",
            "depName": dep_name,
            "updateType": update_type,
        }
        for package_file, dep_name, update_type, _ in CASES.values()
    ]
    outcomes = json.loads(
        npx_renovate("node", str(HELPER), "renovate.json", stdin=json.dumps(updates))
    )

    expected = {name: case[3] for name, case in CASES.items()}
    actual = {
        name: {key: outcome[key] for key in expected[name]}
        for name, outcome in zip(CASES, outcomes, strict=True)
    }
    assert actual == expected
