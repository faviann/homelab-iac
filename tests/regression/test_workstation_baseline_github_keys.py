#!/usr/bin/env python3
"""Regression test for workstation baseline inbound GitHub key population."""

from __future__ import annotations

import functools
import http.server
import json
import os
import subprocess
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SUCCESS_PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "workstation_baseline_github_keys_test.yml"
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def build_bitwarden_test_assets(asset_root: Path) -> tuple[str, str]:
    archive_path = asset_root / "bw-linux-test.zip"
    binary_path = asset_root / "bw"
    binary_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(binary_path, 0o755)

    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(binary_path, arcname="bw")

    digest = sha256(archive_path.read_bytes()).hexdigest()
    release_payload = {
        "assets": [
            {
                "name": archive_path.name,
                "digest": f"sha256:{digest}",
            }
        ]
    }
    (asset_root / "release.json").write_text(json.dumps(release_payload), encoding="utf-8")
    return archive_path.name, "release.json"


@contextmanager
def serve_directory(directory: Path) -> str:
    handler = functools.partial(QuietHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
      host, port = server.server_address
      yield f"http://{host}:{port}"
    finally:
      server.shutdown()
      thread.join()


def run_playbook(playbook: Path, temp_root: str, extra_vars: dict[str, str]) -> subprocess.CompletedProcess[str]:
    command = [*ANSIBLE_PLAYBOOK, str(playbook), "-f", "1", "-e", f"temp_root={temp_root}"]
    for key, value in extra_vars.items():
        command.extend(["-e", f"{key}={value}"])
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def test_workstation_baseline_writes_inbound_github_keys_only() -> None:
    with tempfile.TemporaryDirectory(prefix="workstation-baseline-github-keys-success-") as temp_root:
        asset_root = Path(temp_root) / "assets"
        asset_root.mkdir(parents=True)
        archive_name, release_name = build_bitwarden_test_assets(asset_root)

        with serve_directory(asset_root) as base_url:
            success = run_playbook(
                SUCCESS_PLAYBOOK,
                temp_root,
                {
                    "workstation_bw_download_url": f"{base_url}/{archive_name}",
                    "workstation_bw_release_api_url": f"{base_url}/{release_name}",
                },
            )

    success_output = f"{success.stdout}\n{success.stderr}"
    assert success.returncode == 0, success_output
