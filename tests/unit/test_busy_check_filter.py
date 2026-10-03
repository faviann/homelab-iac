from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FILTER_PATH = REPO_ROOT / "playbooks" / "filter_plugins" / "busy_check.py"
BLOCK = 'x-busy-check: {service: app, command: ["true"], timeout: 5}\n'
SERVICES = "services: {app: {image: example/app:1}}\n"


def load_module():
    spec = importlib.util.spec_from_file_location("busy_check_filter", FILTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module()
FILTERS = MODULE.FilterModule().filters()


def write_stack(source: Path, name: str, files: dict[str, str]) -> Path:
    (source / name).mkdir(parents=True)
    for file_name, content in files.items():
        (source / name / file_name).write_text(content, encoding="utf-8")
    return source / name


def declaration(timeout: int = 5, project: str = "stack") -> dict:
    return {"stack": "stack", "project": project, "service": "app", "command": ["true"], "timeout": timeout}


def check(service: str = "app", command: str = '["true"]', timeout: str = "5", extra: str = "") -> str:
    return (
        f"x-busy-check:\n  service: {service}\n  command: {command}\n  timeout: {timeout}\n{extra}"
    )


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"compose.yaml": SERVICES}, None),
        ({"compose.yaml": SERVICES + BLOCK}, declaration()),
        ({"compose.yml": SERVICES, "compose.override.yaml": BLOCK}, declaration()),
        ({"compose.yaml": "name: renamed\n" + SERVICES + BLOCK}, declaration(project="renamed")),
        ({"compose.yaml": SERVICES + check(timeout="1")}, declaration(timeout=1)),
        ({"compose.yaml": SERVICES + check(timeout="60")}, declaration(timeout=60)),
        ({"compose.yaml": SERVICES + BLOCK + "x-ports: !reset []\n"}, declaration()),
    ],
    ids=["undeclared", "base", "override", "named", "min-timeout", "max-timeout", "compose-tags"],
)
def test_reads_valid_declarations(tmp_path: Path, files: dict[str, str], expected: dict | None) -> None:
    assert MODULE.read_busy_check(write_stack(tmp_path, "stack", files)) == expected


@pytest.mark.parametrize(
    ("files", "path", "message"),
    [
        (
            {"compose.yaml": SERVICES + "x-busy-check: [app]\n"},
            "compose.x-busy-check",
            "x-busy-check must contain only service, command, and timeout",
        ),
        (
            {"compose.yaml": SERVICES + check(extra="  url: http://app\n")},
            "compose.x-busy-check",
            "x-busy-check must contain only service, command, and timeout",
        ),
        (
            {"compose.yaml": SERVICES + 'x-busy-check: {service: app, command: ["true"]}\n'},
            "compose.x-busy-check",
            "x-busy-check must contain only service, command, and timeout",
        ),
        (
            {"compose.yaml": SERVICES + check(service="missing")},
            "compose.x-busy-check.service",
            "service must name a service in the stack's Compose files",
        ),
        *(
            (
                {"compose.yaml": SERVICES + check(command=command)},
                "compose.x-busy-check.command",
                "command must be a non-empty list of non-empty strings",
            )
            for command in ('"true"', "[]", '["true", ""]', "[1]")
        ),
        *(
            (
                {"compose.yaml": SERVICES + check(timeout=timeout)},
                "compose.x-busy-check.timeout",
                "timeout must be an integer number of seconds from 1 to 60",
            )
            for timeout in ("0", "61", "true", '"10"')
        ),
        (
            {"compose.yaml": SERVICES, "compose.override.yaml.j2": BLOCK},
            "compose.x-busy-check",
            "x-busy-check is not supported in a template (compose.override.yaml.j2)",
        ),
        (
            {"compose.yaml": SERVICES + BLOCK, "compose.override.yaml": BLOCK},
            "compose.x-busy-check",
            "x-busy-check must be declared in only one Compose file",
        ),
        (
            {"compose.yaml": '"\nx-busy-check: {}\n"\n'},
            "compose.x-busy-check",
            "x-busy-check must be a top-level Compose key",
        ),
        (
            {"compose.yaml": SERVICES + BLOCK + "services: [\n"},
            "compose",
            "compose.yaml could not be read as YAML",
        ),
    ],
)
def test_rejects_malformed_declarations(
    tmp_path: Path, files: dict[str, str], path: str, message: str
) -> None:
    assert MODULE.read_busy_check(write_stack(tmp_path, "stack", files)) == (path, message)


def test_declarations_list_each_declaring_stack_or_its_error(tmp_path: Path) -> None:
    write_stack(tmp_path, "declared", {"compose.yaml": SERVICES + BLOCK})
    write_stack(tmp_path, "rejected", {"compose.yaml": BLOCK + "services: [\n"})
    write_stack(tmp_path, "undeclared", {"compose.yaml": SERVICES})
    write_stack(tmp_path, "undeclared-broken", {"compose.yaml": "services: [\n"})
    write_stack(
        tmp_path,
        "undeclared-template",
        {"compose.yaml": SERVICES, "compose.override.yaml.j2": "# no x-busy-check here\n"},
    )
    (tmp_path / "README.md").write_text("not a stack\n", encoding="utf-8")

    assert FILTERS["busy_check_declarations"](str(tmp_path)) == [
        {"stack": "declared", "project": "declared", "service": "app", "command": ["true"], "timeout": 5},
        {"stack": "rejected", "error": "compose: compose.yaml could not be read as YAML"},
    ]


def test_a_host_without_a_stack_source_has_no_declarations(tmp_path: Path) -> None:
    assert FILTERS["busy_check_declarations"](str(tmp_path / "missing")) == []


def probe(stack: str, rc: int = 0, stdout: str = "", **extra: object) -> dict:
    return {"item": {"stack": stack}, "rc": rc, "stdout_lines": stdout.splitlines(), **extra}


def test_result_defers_only_busy_and_failed_checks_with_their_reasons() -> None:
    declarations = [
        {"stack": "rejected", "error": "compose: compose.yaml could not be read as YAML"},
        {"stack": "busy", "service": "app", "command": ["true"], "timeout": 5},
    ]
    probes = {
        "results": [
            probe("idle", stdout="idle"),
            probe("absent", stdout="not_deployed\nnothing deployed"),
            probe("busy", stdout="busy"),
            probe("timeout", stdout="check_failed\ntimed out after 1s\nmore"),
            probe("gone", unreachable=True),
            probe("crashed", rc=127, stderr="sh: docker: not found\n"),
            probe("garbled", stdout="who knows", stderr=""),
            probe("noisy", stdout="check_failed\n" + "x" * 300),
        ]
    }

    assert FILTERS["busy_check_result"](declarations, probes) == {
        "deferred_stacks": [
            {"stack": "rejected", "state": "check_failed",
             "reason": "compose: compose.yaml could not be read as YAML"},
            {"stack": "busy", "state": "busy", "reason": ""},
            {"stack": "timeout", "state": "check_failed", "reason": "timed out after 1s more"},
            {"stack": "gone", "state": "check_failed", "reason": "guest unreachable"},
            {"stack": "crashed", "state": "check_failed",
             "reason": "probe failed: sh: docker: not found"},
            {"stack": "garbled", "state": "check_failed", "reason": "probe failed"},
            {"stack": "noisy", "state": "check_failed", "reason": "x" * 200},
        ],
        "host_deferred": True,
    }


def test_a_host_with_nothing_probed_is_not_deferred() -> None:
    assert FILTERS["busy_check_result"]([], {"results": []}) == {
        "deferred_stacks": [],
        "host_deferred": False,
    }
