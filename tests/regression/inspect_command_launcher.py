#!/usr/bin/env python3
"""Regression coverage for the managed-host inspection command."""

from __future__ import annotations

import fcntl
import getpass
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from ansible_test_helper import local_ssh_port, local_sshd, write_controller_identity
from proxmox_api_fixture import (
    COMMON_OBSERVATION,
    LXC_API_PATHS,
    generate_localhost_certificate,
    local_proxmox_server,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
INSPECT = REPO_ROOT / "inspect.sh"
CONTROLLED_API_USER = "inspect-fixture-user@pam"
CONTROLLED_API_TOKEN_ID = "inspect-fixture-token-id"
CONTROLLED_API_TOKEN_SECRET = "inspect-fixture-token-secret"
FIXTURE_COLLECTIONS = (
    REPO_ROOT
    / "tests/regression/fixtures/lxc_lifecycle_facade_assets/collections"
)


def run_inspect(
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    # Assert completed command behavior, independent of controller scheduling.
    return subprocess.run(
        [str(INSPECT), *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env or os.environ.copy(),
    )


def assert_explicit_operation_and_help() -> None:
    bare = run_inspect()
    if bare.returncode != 2:
        raise AssertionError(f"bare inspect returned {bare.returncode}, not 2")

    help_result = run_inspect("--help")
    help_output = f"{help_result.stdout}\n{help_result.stderr}"
    operations = ("credentials", "connectivity", "containers", "plan", "vars", "probe")
    if help_result.returncode != 0 or not all(
        operation in help_output for operation in operations
    ):
        raise AssertionError(f"inspect help is incomplete:\n{help_output}")


def vars_environment(
    temp_root: Path,
    inventory_output: str,
    *,
    inventory_stderr: str = "",
    inventory_status: int = 0,
) -> dict[str, str]:
    env = controlled_environment(temp_root)
    fake_uv = Path(env["PATH"].split(":", 1)[0]) / "uv"
    fake_uv.write_text(
        f"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

capture_dir = Path(f"{{os.environ['INSPECT_TEST_CAPTURE']}}.invocations")
capture_dir.mkdir(exist_ok=True)
capture = capture_dir / f"{{os.getpid()}}.json"
capture.write_text(json.dumps({{
    "argv": sys.argv[1:],
    "marker": os.environ.get("HOMELAB_IAC_LIFECYCLE_WRAPPER"),
}}), encoding="utf-8")
if "ansible-inventory" in sys.argv:
    sys.stdout.write({inventory_output!r})
    sys.stderr.write({inventory_stderr!r})
    raise SystemExit({inventory_status})
elif "python" in sys.argv:
    python_at = sys.argv.index("python")
    os.execv(sys.executable, [sys.executable, *sys.argv[python_at + 1:]])
""",
        encoding="utf-8",
    )
    return env


def vars_invocations(temp_root: Path) -> list[dict[str, object]]:
    capture_dir = temp_root / "capture.json.invocations"
    return sorted(
        (
            json.loads(capture_path.read_text(encoding="utf-8"))
            for capture_path in capture_dir.glob("*.json")
        ),
        key=lambda capture: capture["argv"],
    )


def expected_host_vars_invocations(host: str) -> list[dict[str, object]]:
    return [
        {
            "argv": [
                "run",
                "--locked",
                "ansible-inventory",
                "-i",
                "inventory/hosts.yml",
                "-e",
                "@inventory/vault.yml",
                "--host",
                host,
                "--yaml",
            ],
            "marker": None,
        },
        {
            "argv": ["run", "--locked", "python", "-m", "scripts.masked_inventory"],
            "marker": None,
        },
    ]


def expected_graph_vars_invocations() -> list[dict[str, object]]:
    return [
        {
            "argv": [
                "run",
                "--locked",
                "ansible-inventory",
                "-i",
                "inventory/hosts.yml",
                "--graph",
            ],
            "marker": None,
        }
    ]


def masked_whole(value: object) -> bool:
    """One string holding mask content, with every letter masked as ``a``.

    Digits stay unconstrained: run-length counts are digits, and the numeric
    fixture secrets own digit disclosure.
    """
    return (
        isinstance(value, str)
        and bool({"a", "9"} & set(value))
        and all(character == "a" for character in value if character.isalpha())
    )


def assert_vars_masks_vault_derived_values_without_live_execution() -> None:
    fixture_secret = "SeCrEt42"
    long_secret = "LongFixtureSecretValue12345678901234567890"
    diagnostic_secret = "DiagnosticSecret42"
    inventory_output = f"""---
ordinary_value: visible
vault_feature_enabled: "true"
vault_primary_secret: {fixture_secret}
derived_header: Bearer {fixture_secret}
vault_numeric_secret: 12345678
vault_long_secret: {long_secret}
derived_numeric_value: token=12345678
derived_mapping:
  authorization: Bearer {fixture_secret}
  mode: fixture
derived_sequence:
  - prefix
  - {fixture_secret}
  - 7
"""
    with tempfile.TemporaryDirectory(prefix="inspect-vars-") as temp_dir:
        temp_root = Path(temp_dir)
        env = vars_environment(
            temp_root,
            inventory_output,
            inventory_stderr=f"inventory warning with {diagnostic_secret}\n",
        )
        lock_path = Path(env["HOME"]) / ".ansible/homelab-iac-lifecycle.lock"
        lock_path.parent.mkdir(parents=True)
        with lock_path.open("a", encoding="utf-8") as exclusive_holder:
            fcntl.flock(exclusive_holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = run_inspect("vars", "fixture_host", env=env)

        captures = vars_invocations(temp_root)

    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        raise AssertionError(
            f"vars did not preserve inventory success: {result.returncode}\n{output}"
        )
    if any(
        secret in output
        for secret in (diagnostic_secret, fixture_secret, long_secret, "12345678")
    ):
        raise AssertionError(f"vars disclosed a fixture secret:\n{output}")
    rendered_inventory = yaml.safe_load(result.stdout)
    if rendered_inventory.get("ordinary_value") != "visible":
        raise AssertionError(f"vars masked an ordinary value:\n{result.stdout}")
    # Composites must be masked as one whole value, not field by field.
    unmasked = [
        key
        for key in (
            "vault_feature_enabled",
            "vault_primary_secret",
            "derived_header",
            "vault_numeric_secret",
            "vault_long_secret",
            "derived_numeric_value",
            "derived_mapping",
            "derived_sequence",
        )
        if not masked_whole(rendered_inventory.get(key))
    ]
    if unmasked:
        raise AssertionError(
            f"vars did not mask {unmasked!r} as whole values:\n{result.stdout}"
        )
    # The mask keeps diagnostic shape (ADR-0010), so it is not a fixed redaction.
    header = rendered_inventory["derived_header"]
    shown = f"Bearer {fixture_secret}".replace(" ", "·")
    if len(header) != len(shown) or any(
        masked != original
        for masked, original in zip(header, shown)
        if not original.isalnum()
    ):
        raise AssertionError(f"vars lost the shape of derived_header: {header!r}")
    if not (
        rendered_inventory["derived_mapping"].startswith("{")
        and rendered_inventory["derived_sequence"].startswith("[")
    ):
        raise AssertionError(f"vars lost composite structure:\n{result.stdout}")
    expected_captures = expected_host_vars_invocations("fixture_host")
    if captures != expected_captures:
        raise AssertionError(
            f"vars used a live or unexpected execution path: {captures!r}"
        )


def assert_vars_normalizes_inventory_failure_without_disclosure() -> None:
    fixture_secret = "PartialSecret42"
    diagnostic_secret = "FailureDiagnosticSecret42"
    inventory_output = f"""---
ordinary_derived_value: marker={fixture_secret}
"""
    with tempfile.TemporaryDirectory(prefix="inspect-vars-failure-") as temp_dir:
        temp_root = Path(temp_dir)
        env = vars_environment(
            temp_root,
            inventory_output,
            inventory_stderr=f"inventory failed with {diagnostic_secret}\n",
            inventory_status=23,
        )
        result = run_inspect("vars", "fixture_host", env=env)
        captures = vars_invocations(temp_root)

    output = f"{result.stdout}\n{result.stderr}"
    if (
        result.returncode != 1
        or result.stdout
        or fixture_secret in output
        or diagnostic_secret in output
    ):
        raise AssertionError(
            f"vars published partial inventory failure output:\n{output}"
        )
    expected_captures = expected_host_vars_invocations("fixture_host")
    if captures != expected_captures:
        raise AssertionError(
            f"failing vars used a live or unexpected execution path: {captures!r}"
        )


def assert_vars_suppresses_masker_failure_diagnostics() -> None:
    fixture_marker = "FixtureLeakValue42"
    inventory_output = f"ordinary: !{fixture_marker} x\n"
    with tempfile.TemporaryDirectory(prefix="inspect-vars-mask-failure-") as temp_dir:
        temp_root = Path(temp_dir)
        env = vars_environment(temp_root, inventory_output)
        result = run_inspect("vars", "fixture_host", env=env)
        captures = vars_invocations(temp_root)

    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 1 or result.stdout or fixture_marker in output:
        raise AssertionError(f"vars disclosed masker failure input:\n{output}")
    expected_captures = expected_host_vars_invocations("fixture_host")
    if captures != expected_captures:
        raise AssertionError(
            f"masker failure used a live or unexpected execution path: {captures!r}"
        )


def assert_vars_content_rule_ignores_seven_character_vault_values() -> None:
    inventory_output = """---
vault_short_value: Abc1234
derived_short_value: prefix-Abc1234
"""
    with tempfile.TemporaryDirectory(prefix="inspect-vars-short-") as temp_dir:
        env = vars_environment(Path(temp_dir), inventory_output)
        result = run_inspect("vars", "fixture_host", env=env)
    if result.returncode != 0 or "derived_short_value: prefix-Abc1234" not in result.stdout:
        raise AssertionError(
            "vars selected a derived value containing only a seven-character vault value:\n"
            f"{result.stdout}\n{result.stderr}"
        )


def assert_vars_graph_preserves_inventory_tree_without_live_execution() -> None:
    graph_output = "@all:\n  |--@lxcs:\n  |  |--fixture_host\n"
    diagnostic_secret = "GraphDiagnosticSecret42"
    with tempfile.TemporaryDirectory(prefix="inspect-vars-graph-") as temp_dir:
        temp_root = Path(temp_dir)
        env = vars_environment(
            temp_root,
            graph_output,
            inventory_stderr=f"inventory warning with {diagnostic_secret}\n",
        )
        lock_path = Path(env["HOME"]) / ".ansible/homelab-iac-lifecycle.lock"
        lock_path.parent.mkdir(parents=True)
        with lock_path.open("a", encoding="utf-8") as exclusive_holder:
            fcntl.flock(exclusive_holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = run_inspect("vars", "--graph", env=env)
        captures = vars_invocations(temp_root)

    output = f"{result.stdout}\n{result.stderr}"
    if (
        result.returncode != 0
        or result.stdout != graph_output
        or diagnostic_secret in output
    ):
        raise AssertionError(f"vars --graph did not preserve the inventory tree:\n{result.stdout}\n{result.stderr}")
    expected_captures = expected_graph_vars_invocations()
    if captures != expected_captures:
        raise AssertionError(
            f"vars --graph used a live or unexpected execution path: {captures!r}"
        )


def assert_vars_graph_reports_inventory_failure_without_disclosure() -> None:
    graph_output = "@all:\n  |--@lxcs:\n  |  |--fixture_host\n"
    diagnostic_secret = "GraphFailureDiagnosticSecret42"
    with tempfile.TemporaryDirectory(prefix="inspect-vars-graph-failure-") as temp_dir:
        temp_root = Path(temp_dir)
        env = vars_environment(
            temp_root,
            graph_output,
            inventory_stderr=f"inventory failed with {diagnostic_secret}\n",
            inventory_status=24,
        )
        result = run_inspect("vars", "--graph", env=env)

    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 1 or diagnostic_secret in output:
        raise AssertionError(
            f"vars --graph did not safely report inventory failure:\n{output}"
        )


def controlled_environment(temp_root: Path) -> dict[str, str]:
    home = temp_root / "home"
    bin_dir = temp_root / "bin"
    home.mkdir()
    bin_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
if "ansible-playbook" not in arguments:
    raise SystemExit(0)

Path(os.environ["INSPECT_TEST_CAPTURE"]).write_text(json.dumps({
    "argv": arguments,
    "marker": os.environ.get("HOMELAB_IAC_LIFECYCLE_WRAPPER"),
}), encoding="utf-8")
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "INSPECT_TEST_CAPTURE": str(temp_root / "capture.json"),
        }
    )
    return env


def assert_operations_route_through_shared_live_execution() -> None:
    cases = (
        ("credentials", (), "playbooks/validate-credentials.yml", "localhost", ()),
        ("connectivity", (), "playbooks/lab-connectivity.yml", "localhost", ()),
        ("containers", (), "playbooks/proxmox_api_check.yml", "localhost", ()),
        (
            "plan",
            ("--limit", "target_conflict,release_problem"),
            "playbooks/validate-infrastructure.yml",
            "target_conflict,release_problem",
            ("--limit", "target_conflict,release_problem", "--check"),
        ),
        (
            "probe",
            ("https://a.example/health", "https://b.example/?q=1"),
            "playbooks/service-probe.yml",
            "localhost",
            ("-e", "probe_urls=https://a.example/health,https://b.example/?q=1"),
        ),
    )
    for operation, options, playbook, prerequisite_target, operation_arguments in cases:
        with tempfile.TemporaryDirectory(prefix=f"inspect-{operation}-") as temp_dir:
            temp_root = Path(temp_dir)
            env = controlled_environment(temp_root)
            lock_path = Path(env["HOME"]) / ".ansible/homelab-iac-lifecycle.lock"
            lock_path.parent.mkdir(parents=True)
            with lock_path.open("a", encoding="utf-8") as shared_holder:
                fcntl.flock(shared_holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
                result = run_inspect(operation, *options, env=env)
            if result.returncode != 0:
                raise AssertionError(
                    f"{operation} did not coexist with a shared holder:\n"
                    f"{result.stdout}\n{result.stderr}"
                )
            capture = json.loads(
                (temp_root / "capture.json").read_text(encoding="utf-8")
            )
            expected_arguments = [
                "run",
                "--locked",
                "ansible-playbook",
                playbook,
                *operation_arguments,
                "-e",
                f"prerequisite_target_pattern={prerequisite_target}",
            ]
            if capture != {"argv": expected_arguments, "marker": "1"}:
                raise AssertionError(
                    f"{operation} routed incorrectly:\n"
                    f"expected={expected_arguments!r}\nactual={capture!r}"
                )


def assert_probe_rejects_invalid_urls_before_live_execution() -> None:
    for arguments in (
        ("probe",),
        ("probe", "http://a.example/"),
        ("probe", "https://a.example/,https://b.example/"),
        ("probe", "https://a.example/{{x}}"),
        ("connectivity", "https://a.example/"),
    ):
        with tempfile.TemporaryDirectory(prefix="inspect-probe-usage-") as temp_dir:
            temp_root = Path(temp_dir)
            result = run_inspect(*arguments, env=controlled_environment(temp_root))
            if (
                result.returncode != 2
                or not result.stderr.startswith("inspect.sh: ")
                or (temp_root / "capture.json").exists()
            ):
                raise AssertionError(
                    f"inspect {arguments!r} was not rejected as usage:\n"
                    f"{result.returncode}\n{result.stderr}"
                )


def assert_exclusive_contention_names_holder() -> None:
    for operation in ("credentials", "connectivity", "containers", "plan"):
        with tempfile.TemporaryDirectory(prefix=f"inspect-lock-{operation}-") as temp_dir:
            temp_root = Path(temp_dir)
            env = controlled_environment(temp_root)
            lock_path = Path(env["HOME"]) / ".ansible/homelab-iac-lifecycle.lock"
            holder_dir = Path(f"{lock_path}.holders")
            holder_dir.mkdir(parents=True)
            with lock_path.open("a", encoding="utf-8") as exclusive_holder:
                fcntl.flock(exclusive_holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
                (holder_dir / f"{os.getpid()}.holder").write_text(
                    f"pid={os.getpid()} parent_pid={os.getpid()} "
                    "worktree=/controlled/holder\n",
                    encoding="utf-8",
                )
                result = run_inspect(operation, env=env)
            output = f"{result.stdout}\n{result.stderr}"
            if (
                result.returncode != 75
                or f"pid={os.getpid()}" not in output
                or "worktree=/controlled/holder" not in output
                or (temp_root / "capture.json").exists()
            ):
                raise AssertionError(
                    f"{operation} did not fail immediately with holder identity:\n{output}"
                )


def live_fixture_environment(temp_root: Path, inventory_source: str) -> dict[str, str]:
    home = temp_root / "home"
    home.mkdir()
    write_controller_identity(home)
    inventory = temp_root / "inventory.yml"
    inventory.write_text(inventory_source, encoding="utf-8")
    vault_password = temp_root / "vault-pass"
    vault_password.write_text("unused-fixture-placeholder\n", encoding="utf-8")
    # Keep the public inspect grammar intact; inject fixture prerequisites only
    # at the Ansible invocation, where extra vars override production play vars.
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "ANSIBLE_INVENTORY": str(inventory),
            "ANSIBLE_VAULT_PASSWORD_FILE": str(vault_password),
            "ANSIBLE_COLLECTIONS_PATH": str(temp_root / "empty-collections"),
            "ANSIBLE_COLLECTIONS_SCAN_SYS_PATH": "false",
        }
    )
    return env


# Beside a copy of the production group_vars/all/proxmox.yml, which it follows
# alphabetically and so overrides.
CONNECTIVITY_PROXMOX = """
proxmox_api_host: 127.0.0.1
proxmox_pct_delegate_host: localhost
proxmox_ssh_port: {proxmox_port}
proxmox_ssh_user: {user}
proxmox_validate_pct: false
"""

CONNECTIVITY_INVENTORY = """
all:
  children:
    lxcs:
      vars:
        ansible_connection: ssh
        ansible_port: {guest_port}
        ansible_user: {user}
        ansible_ssh_private_key_file: "~/.ansible/ssh/proxmox_lxc"
        ansible_ssh_common_args: -F /dev/null
      hosts:
        pinned:
          ansible_host: 127.0.0.1
          proxmox_lxc_overrides: {{vmid: 7401}}
        impostor:
          ansible_host: localhost
          proxmox_lxc_overrides: {{vmid: 7402}}
        unreadable:
          ansible_host: 127.0.0.1
          proxmox_lxc_overrides: {{vmid: 7403}}
        stopped:
          ansible_host: localhost
          proxmox_lxc_overrides: {{vmid: 7404}}
"""

# The Proxmox host double: what each guest's host keys are, read by VMID.
CONNECTIVITY_PCT = """#!/bin/sh
case "$1 $2" in
  "exec 7401") cat '{guest_key}' ;;
  "exec 7402") cat '{other_key}' ;;
  "status 7403") echo 'status: running' ;;
  "status 7404") echo 'status: stopped' ;;
  *) exit 1 ;;
esac
"""


def assert_connectivity_trusts_only_keys_pinned_through_proxmox() -> None:
    """One real sshd stands in for Proxmox, another for every guest.

    The pinned guest starts with a stale fleet entry and must connect. The
    impostor presents a key other than the one Proxmox reports and must be
    unreachable. A running guest whose keys cannot be read fails before any
    connection. A stopped guest gets no entry and does not fail the pin. None
    of it reads the vault, which here cannot be decrypted.
    """
    # A short root keeps ControlPath sockets under the Unix socket length limit.
    with tempfile.TemporaryDirectory(prefix="pxpin-", dir="/tmp") as temp_dir:
        temp_root = Path(temp_dir)
        env = live_fixture_environment(temp_root, "")
        home = temp_root / "home"
        servers = {name: temp_root / name for name in ("proxmox", "guest")}
        bin_dir = temp_root / "bin"
        bin_dir.mkdir()
        for server in servers.values():
            server.mkdir()
            (server / "authorized_keys").write_text(
                (home / ".ansible/ssh/proxmox_lxc.pub").read_text()
            )
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["ANSIBLE_VAULT_PASSWORD_FILE"] = str(temp_root / "missing-vault-pass")
        env.pop("SSH_AUTH_SOCK", None)
        (temp_root / "vault.yml").write_text(
            "$ANSIBLE_VAULT;1.1;AES256\ninvalid-unrelated-ciphertext\n"
        )
        group_vars = temp_root / "group_vars" / "all"
        group_vars.mkdir(parents=True)
        (group_vars / "proxmox.yml").write_bytes(
            (REPO_ROOT / "inventory/group_vars/all/proxmox.yml").read_bytes()
        )
        guest_public_key = servers["guest"] / "host_key.pub"
        other_public_key = servers["proxmox"] / "host_key.pub"
        pct = bin_dir / "pct"
        pct.write_text(
            CONNECTIVITY_PCT.format(guest_key=guest_public_key, other_key=other_public_key)
        )
        pct.chmod(0o755)
        with (
            local_sshd(servers["proxmox"]) as proxmox_port,
            local_sshd(servers["guest"]) as guest_port,
        ):
            (group_vars / "zz_fixture.yml").write_text(
                CONNECTIVITY_PROXMOX.format(proxmox_port=proxmox_port, user=getpass.getuser())
            )
            (temp_root / "inventory.yml").write_text(
                CONNECTIVITY_INVENTORY.format(guest_port=guest_port, user=getpass.getuser())
            )
            guest_key = " ".join(guest_public_key.read_text().split()[:2])
            other_key = " ".join(other_public_key.read_text().split()[:2])
            pinned_entry = f"[127.0.0.1]:{guest_port}"
            fleet_file = home / ".ansible" / "known_hosts"
            fleet_file.write_text(f"# BEGIN pinned\n{pinned_entry} {other_key}\n# END pinned\n")
            result = subprocess.run(
                [str(INSPECT), "connectivity"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
        output = f"{result.stdout}\n{result.stderr}"
        fleet = fleet_file.read_text()

    failures = []
    if result.returncode == 0:
        failures.append("connectivity succeeded although targets were unreachable")
    if "SSH reachable: pinned" not in output:
        failures.append("the pinned guest did not connect over its stale entry")
    if f"# BEGIN pinned\n{pinned_entry} {guest_key}\n# END pinned" not in fleet:
        failures.append("pinning did not replace the pinned guest's stale entry")
    if (
        "SSH unreachable: impostor" not in output
        or "Host key verification failed" not in output
    ):
        failures.append("the impostor's key was not refused as unreachable")
    if not re.search(r"unreadable\s+:.*failed=1", output) or ": unreadable (" in output:
        failures.append("an unreadable running guest did not fail before connecting")
    if "SSH unreachable: stopped" not in output or "BEGIN stopped" in fleet:
        failures.append("a stopped guest was pinned or failed the pin")
    if failures:
        raise AssertionError(
            "\n".join(failures) + f"\n{output}\nfleet known_hosts:\n{fleet}"
        )


def assert_containers_includes_unreserved_node_container(*, deny_audit: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix="inspect-containers-live-") as temp_dir:
        temp_root = Path(temp_dir)
        certificate = temp_root / "certificate.pem"
        private_key = temp_root / "private-key.pem"
        generate_localhost_certificate(certificate, private_key)
        with local_proxmox_server(
            certificate,
            private_key,
            denied_audit_paths=("/vms",) if deny_audit else (),
        ) as server:
            env = live_fixture_environment(
                temp_root,
                f"""---
all:
  children:
    proxmox_api:
      hosts:
        api_fixture:
          ansible_connection: local
          proxmox_api_host: 127.0.0.1
          proxmox_api_port: {server.server_address[1]}
          proxmox_api_user: {CONTROLLED_API_USER}
          proxmox_api_token_id: {CONTROLLED_API_TOKEN_ID}
          proxmox_api_token_secret: {CONTROLLED_API_TOKEN_SECRET}
          proxmox_default_node: pve-a
          proxmox_verify_ssl: false
    lxcs:
      hosts:
        reserved_fixture:
          vmid: 5101
""",
            )
            result = run_inspect("containers", env=env)
    output = f"{result.stdout}\n{result.stderr}"
    if deny_audit:
        if (
            result.returncode == 0
            or "VM.Audit" not in output
            or any(path in server.requested_paths for path in LXC_API_PATHS)
        ):
            raise AssertionError(f"containers accepted an incomplete observation:\n{output}")
    elif result.returncode != 0 or "5105" not in output or "release-problem" not in output:
        raise AssertionError(f"containers omitted the unreserved node container:\n{output}")
    for credential_value in (
        CONTROLLED_API_USER,
        CONTROLLED_API_TOKEN_ID,
        CONTROLLED_API_TOKEN_SECRET,
    ):
        if credential_value in output:
            raise AssertionError("containers disclosed a controlled credential value")


def assert_credentials_walks_permission_ladder_without_disclosure() -> None:
    with tempfile.TemporaryDirectory(prefix="inspect-credentials-live-") as temp_dir:
        temp_root = Path(temp_dir)
        certificate = temp_root / "certificate.pem"
        private_key = temp_root / "private-key.pem"
        generate_localhost_certificate(certificate, private_key)
        with local_proxmox_server(certificate, private_key) as server:
            env = live_fixture_environment(
                temp_root,
                f"""---
all:
  children:
    proxmox_api:
      hosts:
        api_fixture:
          ansible_connection: local
          proxmox_api_host: 127.0.0.1
          proxmox_api_port: {server.server_address[1]}
          proxmox_api_user: {CONTROLLED_API_USER}
          proxmox_api_token_id: {CONTROLLED_API_TOKEN_ID}
          proxmox_api_token_secret: {CONTROLLED_API_TOKEN_SECRET}
          proxmox_default_node: pve-a
          proxmox_verify_ssl: false
""",
            )
            result = run_inspect("credentials", env=env)
    output = f"{result.stdout}\n{result.stderr}"
    required_results = (
        "API Connectivity:   PASS",
        "Cluster Access:     PASS",
        "Node Access:        PASS",
        "LXC Access:         PASS",
        "API Host:           127.0.0.1:",
    )
    if result.returncode != 0 or not all(value in output for value in required_results):
        raise AssertionError(f"credentials did not complete its permission ladder:\n{output}")
    for credential_value in (
        CONTROLLED_API_USER,
        CONTROLLED_API_TOKEN_ID,
        CONTROLLED_API_TOKEN_SECRET,
    ):
        if credential_value in output:
            raise AssertionError("credentials disclosed a controlled credential value")


def assert_public_plan_fails_before_effects_when_proxmox_trust_is_missing() -> None:
    with tempfile.TemporaryDirectory(prefix="inspect-plan-live-") as temp_dir:
        temp_root = Path(temp_dir)
        inventory = yaml.safe_load(
            (
                REPO_ROOT
                / "tests/regression/fixtures/lxc_fleet_preflight_inventory.yml"
            ).read_text(encoding="utf-8")
        )
        inventory["all"]["vars"] = {
            "proxmox_api_host": "127.0.0.1",
            "proxmox_api_port": 8006,
            "proxmox_api_user": CONTROLLED_API_USER,
            "proxmox_api_token_id": CONTROLLED_API_TOKEN_ID,
            "proxmox_api_token_secret": CONTROLLED_API_TOKEN_SECRET,
            "proxmox_default_node": "pve-a",
            "proxmox_verify_ssl": False,
            "proxmox_host": "127.0.0.1",
            "proxmox_ssh_connect_timeout": 1,
        }
        inventory["all"]["children"]["lxcs"]["vars"][
            "proxmox_fleet_observation_override"
        ] = None
        env = live_fixture_environment(temp_root, yaml.safe_dump(inventory))
        observation = temp_root / "observation.json"
        observation.write_text(json.dumps({"proxmox_vms": COMMON_OBSERVATION}), encoding="utf-8")
        env["LIFECYCLE_PROXMOX_OBSERVATION"] = str(observation)
        env["ANSIBLE_COLLECTIONS_PATH"] = str(FIXTURE_COLLECTIONS)
        certificate = temp_root / "certificate.pem"
        private_key = temp_root / "private-key.pem"
        generate_localhost_certificate(certificate, private_key)
        with local_proxmox_server(certificate, private_key) as server, local_ssh_port() as ssh_port:
            inventory["all"]["vars"]["proxmox_api_port"] = server.server_address[1]
            inventory["all"]["vars"]["proxmox_ssh_port"] = ssh_port
            Path(env["ANSIBLE_INVENTORY"]).write_text(
                yaml.safe_dump(inventory), encoding="utf-8"
            )
            result = run_inspect(
                "plan",
                "--limit",
                "target_conflict,release_problem",
                env=env,
            )
        lifecycle_observation_reached = observation.with_suffix(".calls").exists()

    output = f"{result.stdout}\n{result.stderr}"
    required_fragments = (
        "selected controller SSH identity is not trusted",
        "root@127.0.0.1",
        "./recover.sh proxmox-host-ssh",
        "will not modify authorized_keys",
    )
    if result.returncode == 0 or not all(
        fragment in output for fragment in required_fragments
    ):
        raise AssertionError(f"public plan did not report missing Proxmox trust:\n{output}")
    # Without a terminal, Ansible replaces a prompt with this warning.
    if "Password for " in output or "Not waiting for response to prompt" in output:
        raise AssertionError("public plan entered the password-driven mutation path")
    if lifecycle_observation_reached:
        raise AssertionError("public plan reached lifecycle observation after trust failed")
    for credential_value in (
        CONTROLLED_API_USER,
        CONTROLLED_API_TOKEN_ID,
        CONTROLLED_API_TOKEN_SECRET,
    ):
        if credential_value in output:
            raise AssertionError("public plan disclosed a controlled credential value")


def main() -> int:
    try:
        assert_explicit_operation_and_help()
        assert_vars_masks_vault_derived_values_without_live_execution()
        assert_vars_normalizes_inventory_failure_without_disclosure()
        assert_vars_suppresses_masker_failure_diagnostics()
        assert_vars_content_rule_ignores_seven_character_vault_values()
        assert_vars_graph_preserves_inventory_tree_without_live_execution()
        assert_vars_graph_reports_inventory_failure_without_disclosure()
        assert_operations_route_through_shared_live_execution()
        assert_probe_rejects_invalid_urls_before_live_execution()
        assert_exclusive_contention_names_holder()
        assert_connectivity_trusts_only_keys_pinned_through_proxmox()
        assert_containers_includes_unreserved_node_container()
        assert_containers_includes_unreserved_node_container(deny_audit=True)
        assert_credentials_walks_permission_ladder_without_disclosure()
        assert_public_plan_fails_before_effects_when_proxmox_trust_is_missing()
    except AssertionError as error:
        print(error, file=sys.stderr)
        return 1
    print("ok: inspect command exposes read-only managed-host diagnostics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
