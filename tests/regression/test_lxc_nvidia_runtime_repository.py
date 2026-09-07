#!/usr/bin/env python3
"""Regression test for retryable NVIDIA repository publication.

Ansible exits 0 when a ``--tags`` selector matches no tasks, so a return code
alone cannot tell a real run apart from a run that asserted nothing. Each
scenario therefore also requires its own existing final semantic assertion task
to have run and passed, read out of the machine-readable report emitted by a
fixture-local stdout callback.

Matching the human-facing display with a regex was rejected because it renders
whatever the caller's environment asks for, and that changes without any change
here.

So ``run_isolated_playbook`` pins the display instead of tolerating it: the
fixture callback, zero verbosity, no inherited extra callbacks, leaving stdout
as exactly one JSON document. That breaks if another writer still reaches
stdout, so the safer rule is that stdout which does not parse into the report
fails the test rather than passing it.

This guards each scenario's *final* semantic observation only -- that one task
is required to have run and passed. It does not prove that every assertion
inside a fixture ran.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ansible_test_helper import ansible_playbook_command
from lifecycle_observation_report import assert_observations_completed as assert_report


REPO_ROOT = Path(__file__).resolve().parents[2]
ANSIBLE_PLAYBOOK = ansible_playbook_command(supplies_own_inventory=True)
PLAYBOOK = (
    REPO_ROOT
    / "tests"
    / "regression"
    / "fixtures"
    / "lxc_nvidia_runtime_repository_test.yml"
)
APT_ORDER_PLAYBOOK = (
    REPO_ROOT
    / "tests"
    / "regression"
    / "fixtures"
    / "lxc_nvidia_runtime_apt_order_test.yml"
)
FIXTURE_ROLES = (
    REPO_ROOT
    / "tests"
    / "regression"
    / "fixtures"
    / "lxc_nvidia_runtime_repository_assets"
    / "roles"
)
FIXTURE_OBSERVATION_PLUGINS = (
    REPO_ROOT / "tests" / "regression" / "fixtures" / "lifecycle_observation_plugins"
)


def run_isolated_playbook(
    playbook: Path, tags: str
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="lxc-nvidia-repository-") as temp_root:
        # ansible.cfg names a vault password file that must exist, but these
        # fixtures decrypt nothing: a per-scenario placeholder keeps the run
        # credential-free and independent of the caller's environment.
        vault_placeholder = Path(temp_root) / "vault-pass"
        vault_placeholder.write_text(
            "unused-fixture-placeholder\n", encoding="utf-8"
        )
        fixture_inventory = Path(temp_root) / "inventory.ini"
        fixture_inventory.write_text(
            "[local]\nlocalhost ansible_connection=local\n", encoding="utf-8"
        )
        repository_dir = Path(temp_root) / "repository"
        repository_dir.mkdir()

        env = os.environ.copy()
        env["ANSIBLE_VAULT_PASSWORD_FILE"] = str(vault_placeholder)
        env["ANSIBLE_INVENTORY"] = str(fixture_inventory)
        env["ANSIBLE_CACHE_PLUGIN_CONNECTION"] = str(Path(temp_root) / "fact-cache")
        env["ANSIBLE_LOCAL_TEMP"] = str(Path(temp_root) / "ansible-local-tmp")
        env["ANSIBLE_REMOTE_TEMP"] = str(Path(temp_root) / "ansible-tmp")
        env["ANSIBLE_ROLES_PATH"] = os.pathsep.join(
            [str(FIXTURE_ROLES), str(REPO_ROOT / "playbooks" / "roles")]
        )
        env["UV_CACHE_DIR"] = str(Path(temp_root) / "uv-cache")
        env["TMPDIR"] = temp_root
        env["ANSIBLE_CALLBACK_PLUGINS"] = str(FIXTURE_OBSERVATION_PLUGINS)
        env["ANSIBLE_STDOUT_CALLBACK"] = "lifecycle_observation"
        # Keep stdout to the report alone: an inherited verbosity prints a
        # config preamble ahead of it, and inherited callbacks interleave their
        # own lines around it. Neither overrides useful human debugging here,
        # because under the JSON callback stdout is a machine document anyway.
        env["ANSIBLE_VERBOSITY"] = "0"
        # Dropped rather than set empty: ansible-core parses an empty value as
        # the one-element list [""] and aborts on the empty plugin name, while
        # an absent variable falls back to ansible.cfg, which enables none.
        env.pop("ANSIBLE_CALLBACKS_ENABLED", None)
        result = subprocess.run(
            [
                "bwrap",
                "--ro-bind",
                "/",
                "/",
                # TMPDIR may be below /dev/shm, so establish /dev before
                # rebinding the scenario root that holds its prerequisites.
                "--dev",
                "/dev",
                "--bind",
                temp_root,
                temp_root,
                "--bind",
                str(repository_dir),
                "/etc/apt/sources.list.d",
                "--proc",
                "/proc",
                "--chdir",
                str(REPO_ROOT),
                *ANSIBLE_PLAYBOOK,
                str(playbook),
                "-f",
                "1",
                "--tags",
                tags,
                "-e",
                f"temp_root={temp_root}",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    return result


def assert_observation_completed(
    result: subprocess.CompletedProcess[str], task_name: str
) -> None:
    assert_report(result, (task_name,))


def test_lxc_nvidia_runtime_repository_publication_is_retryable() -> None:
    result = run_isolated_playbook(PLAYBOOK, "lxc_nvidia_runtime_repository")

    assert_observation_completed(result, "Assert valid repository was not rewritten")


def test_lxc_nvidia_runtime_refreshes_apt_before_toolkit_install() -> None:
    result = run_isolated_playbook(
        APT_ORDER_PLAYBOOK,
        "lxc_nvidia_runtime_package_setup",
    )

    assert_observation_completed(
        result, "Assert cache refresh completed before isolated install failure"
    )


def test_tag_selection_miss_cannot_pass_execution_proof() -> None:
    result = run_isolated_playbook(PLAYBOOK, "fixture_nonexistent_tag")
    assert result.returncode == 0, result.stderr
    try:
        assert_observation_completed(result, "Assert valid repository was not rewritten")
    except AssertionError:
        return
    raise AssertionError("A tag-selection miss passed execution proof")


if __name__ == "__main__":
    try:
        test_tag_selection_miss_cannot_pass_execution_proof()
        test_lxc_nvidia_runtime_repository_publication_is_retryable()
        test_lxc_nvidia_runtime_refreshes_apt_before_toolkit_install()
    except AssertionError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
    print("ok: NVIDIA repository regression scenarios passed")
