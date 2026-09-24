"""Public contract tests for masked inventory values."""

from pathlib import Path
import sys

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.masked_inventory import mask_value  # noqa: E402


def test_mask_value_preserves_diagnostic_shape_without_case() -> None:
    assert mask_value('AbZ09$/,_" \n\t') == 'aaa99$/,_"·\\n\\t'


def test_mask_value_shortens_a_long_run_without_revealing_it() -> None:
    masked = mask_value("Z" * 40)

    assert len(masked) < 40
    assert not set(masked) & set("Zz")


def test_vault_example_keys_have_the_required_prefix() -> None:
    vault_example = yaml.safe_load(
        (REPO_ROOT / "inventory/vault.yml.example").read_text(
            encoding="utf-8"
        )
    )

    assert vault_example
    assert all(key.startswith("vault_") for key in vault_example)
