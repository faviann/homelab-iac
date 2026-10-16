"""Broodling deployment order: initialization, target bootstrap, then readiness."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess

import jinja2
import yaml

from ansible_test_helper import ansible_playbook_command


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_SOURCE = REPO_ROOT / "stacks/broodling/broodling"
BROODLING_DIGEST = "a" * 64


def deploy(tmp_path: Path, *arguments: str, bootstrap_exit: int = 0) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    stack = tmp_path / "conf/stacks/broodling"
    catalog = json.loads(jinja2.Template(
        (STACK_SOURCE / "appdata/broodling/invocation.json.j2").read_text(encoding="utf-8"),
    ).render(stack_vars={"dotnet": {"image": "ghcr.io/faviann/zeroshot-environments/dotnet@sha256:" + "b" * 64}}))
    target = catalog["environments"][0]
    for mount in ("stateMount", "homeMount"):
        target[mount] = str(tmp_path / mount)
        (tmp_path / mount).mkdir(mode=0o755)
    (stack / "appdata/broodling").mkdir(parents=True)
    (stack / "appdata/broodling/invocation.json").write_text(json.dumps(catalog), encoding="utf-8")

    log = tmp_path / "commands.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        '#!/bin/sh\n'
        'printf "docker %s\\n" "$*" >> "$COMMAND_LOG"\n'
        'case "$*" in\n'
        '  *bootstrap-target*) printf \'{"bootstrapped":true,"result":"installed"}\\n\'; exit "$BOOTSTRAP_EXIT" ;;\n'
        '  inspect*) printf "sha256:fixture-target-image\\n" ;;\n'
        'esac\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    runtime = tmp_path / f"check/{BROODLING_DIGEST}"
    (runtime / "dotnet").mkdir(parents=True)
    dotnet = runtime / "dotnet/dotnet"
    dotnet.write_text(
        '#!/bin/sh\n'
        'printf "dotnet %s\\n" "$*" >> "$COMMAND_LOG"\n'
        'printf \'{"ready": true, "targets": [], "providerTasks": 0}\\n\'\n',
        encoding="utf-8",
    )
    dotnet.chmod(0o755)

    playbook = tmp_path / "playbook.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "environment": {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "COMMAND_LOG": str(log),
            "BOOTSTRAP_EXIT": str(bootstrap_exit),
        },
        "vars": {
            "lxc_docker_environment_internal": {"root_docker_conf_path": str(tmp_path / "conf")},
            "lxc_docker_env_broodling_check_target_dir": str(tmp_path / "check"),
            "lxc_docker_env_stack_vars": {"broodling": {
                "broodling_image": f"ghcr.io/faviann/broodling@sha256:{BROODLING_DIGEST}",
            }},
        },
        "tasks": [{"ansible.builtin.include_role": {
            "name": "config/lxc_docker_environment", "tasks_from": "broodling",
        }}],
    }]), encoding="utf-8")
    result = subprocess.run(
        ansible_playbook_command(str(playbook), *arguments),
        cwd=REPO_ROOT,
        env={**os.environ, "ANSIBLE_CACHE_PLUGIN_CONNECTION": str(tmp_path / "cache")},
        capture_output=True,
        text=True,
        check=False,
    )
    commands = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result, commands


def bootstrap_and_check(tmp_path: Path) -> list[str]:
    stack = tmp_path / "conf/stacks/broodling"
    check = tmp_path / "check"
    return [
        "docker compose -p broodling run --rm --no-deps"
        f" -v {stack}/credentials/bootstrap/zeroshot-dotnet-bootstrap-key:/run/secrets/zeroshot-bootstrap-key:ro"
        " broodling bootstrap-target /etc/broodling/invocation.json dotnet /run/secrets/zeroshot-bootstrap-key",
        "docker inspect --format {{.Image}} zeroshot-dotnet",
        f"dotnet {check}/{BROODLING_DIGEST}/app/Broodling.Host.dll check-target"
        f" {check}/target-inventory.json {check}/config.json",
    ]


def test_initialization_runs_in_order_then_bootstraps_and_checks(tmp_path: Path) -> None:
    result, commands = deploy(tmp_path, "-e", "broodling_initialize=true")

    assert result.returncode == 0, result.stdout + result.stderr
    assert commands == [
        "docker compose -p broodling run --rm --no-deps initialize-tls",
        "docker compose -p broodling up -d --force-recreate --no-deps zeroshot-tls",
        "docker compose -p broodling run --rm --no-deps --use-aliases zeroshot-dotnet initialize"
        " --listen 0.0.0.0:18770 --public-origin https://zeroshot-dotnet.dev.faviann.com --storage /state",
        "docker compose -p broodling run --rm --no-deps broodling initialize-store /var/lib/broodling/state.sqlite3",
        "docker compose -p broodling up -d --force-recreate --no-deps broodling zeroshot-dotnet",
        *bootstrap_and_check(tmp_path),
    ]
    assert stat.S_IMODE((tmp_path / "stateMount").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "homeMount").stat().st_mode) == 0o700


def test_ordinary_run_bootstraps_before_checking_and_never_initializes(tmp_path: Path) -> None:
    result, commands = deploy(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert commands == bootstrap_and_check(tmp_path)
    assert stat.S_IMODE((tmp_path / "stateMount").stat().st_mode) == 0o755


def test_failed_bootstrap_fails_the_run_before_the_readiness_check(tmp_path: Path) -> None:
    result, commands = deploy(tmp_path, bootstrap_exit=1)

    assert result.returncode != 0, result.stdout + result.stderr
    assert commands == bootstrap_and_check(tmp_path)[:1]
