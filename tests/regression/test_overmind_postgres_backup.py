#!/usr/bin/env python3
"""Regression tests for overmind verified logical backups."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/files/overmind-postgres-backup"
FRESHNESS_SCRIPT = (
    REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/files/overmind-postgres-backup-freshness"
)
POSTGRES_IMAGE = "docker.io/library/postgres:18"
POSTGRES_PASSWORD = "test-admin-password"


def run_command(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
        **kwargs,
    )


def docker(*args: str, check: bool = True, input: str | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["docker", *args],
        check=False,
        capture_output=True,
        input=input,
        text=True,
        timeout=90,
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"docker {' '.join(args)} failed\nstdout={proc.stdout}\nstderr={proc.stderr}")
    return proc


def retry_docker(*args: str, input: str | None = None) -> subprocess.CompletedProcess[str]:
    last_proc: subprocess.CompletedProcess[str] | None = None
    for _ in range(60):
        last_proc = docker(*args, check=False, input=input)
        if last_proc.returncode == 0:
            return last_proc
        time.sleep(1)

    assert last_proc is not None
    raise AssertionError(
        f"docker {' '.join(args)} did not succeed\nstdout={last_proc.stdout}\nstderr={last_proc.stderr}"
    )


@pytest.fixture(scope="module", autouse=True)
def require_docker() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker is required for overmind Postgres backup regression tests")
    proc = docker("version", "--format", "{{.Server.Version}}", check=False)
    if proc.returncode != 0:
        pytest.skip("docker daemon is not available")


@pytest.fixture()
def postgres_container() -> str:
    name = f"overmind-backup-test-{uuid.uuid4().hex[:12]}"
    docker(
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "-e",
        "POSTGRES_USER=overmind",
        "-e",
        f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
        "-e",
        "POSTGRES_DB=overmind",
        POSTGRES_IMAGE,
    )
    try:
        for _ in range(60):
            ready = docker(
                "exec",
                "-e",
                f"PGPASSWORD={POSTGRES_PASSWORD}",
                name,
                "pg_isready",
                "-U",
                "overmind",
                "-d",
                "overmind",
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise AssertionError("Postgres test container did not become ready")

        retry_docker(
            "exec",
            "-e",
            f"PGPASSWORD={POSTGRES_PASSWORD}",
            name,
            "createdb",
            "-U",
            "overmind",
            "memory",
        )
        retry_docker(
            "exec",
            "-i",
            "-e",
            f"PGPASSWORD={POSTGRES_PASSWORD}",
            name,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "overmind",
            "-d",
            "memory",
            input="""
CREATE TABLE backup_probe (id integer PRIMARY KEY, note text NOT NULL);
INSERT INTO backup_probe VALUES (1, 'verified');
""",
        )
        yield name
    finally:
        docker("rm", "-f", name, check=False)


def backup_env(backup_dir: Path, container: str, **overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "OVERMIND_BACKUP_DIR": str(backup_dir),
            "OVERMIND_BACKUP_RETAIN": "3",
            "OVERMIND_POSTGRES_CONTAINER": container,
            "OVERMIND_POSTGRES_ADMIN_USER": "overmind",
            "OVERMIND_POSTGRES_DATABASE": "memory",
            "OVERMIND_POSTGRES_PASSWORD": POSTGRES_PASSWORD,
            "OVERMIND_DISCORD_WEBHOOK_URL": "",
        }
    )
    env.update(overrides)
    return env


def verified_dumps(backup_dir: Path) -> list[Path]:
    return sorted(backup_dir.glob("memory-*.verified.dump"))


def test_good_dump_is_restore_verified_and_throwaway_database_is_dropped(postgres_container: str) -> None:
    with tempfile.TemporaryDirectory(prefix="overmind-backup-good-") as temp_root:
        backup_dir = Path(temp_root) / "backups"
        backup_dir.mkdir()

        run_command([str(BACKUP_SCRIPT)], env=backup_env(backup_dir, postgres_container))

        dumps = verified_dumps(backup_dir)
        assert len(dumps) == 1
        assert dumps[0].stat().st_size > 0

        probe = docker(
            "exec",
            "-e",
            f"PGPASSWORD={POSTGRES_PASSWORD}",
            postgres_container,
            "psql",
            "-At",
            "-U",
            "overmind",
            "-d",
            "postgres",
            "-c",
            "SELECT count(*) FROM pg_database WHERE datname LIKE 'overmind_backup_verify_%'",
        )
        assert probe.stdout.strip() == "0"


def test_corrupt_dump_fails_without_counting_verified_backup_and_notifies_webhook(postgres_container: str) -> None:
    real_docker = shutil.which("docker")
    assert real_docker is not None

    with tempfile.TemporaryDirectory(prefix="overmind-backup-corrupt-") as temp_root:
        root = Path(temp_root)
        backup_dir = root / "backups"
        backup_dir.mkdir()
        docker_wrapper = root / "docker"
        curl_wrapper = root / "curl"
        curl_log = root / "curl.log"

        docker_wrapper.write_text(
            f"""#!/bin/sh
for arg in "$@"; do
  if [ "$arg" = "pg_dump" ]; then
    printf 'this is not a postgres custom dump\\n'
    exit 0
  fi
done
exec {real_docker} "$@"
""",
            encoding="utf-8",
        )
        docker_wrapper.chmod(0o755)
        curl_wrapper.write_text(
            f"""#!/bin/sh
printf '%s\\n' "$*" >> {curl_log}
exit 0
""",
            encoding="utf-8",
        )
        curl_wrapper.chmod(0o755)

        proc = subprocess.run(
            [str(BACKUP_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
            env=backup_env(
                backup_dir,
                postgres_container,
                OVERMIND_DOCKER_BIN=str(docker_wrapper),
                OVERMIND_CURL_BIN=str(curl_wrapper),
                OVERMIND_DISCORD_WEBHOOK_URL="https://discord.invalid/webhook",
            ),
        )

        assert proc.returncode != 0
        assert verified_dumps(backup_dir) == []
        assert curl_log.exists()
        assert "Overmind Postgres backup failed" in curl_log.read_text(encoding="utf-8")


def test_rotation_keeps_configured_number_of_verified_dumps(postgres_container: str) -> None:
    with tempfile.TemporaryDirectory(prefix="overmind-backup-rotate-") as temp_root:
        backup_dir = Path(temp_root) / "backups"
        backup_dir.mkdir()

        for index in range(4):
            run_command(
                [str(BACKUP_SCRIPT)],
                env=backup_env(
                    backup_dir,
                    postgres_container,
                    OVERMIND_BACKUP_RETAIN="2",
                    OVERMIND_BACKUP_TIMESTAMP=f"20260707T000{index}00Z",
                ),
            )

        dumps = verified_dumps(backup_dir)
        assert len(dumps) == 2
        assert [dump.name for dump in dumps] == [
            "memory-20260707T000200Z.verified.dump",
            "memory-20260707T000300Z.verified.dump",
        ]


def write_systemctl(path: Path, exit_code: int) -> None:
    path.write_text(
        f"""#!/bin/sh
if [ "$1" = "is-active" ]; then
  exit {exit_code}
fi
exit 1
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_freshness_check_fails_when_timer_is_inactive() -> None:
    with tempfile.TemporaryDirectory(prefix="overmind-backup-freshness-timer-") as temp_root:
        root = Path(temp_root)
        backup_dir = root / "backups"
        backup_dir.mkdir()
        (backup_dir / "memory-20260707T000000Z.verified.dump").write_text("ok", encoding="utf-8")
        systemctl = root / "systemctl"
        write_systemctl(systemctl, 3)

        proc = subprocess.run(
            [str(FRESHNESS_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **os.environ,
                "OVERMIND_BACKUP_DIR": str(backup_dir),
                "OVERMIND_BACKUP_FRESHNESS_MAX_AGE_SECONDS": "86400",
                "OVERMIND_SYSTEMCTL_BIN": str(systemctl),
            },
        )

        assert proc.returncode != 0
        assert "timer is not active" in proc.stderr


def test_freshness_check_fails_when_newest_verified_dump_is_stale() -> None:
    with tempfile.TemporaryDirectory(prefix="overmind-backup-freshness-stale-") as temp_root:
        root = Path(temp_root)
        backup_dir = root / "backups"
        backup_dir.mkdir()
        stale_dump = backup_dir / "memory-20260707T000000Z.verified.dump"
        stale_dump.write_text("ok", encoding="utf-8")
        old_mtime = time.time() - 10_000
        os.utime(stale_dump, (old_mtime, old_mtime))
        systemctl = root / "systemctl"
        write_systemctl(systemctl, 0)

        proc = subprocess.run(
            [str(FRESHNESS_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **os.environ,
                "OVERMIND_BACKUP_DIR": str(backup_dir),
                "OVERMIND_BACKUP_FRESHNESS_MAX_AGE_SECONDS": "60",
                "OVERMIND_SYSTEMCTL_BIN": str(systemctl),
            },
        )

        assert proc.returncode != 0
        assert "stale" in proc.stderr
