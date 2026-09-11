#!/usr/bin/env python3
"""Regression test for Hawser defaults and caller fact-cache isolation."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "hawser_standard_remote_default_test.yml"
ANSIBLE_PLAYBOOK = ansible_playbook_command()
PORTAL_CACHE_ENTRY = "s1_portal"
SENTINEL = b'{"sentinel":"issue-89"}\n'


EntryState = tuple[bool, int, int, int, str]


def snapshot(entry: Path) -> EntryState:
    if not entry.exists():
        return (False, -1, -1, -1, "")
    stat = entry.stat()
    digest = hashlib.sha256(entry.read_bytes()).hexdigest()
    return (True, stat.st_size, stat.st_mtime_ns, stat.st_ino, digest)


def run_hawser(temp_root: Path, caller_cache: Path) -> subprocess.CompletedProcess[str]:
    caller_env = {
        **os.environ,
        "ANSIBLE_CACHE_PLUGIN_CONNECTION": str(caller_cache),
    }
    fixture_env = {
        **caller_env,
        # Fake fixture hosts must not persist into a caller-selected fact cache
        # (issue #89), including when this launcher is run directly.
        "ANSIBLE_CACHE_PLUGIN_CONNECTION": str(temp_root / "fact-cache"),
    }
    return subprocess.run(
        [*ANSIBLE_PLAYBOOK, str(PLAYBOOK), "-e", f"temp_root={temp_root}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=fixture_env,
    )


def main() -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="hawser-standard-remote-default-") as root:
        temp_root = Path(root)
        caller_cache = temp_root / "caller-cache"
        caller_entry = caller_cache / PORTAL_CACHE_ENTRY

        absent_state = snapshot(caller_entry)
        proc = run_hawser(temp_root / "absent", caller_cache)
        if proc.returncode != 0:
            failures.append(
                f"absent-cache Hawser playbook failed:\n{proc.stdout}\n{proc.stderr}"
            )
        if snapshot(caller_entry) != absent_state:
            failures.append("Hawser fixture modified the initially absent caller cache")

        caller_cache.mkdir(exist_ok=True)
        caller_entry.write_bytes(SENTINEL)
        present_state = snapshot(caller_entry)
        proc = run_hawser(temp_root / "present", caller_cache)
        if proc.returncode != 0:
            failures.append(
                f"present-cache Hawser playbook failed:\n{proc.stdout}\n{proc.stderr}"
            )
        if snapshot(caller_entry) != present_state:
            failures.append("Hawser fixture modified the pre-existing caller cache entry")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    print(
        "ok: Hawser defaults pass with caller cache entry initially absent and present, "
        "and both caller cache states remain untouched"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
