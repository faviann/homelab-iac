"""Each live operation reconciles what it consumes, and nothing else."""

from __future__ import annotations

import configparser
import fcntl
import json
import os
import re
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.live_dependencies import (  # noqa: E402
    COLLECTIONS_PATH,
    LIVE_OPERATIONS,
    ROLES_PATH,
    SSH_CONTROL_PATH_PARENT,
    DependencyReconciliationError,
    UnsupportedLiveOperation,
    reconcile,
)

PUBLIC_COMMANDS = ("run.sh", "inspect.sh", "recover.sh")
PLAYBOOK_TOKEN = re.compile(r"site\.yml|playbooks/[A-Za-z0-9_-]+\.yml")
POISON_ROLE = "example.explodes"
FAKE_UV = """#!/usr/bin/env python3
import os
import sys

arguments = sys.argv[1:]
while arguments and arguments[0] in ("run", "--locked"):
    arguments.pop(0)
os.execvp(arguments[0], arguments)
"""

# GALAXY_INSTALLS_VERSION lets a test stage an installer that reports success
# while leaving the wrong version behind. The poison-role check fails loudly if
# reconciliation ever widens back to the whole declaration file.
FAKE_GALAXY = f"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
with Path(os.environ["GALAXY_LOG"]).open("a", encoding="utf-8") as log:
    log.write(" ".join(arguments) + "\\n")

touched = list(arguments)
if "-r" in arguments:
    touched.append(Path(arguments[arguments.index("-r") + 1]).read_text(encoding="utf-8"))
if any({POISON_ROLE!r} in fragment for fragment in touched):
    sys.stderr.write("refusing to resolve {POISON_ROLE}\\n")
    raise SystemExit(9)

if os.environ.get("GALAXY_EXIT"):
    raise SystemExit(int(os.environ["GALAXY_EXIT"]))

install_path = Path(arguments[arguments.index("-p") + 1])
spec = next(argument for argument in arguments[2:] if not argument.startswith("-"))
if arguments[0] == "collection":
    name, version = spec.split(":")
    version = os.environ.get("GALAXY_INSTALLS_VERSION", version)
    namespace, collection = name.split(".", 1)
    manifest = install_path / "ansible_collections" / namespace / collection
    manifest.mkdir(parents=True, exist_ok=True)
    (manifest / "MANIFEST.json").write_text(
        json.dumps({{"collection_info": {{"version": version}}}}), encoding="utf-8"
    )
else:
    name, declared = spec.split(",")
    version = os.environ.get("GALAXY_INSTALLS_VERSION", declared)
    meta = install_path / name / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / ".galaxy_install_info").write_text(
        f"version: {{version}}\\n", encoding="utf-8"
    )
"""

# Records every uv invocation, and runs the real reconciler when asked for one,
# so a test can tell "reconciled and rejected" from "never reconciled at all".
RECORDING_UV = """#!/usr/bin/env python3
import json
import os
import sys
arguments = sys.argv[1:]
with open(os.environ["UV_RECORD"], "a", encoding="utf-8") as record:
    record.write(json.dumps(arguments) + "\\n")
if "scripts.live_dependencies" in arguments:
    os.execv(sys.executable, [sys.executable, *arguments[arguments.index("python") + 1:]])
"""


def declared(relative: str, key: str) -> dict[str, str]:
    document = yaml.safe_load((REPO_ROOT / relative).read_text(encoding="utf-8"))
    return {entry["name"]: str(entry["version"]) for entry in document[key]}


def write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def fixture_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / "project"
    (project_root / "collections").mkdir(parents=True)
    (project_root / "requirements").mkdir()

    fixture_bin = tmp_path / "bin"
    fixture_bin.mkdir()
    write_executable(fixture_bin / "uv", FAKE_UV)
    write_executable(fixture_bin / "ansible-galaxy", FAKE_GALAXY)

    monkeypatch.setenv("PATH", f"{fixture_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GALAXY_LOG", str(tmp_path / "galaxy.log"))
    monkeypatch.chdir(project_root)
    return project_root


def declare(project_root: Path, collections: dict[str, str], roles: dict[str, str]) -> None:
    (project_root / "collections" / "requirements.yml").write_text(
        yaml.safe_dump(
            {"collections": [{"name": name, "version": v} for name, v in collections.items()]}
        ),
        encoding="utf-8",
    )
    (project_root / "requirements" / "roles.yml").write_text(
        yaml.safe_dump({"roles": [{"name": name, "version": v} for name, v in roles.items()]}),
        encoding="utf-8",
    )


def install_collection(project_root: Path, name: str, version: str) -> None:
    namespace, collection = name.split(".", 1)
    manifest = (
        project_root / "collections" / "ansible_collections" / namespace / collection
    )
    manifest.mkdir(parents=True)
    (manifest / "MANIFEST.json").write_text(
        json.dumps({"collection_info": {"version": version}}), encoding="utf-8"
    )


def installed_collection(project_root: Path, name: str) -> str | None:
    namespace, collection = name.split(".", 1)
    manifest = (
        project_root
        / "collections"
        / "ansible_collections"
        / namespace
        / collection
        / "MANIFEST.json"
    )
    if not manifest.is_file():
        return None
    return json.loads(manifest.read_text(encoding="utf-8"))["collection_info"]["version"]


def installed_role(project_root: Path, name: str) -> str | None:
    install_info = project_root / ".ansible" / "roles" / name / "meta" / ".galaxy_install_info"
    if not install_info.is_file():
        return None
    return str(yaml.safe_load(install_info.read_text(encoding="utf-8"))["version"])


def galaxy_ran() -> bool:
    return Path(os.environ["GALAXY_LOG"]).exists()


def test_registry_covers_exactly_the_publicly_reachable_live_playbooks() -> None:
    reachable = {
        token
        for command in PUBLIC_COMMANDS
        for token in PLAYBOOK_TOKEN.findall(
            (REPO_ROOT / command).read_text(encoding="utf-8")
        )
    }
    assert reachable == set(LIVE_OPERATIONS)
    for playbook in LIVE_OPERATIONS:
        assert (REPO_ROOT / playbook).is_file()


def test_every_consumed_dependency_is_declared_with_an_exact_pin() -> None:
    """A registry name the declarations do not pin fails every live run."""
    collections = declared("collections/requirements.yml", "collections")
    roles = declared("requirements/roles.yml", "roles")
    for operation in LIVE_OPERATIONS.values():
        assert set(operation.collections) <= set(collections)
        assert set(operation.roles) <= set(roles)


def test_repository_paths_match_the_normal_ansible_configuration() -> None:
    config = configparser.ConfigParser(interpolation=None)
    config.read(REPO_ROOT / "ansible.cfg", encoding="utf-8")

    assert config.get("defaults", "collections_path") == str(COLLECTIONS_PATH)
    assert config.get("defaults", "roles_path").split(os.pathsep)[-1] == str(
        ROLES_PATH
    )
    assert Path(config.get("ssh_connection", "control_path")).parent == (
        SSH_CONTROL_PATH_PARENT
    )


def test_docker_role_is_claimed_only_by_configure_capable_operations() -> None:
    assert LIVE_OPERATIONS["playbooks/provision-lxcs.yml"].roles == ()
    for playbook in ("site.yml", "playbooks/configure-lxcs.yml"):
        assert "geerlingguy.docker" in LIVE_OPERATIONS[playbook].roles

    for playbook in ("playbooks/validate-credentials.yml", "playbooks/proxmox_api_check.yml"):
        operation = LIVE_OPERATIONS[playbook]
        assert operation.collections == ()
        assert operation.roles == ()
        assert operation.uses_ssh is False


def test_unsupported_playbook_is_rejected_before_any_reconciliation(
    fixture_project: Path,
) -> None:
    with pytest.raises(UnsupportedLiveOperation) as failure:
        reconcile("playbooks/unsupported.yml", project_root=fixture_project)
    assert "Unsupported live playbook 'playbooks/unsupported.yml'" in str(failure.value)
    assert not galaxy_ran()


def test_missing_consumed_collection_is_installed_at_the_declared_version(
    fixture_project: Path,
) -> None:
    declare(fixture_project, {"community.proxmox": "2.0.0"}, {})

    reconcile(
        "playbooks/provision-lxcs.yml",
        project_root=fixture_project,
    )

    assert installed_collection(fixture_project, "community.proxmox") == "2.0.0"


def test_drifting_consumed_collection_is_returned_to_the_declared_version(
    fixture_project: Path,
) -> None:
    declare(fixture_project, {"community.proxmox": "2.0.0"}, {})
    install_collection(fixture_project, "community.proxmox", "1.6.0")

    reconcile(
        "playbooks/provision-lxcs.yml",
        project_root=fixture_project,
    )

    assert installed_collection(fixture_project, "community.proxmox") == "2.0.0"


def test_matching_consumed_collection_costs_no_install(fixture_project: Path) -> None:
    declare(fixture_project, {"community.proxmox": "2.0.0"}, {})
    install_collection(fixture_project, "community.proxmox", "2.0.0")

    reconcile(
        "playbooks/provision-lxcs.yml",
        project_root=fixture_project,
    )

    assert not galaxy_ran()


def test_install_that_leaves_the_wrong_version_fails_naming_the_playbook(
    fixture_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    declare(fixture_project, {"community.proxmox": "2.0.0"}, {})
    monkeypatch.setenv("GALAXY_INSTALLS_VERSION", "1.6.0")

    with pytest.raises(DependencyReconciliationError) as failure:
        reconcile(
            "playbooks/provision-lxcs.yml",
            project_root=fixture_project,
        )

    message = str(failure.value)
    assert "playbooks/provision-lxcs.yml" in message
    assert "community.proxmox 2.0.0" in message
    assert "1.6.0" in message


def test_failing_installer_fails_naming_the_playbook(
    fixture_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    declare(fixture_project, {"community.proxmox": "2.0.0"}, {})
    monkeypatch.setenv("GALAXY_EXIT", "3")

    with pytest.raises(DependencyReconciliationError) as failure:
        reconcile(
            "playbooks/provision-lxcs.yml",
            project_root=fixture_project,
        )

    assert "playbooks/provision-lxcs.yml" in str(failure.value)
    assert "community.proxmox 2.0.0" in str(failure.value)


def test_consumed_but_undeclared_collection_fails_clearly(
    fixture_project: Path,
) -> None:
    declare(fixture_project, {}, {})

    with pytest.raises(DependencyReconciliationError) as failure:
        reconcile(
            "playbooks/provision-lxcs.yml",
            project_root=fixture_project,
        )

    message = str(failure.value)
    assert "playbooks/provision-lxcs.yml" in message
    assert "community.proxmox" in message
    assert "collections/requirements.yml" in message
    assert not galaxy_ran()


def test_consumed_but_undeclared_role_fails_clearly(fixture_project: Path) -> None:
    declare(
        fixture_project,
        {name: "1.0.0" for name in LIVE_OPERATIONS["site.yml"].collections},
        {},
    )
    for name in LIVE_OPERATIONS["site.yml"].collections:
        install_collection(fixture_project, name, "1.0.0")

    with pytest.raises(DependencyReconciliationError) as failure:
        reconcile("site.yml", project_root=fixture_project)

    message = str(failure.value)
    assert "site.yml" in message
    assert "geerlingguy.docker" in message
    assert "requirements/roles.yml" in message


def test_consumed_external_role_is_reconciled_and_verified(
    fixture_project: Path,
) -> None:
    declare(
        fixture_project,
        {name: "9.9.9" for name in LIVE_OPERATIONS["site.yml"].collections},
        {"geerlingguy.docker": "7.9.0"},
    )
    for name in LIVE_OPERATIONS["site.yml"].collections:
        install_collection(fixture_project, name, "9.9.9")

    reconcile("site.yml", project_root=fixture_project)

    assert installed_role(fixture_project, "geerlingguy.docker") == "7.9.0"


def test_unconsumed_role_never_participates_in_a_configure_run(
    fixture_project: Path,
) -> None:
    """A role declared beside a consumed one must not be resolved at all."""
    declare(
        fixture_project,
        {name: "9.9.9" for name in LIVE_OPERATIONS["site.yml"].collections},
        {"geerlingguy.docker": "7.9.0", POISON_ROLE: "1.0.0"},
    )
    for name in LIVE_OPERATIONS["site.yml"].collections:
        install_collection(fixture_project, name, "9.9.9")

    reconcile("site.yml", project_root=fixture_project)

    assert installed_role(fixture_project, "geerlingguy.docker") == "7.9.0"
    assert installed_role(fixture_project, POISON_ROLE) is None


def test_unconsumed_collection_drift_does_not_block_the_operation(
    fixture_project: Path,
) -> None:
    """The acceptance criterion: shared declarations are not a shared contract."""
    declare(
        fixture_project,
        {"community.proxmox": "2.0.0", "community.crypto": "3.3.0"},
        {"geerlingguy.docker": "7.9.0"},
    )
    install_collection(fixture_project, "community.proxmox", "2.0.0")
    install_collection(fixture_project, "community.crypto", "0.0.1")

    reconcile(
        "playbooks/provision-lxcs.yml",
        project_root=fixture_project,
    )

    assert not galaxy_ran()
    assert installed_collection(fixture_project, "community.crypto") == "0.0.1"


def test_api_only_operation_needs_neither_declarations_nor_a_control_path(
    fixture_project: Path,
) -> None:
    reconcile("playbooks/proxmox_api_check.yml", project_root=fixture_project)

    assert not galaxy_ran()
    assert not (fixture_project / ".ansible" / "cp").exists()


def test_ssh_operation_creates_the_repository_control_path_parent(
    fixture_project: Path,
) -> None:
    reconcile("playbooks/lab-connectivity.yml", project_root=fixture_project)

    control_path_parent = fixture_project / ".ansible" / "cp"
    assert control_path_parent.is_dir()
    assert control_path_parent.stat().st_mode & 0o777 == 0o700


def test_live_path_never_directs_the_caller_to_the_retired_bootstrap() -> None:
    live_sources = [
        REPO_ROOT / "scripts" / "live_dependencies.py",
        REPO_ROOT / "scripts" / "lib" / "live-execution.sh",
        REPO_ROOT / "playbooks" / "controller-prerequisites.yml",
        REPO_ROOT / "playbooks" / "proxmox-host-prerequisites.yml",
        *(REPO_ROOT / command for command in PUBLIC_COMMANDS),
    ]
    for source in live_sources:
        assert "setup.sh bootstrap" not in source.read_text(encoding="utf-8"), source


def run_boundary(
    tmp_path: Path, *arguments: str, hold_lock: bool = False
) -> tuple[subprocess.CompletedProcess[str], Path]:
    home = tmp_path / "home"
    (home / ".ansible").mkdir(parents=True)
    fixture_bin = tmp_path / "bin"
    fixture_bin.mkdir()
    write_executable(fixture_bin / "uv", RECORDING_UV)
    record = tmp_path / "uv-invocations.jsonl"

    script = tmp_path / "boundary.sh"
    script.write_text(
        "set -euo pipefail\n"
        f"source {REPO_ROOT / 'scripts/lib/live-execution.sh'}\n"
        f"run_live_playbook {' '.join(arguments)}\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fixture_bin}{os.pathsep}{os.environ['PATH']}",
        "UV_RECORD": str(record),
    }

    def invoke() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(script)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=environment,
            check=False,
            timeout=60,
        )

    if not hold_lock:
        return invoke(), record

    lock_path = home / ".ansible" / "homelab-iac-lifecycle.lock"
    Path(f"{lock_path}.holders").mkdir(parents=True)
    with lock_path.open("a", encoding="utf-8") as holder:
        holder.write("pid=4242 worktree=/controlled/holder\n")
        holder.flush()
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return invoke(), record


@pytest.mark.serial
def test_lock_contention_short_circuits_before_any_reconciliation(
    tmp_path: Path,
) -> None:
    result, record = run_boundary(
        tmp_path,
        "exclusive",
        "site.yml",
        hold_lock=True,
    )

    assert result.returncode == 75
    assert "/controlled/holder" in result.stderr
    assert not record.exists()


@pytest.mark.serial
def test_unsupported_playbook_stops_the_boundary_before_ansible(tmp_path: Path) -> None:
    result, record = run_boundary(tmp_path, "shared", "playbooks/unsupported.yml")

    assert result.returncode == 2
    assert "Unsupported live playbook 'playbooks/unsupported.yml'" in result.stderr
    invoked = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
    assert not any("ansible-playbook" in arguments for arguments in invoked)


@pytest.mark.serial
def test_reconciliation_precedes_ansible_at_the_live_boundary(tmp_path: Path) -> None:
    result, record = run_boundary(
        tmp_path, "shared", "playbooks/validate-credentials.yml"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    invoked = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
    assert "scripts.live_dependencies" in invoked[0]
    assert "ansible-playbook" in invoked[1]
