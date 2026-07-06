from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FILTER_PATH = REPO_ROOT / "playbooks" / "filter_plugins" / "compose_env.py"


def load_filter_module():
    spec = importlib.util.spec_from_file_location("compose_env_filter", FILTER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compose_env_doubles_dollar_signs() -> None:
    module = load_filter_module()

    assert module.compose_env("pa$$word-${TOKEN}") == "pa$$$$word-$${TOKEN}"


def test_compose_env_stringifies_values() -> None:
    module = load_filter_module()

    assert module.compose_env(1234) == "1234"
