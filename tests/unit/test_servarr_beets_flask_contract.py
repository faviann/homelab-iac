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

    def test_beets_vgmdb_requirement_is_compatible_with_beets_flask_image(self) -> None:
        requirements_path = REPO_ROOT / "stacks/servarr/beets-flask/appdata/requirements.txt"
        requirements = requirements_path.read_text(encoding="utf-8").splitlines()

        self.assertIn("beets-vgmdb==1.3.2", requirements)
        self.assertIn("pyacoustid==1.3.1", requirements)
        self.assertIn("python3-discogs-client==2.8", requirements)

    def test_beets_config_uses_installed_vgmdb_plugin_module_name(self) -> None:
        beets_config = load_yaml(REPO_ROOT / "stacks/servarr/beets-flask/appdata/beets/config.yaml.j2")

        self.assertIn("VGMplug", beets_config["plugins"])
        self.assertNotIn("vgmdb", beets_config["plugins"])

    def test_replaygain_uses_available_ffmpeg_backend(self) -> None:
        beets_config = load_yaml(REPO_ROOT / "stacks/servarr/beets-flask/appdata/beets/config.yaml.j2")

        self.assertEqual(beets_config["replaygain"]["backend"], "ffmpeg")

    def test_game_soundtracks_route_by_exact_vgmdb_genre(self) -> None:
        beets_config = load_yaml(REPO_ROOT / "stacks/servarr/beets-flask/appdata/beets/config.yaml.j2")
        paths = beets_config["paths"]

        self.assertEqual(
            paths["genre:=Game"],
            "Soundtracks/Game/$album ($year)/$track - $title",
        )
        self.assertNotIn("albumtype:soundtrack albumtype2:game", paths)

    def test_discogs_video_game_music_style_routes_to_game_soundtracks(self) -> None:
        beets_config = load_yaml(REPO_ROOT / "stacks/servarr/beets-flask/appdata/beets/config.yaml.j2")
        paths = beets_config["paths"]

        self.assertEqual(
            paths["style:Video"],
            "Soundtracks/Game/$album ($year)/$track - $title",
        )
        self.assertLess(
            list(paths).index("style:Video"),
            list(paths).index("albumtype:soundtrack"),
        )

    def test_beets_flask_startup_hook_is_executable_and_patches_vgmplug(self) -> None:
        compose_override = load_yaml(REPO_ROOT / "stacks/servarr/beets-flask/compose.override.yaml")
        managed_files = compose_override["x-managed-files"]

        startup_hook = next(
            entry
            for entry in managed_files
            if entry["path"] == "./appdata/startup.sh"
        )
        self.assertEqual(startup_hook["mode"], "0755")

        startup_script = (REPO_ROOT / "stacks/servarr/beets-flask/appdata/startup.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("python -m pip install -r /config/requirements.txt", startup_script)
        self.assertIn("apk add --no-cache chromaprint", startup_script)
        self.assertIn("from beets.autotag.distance import Distance, string_dist", startup_script)
        self.assertIn('self._log.setLevel("ERROR")', startup_script)
        self.assertIn("import beetsplug.VGMplug", startup_script)


if __name__ == "__main__":
    unittest.main()
