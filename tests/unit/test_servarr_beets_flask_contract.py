#!/usr/bin/env python3
"""Static contract checks for the servarr beets-flask rollout."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_ROOT = REPO_ROOT / "stacks/servarr/beets-flask"


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def beets_flask_bind_mounts() -> list[tuple[str, str]]:
    """Source and target of each declared bind mount, in either Compose spelling.

    Keeps every declaration, so conflicting mounts to one target stay visible.
    """
    service = load_yaml(STACK_ROOT / "compose.override.yaml")["services"]["beets-flask"]
    mounts = []
    for volume in service["volumes"]:
        if isinstance(volume, dict):
            if volume.get("type") != "bind":
                continue
            mounts.append((volume["source"], volume["target"]))
        else:
            source, target, *_ = volume.split(":")
            mounts.append((source, target))
    return mounts


class ServarrBeetsFlaskContractTests(unittest.TestCase):
    def test_servarr_inventory_exposes_beets_flask_contract(self) -> None:
        servarr_vars = load_yaml(REPO_ROOT / "inventory/host_vars/servarr.yml")

        compose_override = load_yaml(STACK_ROOT / "compose.override.yaml")
        self.assertTrue(compose_override["networks"]["shared"]["external"])
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

    def test_plugin_requirements_are_installed_for_the_enabled_plugins(self) -> None:
        requirements = (STACK_ROOT / "appdata/requirements.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        packages = {line.split("==")[0] for line in requirements if line}
        plugins = load_yaml(STACK_ROOT / "appdata/beets/config.yaml.j2")["plugins"]
        startup_script = (STACK_ROOT / "appdata/startup.sh").read_text(encoding="utf-8")

        # startup.sh patches this exact release's import layout for the image's
        # Beets 2.5 runtime; a different release needs a new patch.
        self.assertIn("beets-vgmdb==1.3.2", requirements)
        self.assertIn("VGMplug", plugins)
        self.assertIn(
            "from beets.autotag.distance import Distance, string_dist", startup_script
        )
        self.assertIn("chroma", plugins)
        self.assertIn("pyacoustid", packages)
        self.assertIn("apk add --no-cache chromaprint", startup_script)
        self.assertIn("discogs", plugins)
        self.assertIn("python3-discogs-client", packages)

    def test_beets_config_uses_installed_vgmdb_plugin_module_name(self) -> None:
        # beets-vgmdb installs the plugin module as VGMplug; `vgmdb` fails to load.
        beets_config = load_yaml(STACK_ROOT / "appdata/beets/config.yaml.j2")

        self.assertIn("VGMplug", beets_config["plugins"])
        self.assertNotIn("vgmdb", beets_config["plugins"])

    def test_replaygain_uses_available_ffmpeg_backend(self) -> None:
        # ffmpeg is the replaygain backend the beets-flask image already provides.
        beets_config = load_yaml(STACK_ROOT / "appdata/beets/config.yaml.j2")

        self.assertEqual(beets_config["replaygain"]["backend"], "ffmpeg")

    def test_beets_flask_startup_hook_is_executable_and_installs_mounted_requirements(self) -> None:
        compose_override = load_yaml(STACK_ROOT / "compose.override.yaml")
        managed_files = compose_override["x-managed-files"]

        startup_hook = next(
            entry
            for entry in managed_files
            if entry["path"] == "./appdata/startup.sh"
        )
        self.assertEqual(startup_hook["mode"], "0755")

        startup_script = (STACK_ROOT / "appdata/startup.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("python -m pip install -r /config/requirements.txt", startup_script)

    def test_media_mounts_keep_host_and_container_paths_identical(self) -> None:
        media_targets = ["/data/media/_ingest/music", "/data/media/music"]
        declared = sorted(
            (target, source)
            for source, target in beets_flask_bind_mounts()
            if target in media_targets
        )

        self.assertEqual(declared, [(target, target) for target in media_targets])

    def test_gui_inbox_and_terminal_target_the_declared_prereq_dir(self) -> None:
        compose_override = load_yaml(STACK_ROOT / "compose.override.yaml")
        gui_config = load_yaml(STACK_ROOT / "appdata/beets-flask/config.yaml")["gui"]
        ingest_dir = "/data/media/_ingest/music"

        self.assertIn(ingest_dir, compose_override["x-prereq-dirs"])
        self.assertEqual(gui_config["terminal"]["start_path"], ingest_dir)

        self.assertEqual(gui_config["inbox"]["folders"]["SoundtrackInbox"]["path"], ingest_dir)

    def test_appdata_is_mounted_as_the_container_config_dir(self) -> None:
        declared = [mount for mount in beets_flask_bind_mounts() if mount[1] == "/config"]

        self.assertEqual(declared, [("./appdata", "/config")])


if __name__ == "__main__":
    unittest.main()
