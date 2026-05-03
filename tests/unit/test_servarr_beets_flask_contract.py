#!/usr/bin/env python3
"""Static contract checks for the servarr beets-flask rollout."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class ServarrBeetsFlaskContractTests(unittest.TestCase):
    def test_servarr_inventory_exposes_beets_flask_contract(self) -> None:
        servarr_vars = load_yaml(REPO_ROOT / "inventory/host_vars/servarr.yml")

        self.assertEqual(servarr_vars["default_domain"], "admin.faviann.com")
        self.assertIn("shared", servarr_vars["lxc_docker_env_external_networks"])

        ingest_dir = next(
            entry
            for entry in servarr_vars["lxc_docker_env_host_directories"]
            if entry["path"] == "/data/media/_ingest/music"
        )
        self.assertEqual(ingest_dir["owner"], "{{ docker_uid }}")
        self.assertEqual(ingest_dir["group"], "{{ docker_gid }}")

        beets_stack_vars = servarr_vars["lxc_docker_env_stack_vars"]["beets-flask"]
        self.assertEqual(beets_stack_vars["acoustid_apikey"], "{{ vault_beets_acoustid_apikey }}")
        self.assertEqual(beets_stack_vars["discogs_token"], "{{ vault_beets_discogs_token }}")

    def test_lidarr_compose_reserves_managed_beets_hook_path(self) -> None:
        lidarr_compose = load_yaml(REPO_ROOT / "stacks/servarr/lidarr/compose.yaml")
        managed_files = lidarr_compose["x-managed-files"]

        beets_script = next(
            entry
            for entry in managed_files
            if entry["path"] == "./appdata/lidarr/scripts/beets-post-import.sh"
        )
        self.assertEqual(beets_script["mode"], "0755")


if __name__ == "__main__":
    unittest.main()