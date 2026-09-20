"""Each live operation reconciles what it consumes, and nothing else."""

from __future__ import annotations

import fcntl
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.live_dependencies import (  # noqa: E402
    LIVE_OPERATIONS,
    DependencyReconciliationError,
    UnsupportedLiveOperation,
    reconcile,
)

PUBLIC_COMMANDS = ("run.sh", "inspect.sh", "recover.sh")
PLAYBOOK_TOKEN = re.compile(r"site\.yml|playbooks/[A-Za-z0-9_-]+\.yml")
POISON_ROLE = "example.explodes"
ANSIBLE_CFG = """[defaults]
collections_path = collections
roles_path = playbooks/roles:.ansible/roles

[ssh_connection]
control_path = .ansible/cp/%%h-%%p-%%r
"""

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
    modules = manifest / "plugins/modules"
    modules.mkdir(parents=True, exist_ok=True)
    (modules / "dependency_probe.py").write_text(
        "from ansible.module_utils.basic import AnsibleModule\\n"
        "AnsibleModule(argument_spec=dict()).exit_json(changed=False, version="
        + repr(version) + ")\\n",
        encoding="utf-8",
    )
else:
    name, declared = spec.split(",")
    version = os.environ.get("GALAXY_INSTALLS_VERSION", declared)
    meta = install_path / name / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / ".galaxy_install_info").write_text(
        f"version: {{version}}\\n", encoding="utf-8"
    )
    tasks = install_path / name / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / "main.yml").write_text(
        "- name: Report the role version actually consumed\\n"
        "  ansible.builtin.set_fact:\\n"
        f"    consumed_role_version: '{{version}}'\\n",
        encoding="utf-8",
    )
"""

# Records every uv invocation, and runs the real reconciler when asked for one,
# so a test can tell "reconciled and rejected" from "never reconciled at all".
RECORDING_UV = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
expected_parent = os.environ.get("EXPECTED_CONTROL_PATH_PARENT")
if "ansible-playbook" in arguments and expected_parent:
    if not Path(expected_parent).is_dir():
        sys.stderr.write(f"missing ControlPath parent before ansible-playbook: {expected_parent}\\n")
        raise SystemExit(9)
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
    (project_root / "ansible.cfg").write_text(ANSIBLE_CFG, encoding="utf-8")

    fixture_bin = tmp_path / "bin"
    fixture_bin.mkdir()
    write_executable(fixture_bin / "uv", FAKE_UV)
    write_executable(fixture_bin / "ansible-galaxy", FAKE_GALAXY)

    monkeypatch.setenv("PATH", f"{fixture_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GALAXY_LOG", str(tmp_path / "galaxy.log"))
    monkeypatch.delenv("ANSIBLE_COLLECTIONS_PATH", raising=False)
    monkeypatch.delenv("ANSIBLE_ROLES_PATH", raising=False)
    monkeypatch.delenv("ANSIBLE_CONFIG", raising=False)
    monkeypatch.delenv("ANSIBLE_SSH_CONTROL_PATH", raising=False)
    monkeypatch.delenv("ANSIBLE_SSH_CONTROL_PATH_DIR", raising=False)
    monkeypatch.chdir(project_root)
    return project_root


@pytest.fixture
def live_fixture_project(
    fixture_project: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    # Only the real command boundary is copied; tests supply localhost plays.
    for relative in (
        "run.sh",
        "inspect.sh",
        "scripts/lib/live-execution.sh",
        "scripts/live_dependencies.py",
    ):
        target = fixture_project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    monkeypatch.setenv("HOME", str(fixture_project / "home"))
    return fixture_project


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


def test_ssh_operation_creates_the_configured_control_path_parent(
    fixture_project: Path,
) -> None:
    reconcile("playbooks/lab-connectivity.yml", project_root=fixture_project)

    control_path_parent = fixture_project / ".ansible" / "cp"
    assert control_path_parent.is_dir()
    assert control_path_parent.stat().st_mode & 0o777 == 0o700


def test_custom_control_path_preserves_existing_directory_permissions(
    fixture_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = fixture_project / "shared-sockets"
    directory.mkdir(mode=0o755)
    monkeypatch.setenv("ANSIBLE_SSH_CONTROL_PATH", str(directory / "%%h-%%p-%%r"))

    reconcile("playbooks/lab-connectivity.yml", project_root=fixture_project)

    assert directory.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("override", ["ANSIBLE_CONFIG", "ANSIBLE_SSH_CONTROL_PATH"])
def test_live_wrapper_prepares_the_control_path_ansible_actually_uses(
    live_fixture_project: Path, monkeypatch: pytest.MonkeyPatch, override: str
) -> None:
    fixture_project = live_fixture_project
    playbook = fixture_project / "playbooks/lab-connectivity.yml"
    playbook.parent.mkdir()
    playbook.write_text(
        """---
- name: Observe the SSH configuration without making an SSH connection
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: Require reconciliation of Ansible's effective control-path parent
      ansible.builtin.assert:
        that:
          - control_parent is directory
      vars:
        control_parent: >-
          {{ lookup('ansible.builtin.config', 'control_path',
                    plugin_type='connection', plugin_name='ssh') | dirname }}
""",
        encoding="utf-8",
    )
    control_path = fixture_project / "override-sockets/%%h-%%p-%%r"
    if override == "ANSIBLE_CONFIG":
        config = fixture_project / "alternate.cfg"
        config.write_text(f"[ssh_connection]\ncontrol_path = {control_path}\n")
        monkeypatch.setenv(override, str(config))
    else:
        monkeypatch.setenv(override, str(control_path))

    result = subprocess.run(
        ["bash", str(fixture_project / "inspect.sh"), "connectivity"],
        cwd=fixture_project,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_run_passthrough_prepares_explicit_ssh_control_path_before_ansible(
    live_fixture_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = live_fixture_project
    declare(project, {"community.proxmox": "9.9.9"}, {})
    install_collection(project, "community.proxmox", "9.9.9")
    control_parent = project / "passthrough-sockets"
    control_path = control_parent / "%h-%p-%r"
    uv_executable = shutil.which("uv")
    assert uv_executable is not None
    write_executable(Path(uv_executable), RECORDING_UV)
    monkeypatch.setenv("UV_RECORD", str(project / "uv-invocations.jsonl"))
    monkeypatch.setenv("EXPECTED_CONTROL_PATH_PARENT", str(control_parent))

    result = subprocess.run(
        [
            "bash",
            str(project / "run.sh"),
            "provision",
            "--",
            f"--ssh-common-args=-oControlPath={control_path}",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert control_parent.is_dir()


@pytest.mark.parametrize("source", ["config", "environment"])
def test_live_wrapper_prepares_control_path_from_effective_ssh_args(
    live_fixture_project: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    project = live_fixture_project
    control_parent = project / f"{source}-ssh-args-sockets"
    control_path = control_parent / "%h-%p-%r"
    if source == "config":
        config = project / "ssh-args.cfg"
        config.write_text(
            f"[ssh_connection]\nssh_args = -o ControlPath={control_path}\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("ANSIBLE_CONFIG", str(config))
    else:
        monkeypatch.setenv("ANSIBLE_SSH_ARGS", f"-o ControlPath={control_path}")
    uv_executable = shutil.which("uv")
    assert uv_executable is not None
    write_executable(Path(uv_executable), RECORDING_UV)
    monkeypatch.setenv("UV_RECORD", str(project / "uv-invocations.jsonl"))
    monkeypatch.setenv("EXPECTED_CONTROL_PATH_PARENT", str(control_parent))

    result = subprocess.run(
        ["bash", str(project / "inspect.sh"), "connectivity"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert control_parent.is_dir()


def test_ssh_args_control_path_precedes_cli_common_args(
    live_fixture_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = live_fixture_project
    declare(project, {"community.proxmox": "9.9.9"}, {})
    install_collection(project, "community.proxmox", "9.9.9")
    ssh_args_parent = project / "ssh-args-sockets"
    common_args_parent = project / "common-args-sockets"
    monkeypatch.setenv(
        "ANSIBLE_SSH_ARGS", f"-o ControlPath={ssh_args_parent}/%h-%p-%r"
    )
    uv_executable = shutil.which("uv")
    assert uv_executable is not None
    write_executable(Path(uv_executable), RECORDING_UV)
    monkeypatch.setenv("UV_RECORD", str(project / "uv-invocations.jsonl"))
    monkeypatch.setenv("EXPECTED_CONTROL_PATH_PARENT", str(ssh_args_parent))

    result = subprocess.run(
        [
            "bash",
            str(project / "run.sh"),
            "provision",
            "--",
            f"--ssh-common-args=-oControlPath={common_args_parent}/%h-%p-%r",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert ssh_args_parent.is_dir()
    assert not common_args_parent.exists()


def test_cli_ssh_extra_control_path_overrides_ssh_args_control_path(
    live_fixture_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = live_fixture_project
    declare(project, {"community.proxmox": "9.9.9"}, {})
    install_collection(project, "community.proxmox", "9.9.9")
    ssh_args_parent = project / "ignored-ssh-args-sockets"
    extra_args_parent = project / "ssh-extra-sockets"
    monkeypatch.setenv(
        "ANSIBLE_SSH_ARGS", f"-o ControlPath={ssh_args_parent}/%h-%p-%r"
    )
    uv_executable = shutil.which("uv")
    assert uv_executable is not None
    write_executable(Path(uv_executable), RECORDING_UV)
    monkeypatch.setenv("UV_RECORD", str(project / "uv-invocations.jsonl"))
    monkeypatch.setenv("EXPECTED_CONTROL_PATH_PARENT", str(extra_args_parent))

    result = subprocess.run(
        [
            "bash",
            str(project / "run.sh"),
            "provision",
            "--",
            f"--ssh-extra-args=-S{extra_args_parent}/%h-%p-%r",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert extra_args_parent.is_dir()


@pytest.mark.parametrize("shadow", ["none", "role", "collection"])
def test_live_wrapper_consumes_reconciled_pins_from_the_effective_config(
    live_fixture_project: Path, monkeypatch: pytest.MonkeyPatch, shadow: str
) -> None:
    project = live_fixture_project
    declare(
        project,
        {name: "9.9.9" for name in LIVE_OPERATIONS["site.yml"].collections},
        {"geerlingguy.docker": "7.9.0", POISON_ROLE: "1.0.0"},
    )
    settings = project / "settings"
    settings.mkdir()
    config = settings / "ansible.cfg"
    config.write_text(
        "[defaults]\ncollections_path = collections\n"
        "roles_path = roles-first:roles-last\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANSIBLE_CONFIG", str(config))
    if shadow == "role":
        # A correct pin in the last directory does not repair the older role
        # Ansible will find first. Observe the role's execution, not its files.
        for directory, version in (("roles-first", "1.0.0"), ("roles-last", "7.9.0")):
            role = settings / directory / "geerlingguy.docker"
            (role / "meta").mkdir(parents=True)
            (role / "meta/.galaxy_install_info").write_text(f"version: {version}\n")
            (role / "tasks").mkdir()
            (role / "tasks/main.yml").write_text(
                "- ansible.builtin.set_fact:\n"
                f"    consumed_role_version: '{version}'\n"
            )
    if shadow == "collection":
        # Adjacent collections precede even the configured collection paths.
        install_collection(project, "community.proxmox", "1.0.0")
        modules = (
            project / "collections/ansible_collections/community/proxmox/plugins/modules"
        )
        modules.mkdir(parents=True)
        (modules / "dependency_probe.py").write_text(
            "from ansible.module_utils.basic import AnsibleModule\n"
            "AnsibleModule(argument_spec=dict()).exit_json(changed=False, version='1.0.0')\n"
        )
    (project / "site.yml").write_text(
        """---
- name: Consume only fixture dependencies on localhost
  hosts: localhost
  connection: local
  gather_facts: false
  roles:
    - geerlingguy.docker
  tasks:
    - name: Execute the collection found by Ansible
      community.proxmox.dependency_probe:
      register: consumed_collection
    - name: Require the declared pins at the point of consumption
      ansible.builtin.assert:
        that:
          - consumed_collection.version == '9.9.9'
          - consumed_role_version == '7.9.0'
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(project / "run.sh")],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr


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


def test_credential_free_collection_fixture_satisfies_the_declared_pin() -> None:
    """Staging keeps live reconciliation off the network during validation."""
    manifest = (
        REPO_ROOT
        / "tests/regression/fixtures/lxc_lifecycle_facade_assets/collections"
        / "ansible_collections/community/proxmox/MANIFEST.json"
    )
    staged = json.loads(manifest.read_text(encoding="utf-8"))
    assert staged["collection_info"]["version"] == declared(
        "collections/requirements.yml", "collections"
    )["community.proxmox"]


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
