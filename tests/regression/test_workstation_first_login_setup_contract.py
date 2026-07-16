#!/usr/bin/env python3
"""Regression test for workstation first-login setup contract."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _prepare_completed_workstation(temp_root: Path) -> tuple[Path, dict[str, str]]:
    username = subprocess.run(
        ["id", "-un"], check=True, text=True, stdout=subprocess.PIPE
    ).stdout.strip()
    home = temp_root / "home" / username
    bin_dir = home / ".local" / "bin"
    source = home / ".local" / "share" / "chezmoi"
    command_log = temp_root / "commands.log"
    bw_state = temp_root / "bw-state"

    for path in (
        home / ".ansible",
        home / ".ssh",
        bin_dir,
        source / ".git",
        source / "dot_local" / "bin",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (home / ".ansible" / "vault-pass").write_text("test\n", encoding="utf-8")
    (home / ".ansible" / "vault-pass").chmod(0o600)
    (home / ".ssh" / "id_ed25519").write_text("test\n", encoding="utf-8")
    (home / ".ssh" / "id_ed25519").chmod(0o600)
    for name in ("id_ed25519.pub", "allowed_signers", "known_hosts"):
        (home / ".ssh" / name).write_text("test\n", encoding="utf-8")

    mock = """#!/bin/sh
name=$(basename "$0")
printf '%s %s\n' "$name" "$*" >> "$COMMAND_LOG"
case "$name:$1" in
  bw:status) printf '{"status":"%s"}\n' "$(cat "$BW_STATE")" ;;
  bw:unlock) printf 'unlocked' > "$BW_STATE"; printf 'test-session\n' ;;
  bw:login) printf 'locked' > "$BW_STATE" ;;
  ssh:*) printf "You've successfully authenticated\n" ;;
esac
exit 0
"""
    for name in (
        "bw",
        "bwrap",
        "chezmoi",
        "claude",
        "codex",
        "fd",
        "fzf",
        "gh",
        "git",
        "hermes",
        "home-manager",
        "jq",
        "nix",
        "node",
        "npm",
        "openclaw",
        "pi",
        "rg",
        "ssh",
        "ssh-keygen",
        "setsid",
        "update-agent-tools",
        "uv",
    ):
        _write_executable(bin_dir / name, mock)
    _write_executable(temp_root / "bin" / "bw", mock)

    marker = home / ".local" / "state" / "workstation-setup" / "complete"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        "\n".join(
            (
                "version=2",
                "dotfiles=https://github.com/faviann/dotfiles.git",
                "fingerprint=2|https://github.com/faviann/dotfiles.git|dotfiles/github-cli-token|"
                f"{source}#workstation|{temp_root}/bin/bw",
                "completed_at=2026-01-01T00:00:00Z",
                "",
            )
        ),
        encoding="utf-8",
    )
    bw_state.write_text("locked", encoding="utf-8")
    env = os.environ | {
        "COMMAND_LOG": str(command_log),
        "BW_STATE": str(bw_state),
    }
    return home, env


def _run_setup(temp_root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(temp_root / "bin" / "workstation-setup")],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )


def _wait_for_command(command_log: Path, expected: str) -> str:
    commands = ""
    for _ in range(50):
        commands = command_log.read_text(encoding="utf-8")
        if expected in commands:
            return commands
        time.sleep(0.02)
    return commands


def test_workstation_first_login_setup_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="workstation-first-login-setup-") as temp_root:
        result = subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                "ansible-playbook",
                "tests/regression/fixtures/workstation_first_login_setup_contract.yml",
                "-e",
                f"temp_root={temp_root}",
            ],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        assert result.returncode == 0, result.stdout

        root = Path(temp_root)
        home, env = _prepare_completed_workstation(root)
        workstation_update = home / ".local" / "bin" / "workstation-update"
        workstation_update_source = (
            home
            / ".local"
            / "share"
            / "chezmoi"
            / "dot_local"
            / "bin"
            / "executable_workstation-update"
        )
        update_agent_tools = home / ".local" / "bin" / "update-agent-tools"
        update_agent_tools_source = (
            home
            / ".local"
            / "share"
            / "chezmoi"
            / "dot_local"
            / "bin"
            / "executable_update-agent-tools"
        )

        _write_executable(workstation_update_source, "#!/bin/sh\nexit 0\n")
        repaired = _run_setup(root, env)
        assert repaired.returncode == 0, repaired.stderr
        assert workstation_update.is_file() and os.access(workstation_update, os.X_OK)
        assert "workstation-setup: environment repaired and ready." in repaired.stdout
        assert "home-manager switch" in (root / "commands.log").read_text(encoding="utf-8")

        (root / "commands.log").write_text("", encoding="utf-8")
        healthy = _run_setup(root, env)
        assert healthy.returncode == 0, healthy.stderr
        assert "workstation-setup: environment healthy." in healthy.stdout
        healthy_commands = (root / "commands.log").read_text(encoding="utf-8")
        assert "home-manager switch" not in healthy_commands
        assert "bw unlock --raw" not in healthy_commands

        update_agent_tools.unlink()
        _write_executable(update_agent_tools_source, "#!/bin/sh\nexit 0\n")
        repaired_agent_tools = _run_setup(root, env)
        assert repaired_agent_tools.returncode == 0, repaired_agent_tools.stderr
        assert update_agent_tools.is_file() and os.access(update_agent_tools, os.X_OK)
        assert "workstation-setup: environment healthy." not in repaired_agent_tools.stdout
        assert "workstation-setup: environment repaired and ready." in repaired_agent_tools.stdout

        workstation_update.unlink()
        workstation_update_source.unlink()
        (root / "commands.log").write_text("", encoding="utf-8")
        escalated = _run_setup(root, env)
        assert escalated.returncode != 0
        assert "Bitwarden is locked" in escalated.stderr
        assert "environment healthy" not in escalated.stdout
        assert "environment repaired and ready" not in escalated.stdout
        assert "bw unlock --raw" in (root / "commands.log").read_text(encoding="utf-8")

        (root / "bw-state").write_text("unauthenticated", encoding="utf-8")
        (root / "commands.log").write_text("", encoding="utf-8")
        unauthenticated = _run_setup(root, env)
        assert unauthenticated.returncode != 0
        assert "Bitwarden is unauthenticated" in unauthenticated.stderr
        assert "Bitwarden is locked" in unauthenticated.stderr
        assert not workstation_update.exists()
        assert "environment healthy" not in unauthenticated.stdout
        assert "environment repaired and ready" not in unauthenticated.stdout
        unauthenticated_commands = (root / "commands.log").read_text(encoding="utf-8")
        assert "bw login" in unauthenticated_commands
        assert "bw unlock --raw" in unauthenticated_commands

        (root / "commands.log").write_text("", encoding="utf-8")
        missing_checker_profile = subprocess.run(
            ["bash", "-c", f'. "{root / "etc/profile.d/workstation-setup.sh"}"'],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env | {"SSH_CONNECTION": "test"},
            check=False,
        )
        assert missing_checker_profile.returncode == 0
        assert "workstation-update is missing or not executable" in missing_checker_profile.stderr
        assert "Run workstation-setup to repair the workstation" in missing_checker_profile.stderr
        expected_autosync_launch = f"setsid {root / 'bin' / 'workstation-autosync'}"
        missing_checker_commands = _wait_for_command(root / "commands.log", expected_autosync_launch)
        assert expected_autosync_launch in missing_checker_commands

        _write_executable(workstation_update, "#!/bin/sh\nexit 0\n")
        (root / "commands.log").write_text("", encoding="utf-8")
        checker_present_profile = subprocess.run(
            ["bash", "-c", f'. "{root / "etc/profile.d/workstation-setup.sh"}"'],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env | {"SSH_CONNECTION": "test"},
            check=False,
        )
        assert checker_present_profile.returncode == 0
        assert "workstation-update is missing or not executable" not in checker_present_profile.stderr
        checker_present_commands = _wait_for_command(root / "commands.log", expected_autosync_launch)
        assert expected_autosync_launch in checker_present_commands
