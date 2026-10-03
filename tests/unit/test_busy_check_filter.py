from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FILTER_PATH = REPO_ROOT / "playbooks" / "filter_plugins" / "busy_check.py"
BLOCK = 'x-busy-check: {service: app, command: ["true"], timeout: 5}\n'
SERVICES = "services: {app: {image: example/app:1}}\n"


def load_filters() -> dict:
    spec = importlib.util.spec_from_file_location("busy_check_filter", FILTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


FILTERS = load_filters()


def busy_check_declarations(stacks_source: Path) -> list[dict]:
    return FILTERS["busy_check_declarations"](str(stacks_source))


def write_stack(source: Path, name: str, files: dict[str, str]) -> None:
    (source / name).mkdir(parents=True)
    for file_name, content in files.items():
        (source / name / file_name).write_text(content, encoding="utf-8")


def test_runtime_reads_only_declarations_validation_accepts(tmp_path: Path) -> None:
    write_stack(tmp_path, "declared", {"compose.yaml": SERVICES + BLOCK})
    write_stack(tmp_path, "override", {"compose.yaml": SERVICES, "compose.override.yaml": BLOCK})
    write_stack(tmp_path, "undeclared", {"compose.yaml": SERVICES})
    write_stack(tmp_path, "template", {"compose.yaml": SERVICES, "compose.override.yaml.j2": BLOCK})
    write_stack(
        tmp_path, "double", {"compose.yaml": SERVICES + BLOCK, "compose.override.yaml": BLOCK}
    )
    write_stack(tmp_path, "unparseable", {"compose.yaml": "services: [\n"})
    write_stack(tmp_path, "compose-tags", {"compose.yaml": SERVICES + BLOCK + "x-ports: !reset []\n"})

    assert busy_check_declarations(tmp_path) == [
        {"stack": "compose-tags", "service": "app", "command": ["true"], "timeout": 5},
        {"stack": "declared", "service": "app", "command": ["true"], "timeout": 5},
        {
            "stack": "double",
            "error": "compose.x-busy-check: x-busy-check must be declared in only one Compose file",
        },
        {"stack": "override", "service": "app", "command": ["true"], "timeout": 5},
        {
            "stack": "template",
            "error": "compose.x-busy-check: x-busy-check is not supported in a template "
            "(compose.override.yaml.j2)",
        },
        {"stack": "unparseable", "error": "compose: compose.yaml could not be read as YAML"},
    ]


def test_a_host_without_a_stack_source_has_no_declarations(tmp_path: Path) -> None:
    assert busy_check_declarations(tmp_path / "missing") == []


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
