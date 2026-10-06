from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from ansible.errors import AnsibleFilterError


REPO_ROOT = Path(__file__).resolve().parents[2]
FILTER_PATH = REPO_ROOT / "playbooks" / "filter_plugins" / "restart_on_change.py"
STACK_DIR = "/shared/host/stacks/app"


def load_filter():
    spec = importlib.util.spec_from_file_location("restart_on_change_filter", FILTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.restart_on_change_declarations


DECLARATIONS = load_filter()


PLAN = {"files_to_render": [], "files_to_copy": [{"dest_path": f"{STACK_DIR}/conf/app.yml"}]}


def compose_sources(block: str) -> list[dict]:
    content = f"services: {{web: {{image: web}}}}\nx-restart-on-change:\n{block}"
    return [{"target_dir": STACK_DIR, "content": content}]


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ("  worker: [./conf/app.yml]\n", "stack app: x-restart-on-change names unknown service worker"),
        ("  web: ./conf/app.yml\n", "stack app: x-restart-on-change web must be a list of paths"),
        ("  web: [./conf/missing.yml]\n", "stack app: x-restart-on-change path ./conf/missing.yml is not a file"),
    ],
    ids=["unknown-service", "malformed", "not-synced"],
)
def test_invalid_declaration_names_stack_and_path(block: str, message: str) -> None:
    with pytest.raises(AnsibleFilterError, match=message):
        DECLARATIONS(compose_sources(block), PLAN)
