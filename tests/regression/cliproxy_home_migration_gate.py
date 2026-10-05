"""Explicit pinned-image migration rehearsal; default validation needs no Docker.

    ./validate.sh tests tests/regression/cliproxy_home_migration_gate.py

Only synthetic state and an internal local Docker network are used. This gate
covers native import/export and standalone behavior before consumer enrollment.
It does not prove real OAuth refresh, panel behavior or remote orphan removal;
the maintenance-script stand-in tests own removal of managed Home containers.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest
import yaml

from cliproxy_home_recovery_gate import (
    CPA_IMAGE, HOME_IMAGE, LEGACY_KEY, MANAGEMENT_KEY, MODEL, REPO, HomeCPAPair, SyntheticProvider,
)

pytestmark = pytest.mark.serial
# Fixed synthetic bcrypt reference; management probes use a fixture-only env
# password so the test never rewrites this imported reference to gain access.
BCRYPT_REFERENCE = "$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy"
SCRIPT_HOME_IMAGE = re.search(r"^initial_home_image=(\S+)$",
                              (REPO / "scripts/cliproxy-maintenance.sh").read_text(), re.M)[1]


def require(condition: bool, stage: str) -> None:
    """Failures identify a boundary without rendering credential-bearing data."""
    if not condition:
        pytest.fail(stage, pytrace=False)


def fingerprint(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_mode & 0o777,
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
            for p in [root, *sorted(root.rglob("*"))]}


def oauth_files(root: Path) -> dict:
    return {value["email"]: value for p in root.glob("*.json")
            if (value := json.loads(p.read_text())).get("type") in ("codex", "claude")}


def compare_accounts(actual: dict, expected: dict) -> None:
    require(set(actual) == set(expected), "OAuth source count/identity changed")
    for email, fields in expected.items():
        require(all(actual[email].get(key) == value for key, value in fields.items()),
                "OAuth credential, status or meaningful metadata changed")


def database_accounts(state: Path) -> tuple[dict, dict]:
    with sqlite3.connect(f"file:{state / 'home.db'}?mode=ro", uri=True) as db:
        rows = db.execute("select uuid, disabled, auth_json from auth where provider in ('codex', 'claude')").fetchall()
        config = dict(db.execute("select key, value from config").fetchall())
        keys = [row[0] for row in db.execute("select api_key from api_key").fetchall()]
    require(keys == [LEGACY_KEY], "arbitrary legacy client key changed")
    require(json.loads(config["remote-management"])["secret-key"] == BCRYPT_REFERENCE,
            "management bcrypt reference changed")
    accounts, identifiers = {}, {}
    for identifier, disabled, serialized in rows:
        record = json.loads(serialized)
        metadata = record.get("metadata", record.get("Metadata", {}))
        email = metadata["email"]
        require(bool(disabled) == bool(metadata.get("disabled", False)), "active/disabled status changed")
        accounts[email] = metadata
        identifiers[email] = identifier
    return accounts, identifiers


class CheckedProvider(SyntheticProvider):
    def do_POST(self) -> None:
        payload = self.rfile.read(int(self.headers["Content-Length"]))
        valid = (self.path == "/v1/chat/completions"
                 and self.headers.get("Authorization") == "Bearer synthetic-provider-key"
                 and json.loads(payload).get("model") == MODEL)
        self.server.observed_requests.append(valid)
        if not valid:
            self.send_error(400)
            return
        self.rfile = io.BytesIO(payload)
        super().do_POST()


class MigrationPair(HomeCPAPair):
    def mounts(self, state: Path, home: Path) -> list[str]:
        return [*super().mounts(state, home), "--env", "MANAGEMENT_PASSWORD=" + MANAGEMENT_KEY]

    def standalone(self, directory: Path) -> None:
        self.containers.append(self.cpa_name)
        self.docker("run", "-d", "--pull", "never", "--name", self.cpa_name,
                    "--network", self.network, "--user", f"{os.getuid()}:{os.getgid()}",
                    "--env", "HOME=/root", "--mount", f"type=bind,src={directory},dst=/legacy",
                    "--entrypoint", "/bin/sh", CPA_IMAGE, "-c",
                    "umask 077; exec ./CLIProxyAPI -config /legacy/config.yaml",
                    stage="standalone rollback startup")
        self.cpa_url = "http://" + self.address(self.cpa_name) + ":8317/v1"
        before = len(self.provider.observed_requests)
        self.wait(lambda: self.chat(LEGACY_KEY), "standalone legacy key/fake-provider behavior")
        require(len(self.provider.observed_requests) > before
                and all(self.provider.observed_requests), "fake provider path/auth/model changed")
        self.stop()

    def restore(self, source: Path, target: Path, auth_name: str) -> None:
        # Runtime, client-key and config-provider policy remain frozen. Prepare
        # standalone from old config and the selected native/source auth tree.
        shutil.copy2(self.root / "original/config.yaml", target / "config.yaml")
        shutil.copytree(source / auth_name, target / "auth")
        config = yaml.safe_load((target / "config.yaml").read_text())
        config["auth-dir"] = "/legacy/auth"
        (target / "config.yaml").write_text(yaml.safe_dump(config))
        self.standalone(target)


@pytest.fixture
def migration_pair():
    # Rehearse exactly the Home image the maintenance script imports and exports with.
    require(HOME_IMAGE == SCRIPT_HOME_IMAGE, "gate and maintenance script Home images differ")
    with tempfile.TemporaryDirectory(prefix="cliproxy-home-migration-") as temporary:
        pair = MigrationPair(Path(temporary))
        pair.root.chmod(0o700)
        try:
            pair.prepare()
            pair.provider.observed_requests = []
            pair.provider.RequestHandlerClass = CheckedProvider
            yield pair
        finally:
            pair.close()


def test_offline_import_and_both_pre_consumer_standalone_rollbacks(migration_pair):
    pair = migration_pair
    original = pair.root / "original"
    (pair.root / "source").rename(original)
    config = yaml.safe_load((original / "config.yaml").read_text())
    config["remote-management"]["secret-key"] = BCRYPT_REFERENCE
    config["auth-dir"] = "/legacy/auth"
    (original / "config.yaml").write_text(yaml.safe_dump(config))
    (original / "auth/synthetic-codex.json").unlink()
    for disabled in (False, True):
        account = {"type": "codex", "email": f"migration-{disabled}@example.invalid",
                   "disabled": disabled, "access_token": f"synthetic-access-{disabled}",
                   "refresh_token": f"synthetic-refresh-{disabled}", "expired": "2100-01-01T00:00:00Z",
                   "account_id": f"synthetic-account-{disabled}", "prefix": "migration",
                   "priority": 7, "note": "frozen original", "migration_marker": {"generation": "original"}, "last_refresh": "2026-01-01T00:00:00Z"}
        (original / "auth" / f"legacy-{disabled}.json").write_text(json.dumps(account))
    (original / "auth/legacy-claude.json").write_text(json.dumps({
        "type": "claude", "email": "migration-claude@example.invalid", "disabled": True,
        "access_token": "synthetic-claude-access", "refresh_token": "synthetic-claude-refresh",
        "expired": "2100-01-01T00:00:00Z", "account_id": "synthetic-claude-account",
        "prefix": "migration", "priority": 7, "note": "frozen original",
        "migration_marker": {"generation": "original"}, "last_refresh": "2026-01-01T00:00:00Z",
    }))
    for path in [original, *original.rglob("*")]:
        path.chmod(0o700 if path.is_dir() else 0o600)
    frozen = fingerprint(original)
    expected = oauth_files(original / "auth")
    working = pair.root / "working"
    shutil.copytree(original, working)
    state = pair.directory("fresh-home")
    require(not list(state.iterdir()), "Home import target is not fresh")
    result = pair.native(state, "-import", "-config", "/recovery/working/config.yaml",
                         "-auth-dir", "/recovery/working/auth", stage="one offline native import")
    summary = re.search(r"database import completed created=(\d+) updated=(\d+) unchanged=(\d+) restored=(\d+) overwritten=(\d+) skipped=(\d+)", result.stdout + result.stderr)
    # Skipped counts excluded config roots, not missing OAuth accounts. Both
    # auth-dir and openai-compatibility are intentionally synthesized/excluded.
    require(summary is not None and tuple(map(int, summary.groups()))[1:5] == (0, 0, 0, 0)
            and int(summary[6]) == 2, "native import status is partial or unexpected")
    accounts, identifiers = database_accounts(state)
    with sqlite3.connect(f"file:{state / 'home.db'}?mode=ro", uri=True) as db:
        imported_count = sum(db.execute(f"select count(*) from {table}").fetchone()[0]
                             for table in ("config", "api_key", "auth"))
        config_provider_count = db.execute("select count(*) from auth where provider not in ('codex', 'claude')").fetchone()[0]
    require(int(summary[1]) == imported_count and config_provider_count == 1,
            f"native created count/config-provider inventory differs ({summary[1]}/{imported_count}/{config_provider_count})")
    compare_accounts(accounts, expected)
    compare_accounts(oauth_files(working / "auth"), expected)
    require(all(value.get("uuid") for value in oauth_files(working / "auth").values()),
            "native UUID normalization was not observed on the writable copy")
    require(fingerprint(original) == frozen, "native import mutated frozen source names/modes/content")

    pair.restore(original, pair.directory("rollback-original"), "auth")
    compare_accounts(oauth_files(pair.root / "rollback-original/auth"), expected)
    pair.start_home(state)
    email = "migration-False@example.invalid"
    changes = {"access_token": "synthetic-refreshed-access", "refresh_token": "synthetic-refreshed-refresh",
               "expired": "2101-01-01T00:00:00Z", "last_refresh": "2026-10-05T00:00:00Z",
               "migration_marker": {"generation": "refreshed"}}
    status, _ = pair.request(pair.home_url.replace("/v8/management", "/v0/management") + "/auth-files/fields", MANAGEMENT_KEY, "PATCH",
                             {"id": identifiers[email], **changes})
    require(status == 200, f"native provider metadata patch failed (HTTP {status})")
    pair.stop()
    expected[email].update(changes)
    export = pair.directory("current-export")
    require(not list(export.iterdir()), "current export target is not empty")
    pair.native(state, "-export", "-export-dir", "/recovery/current-export", stage="current native legacy export")
    require((export / "config.yaml").is_file() and (export / "auths").is_dir(), "native legacy export shape changed")
    compare_accounts(oauth_files(export / "auths"), expected)
    database_accounts(state)  # Legacy key and hash remain frozen after patch/export.
    pair.restore(export, pair.directory("rollback-current"), "auths")
    compare_accounts(oauth_files(pair.root / "rollback-current/auth"), expected)
    require(fingerprint(original) == frozen, "rollback changed protected original archive")
