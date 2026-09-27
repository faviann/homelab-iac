#!/usr/bin/env python3
"""Contract checks for the Broodling Compose installation (broodling ADR 0001)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_ROOT = REPO_ROOT / "stacks/broodling/broodling"
ROLE_TASKS = REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/tasks"

DATA = "/data/broodling"
KEY_DIR = f"{DATA}/zeroshot-tls/key"
ROOT_DIR = f"{DATA}/zeroshot-tls/root"
CADDY_DATA = f"{DATA}/zeroshot-tls/data"
# The UID each long-running service writes as (readiness checks these; broodling's is the image user).
SERVICE_UID = {"broodling": "1654", "zeroshot": "0", "zeroshot-tls": "10443"}
CREDENTIAL_NAMES = {"GH_TOKEN", "GITHUB_TOKEN", "GATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY"}


def load_yaml(path: Path) -> dict | list:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def mounts(service: dict) -> set[tuple[str, str, bool]]:
    """Bind mounts as (source, target, read_only) from the short volume syntax."""
    result = set()
    for volume in service.get("volumes", []):
        source, target, *flags = volume.split(":")
        result.add((source, target, "ro" in flags))
    return result


def mounters(services: dict, source: str) -> dict[str, bool]:
    """Which services mount a host path, and whether read-only."""
    return {name: ro for name, service in services.items() for src, _, ro in mounts(service) if src == source}


class BroodlingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host_vars = load_yaml(REPO_ROOT / "inventory/host_vars/broodling.yml")
        self.compose = load_yaml(STACK_ROOT / "compose.yaml")
        self.services = self.compose["services"]
        self.init_tasks = load_yaml(ROLE_TASKS / "broodling_initialize.yml")

    def test_bind_sources_are_provisioned_for_the_service_that_writes_them(self) -> None:
        # Docker would otherwise create a missing bind source root-owned, unwritable by a non-root service.
        provisioned = {entry["path"]: entry for entry in self.host_vars["lxc_docker_env_host_directories"]}
        for task in self.init_tasks:
            file = task.get("ansible.builtin.file")
            if file:
                provisioned.update({path: file for path in task.get("loop", [file["path"]])})

        for name, service in self.services.items():
            for source, _, read_only in mounts(service):
                if not source.startswith("/"):
                    continue
                self.assertIn(source, provisioned, f"{name} mounts an unprovisioned directory")
                if not read_only and name in SERVICE_UID:
                    self.assertEqual(str(provisioned[source]["owner"]), SERVICE_UID[name], f"{name} cannot write {source}")

        # Native relaxes its state root's mode for worker UIDs; an every-run mode would undo that.
        every_run = {entry["path"] for entry in self.host_vars["lxc_docker_env_host_directories"]}
        self.assertNotIn(f"{DATA}/zeroshot/state", every_run)
        self.assertNotIn(f"{DATA}/zeroshot/home", every_run)

    def test_key_and_caddy_data_never_reach_the_other_services(self) -> None:
        self.assertEqual(mounters(self.services, KEY_DIR), {"zeroshot-tls": True, "initialize-tls": False})
        self.assertEqual(mounters(self.services, CADDY_DATA), {"zeroshot-tls": False})
        self.assertEqual(
            mounters(self.services, ROOT_DIR),
            {"broodling": True, "zeroshot": True, "zeroshot-tls": True, "initialize-tls": False},
        )

    def test_services_run_as_adr_0001_requires(self) -> None:
        broodling = self.services["broodling"]
        zeroshot = self.services["zeroshot"]
        tls = self.services["zeroshot-tls"]
        helper = self.services["initialize-tls"]

        self.assertNotIn("depends_on", broodling)
        for forbidden in ("ports", "user", "privileged", "network_mode", "cap_drop", "environment", "env_file"):
            self.assertNotIn(forbidden, zeroshot)
        self.assertEqual(zeroshot["restart"], "no")

        self.assertEqual(tls["user"], "10443:10443")
        self.assertEqual(tls["cap_drop"], ["ALL"])
        self.assertEqual(tls["cap_add"], ["NET_BIND_SERVICE"])
        self.assertEqual(len(tls["ports"]), 1)
        self.assertTrue(tls["ports"][0].endswith(":443"))

        self.assertEqual(helper["profiles"], ["initialize"])
        self.assertEqual(helper["network_mode"], "none")
        self.assertEqual(helper["image"], zeroshot["image"])

    def test_origin_agrees_across_target_proxy_and_client(self) -> None:
        invocation = json.loads((STACK_ROOT / "appdata/broodling/invocation.json").read_text(encoding="utf-8"))
        caddyfile = (STACK_ROOT / "appdata/zeroshot-tls/Caddyfile").read_text(encoding="utf-8")
        origin = invocation["directOrigin"]
        host = origin.removeprefix("https://")
        command = self.services["zeroshot"]["command"]
        inner_port = command[command.index("--listen") + 1].split(":")[1]

        self.assertEqual(invocation["directRootCertificate"], "/tls-root/root.crt")
        self.assertEqual(command[command.index("--public-origin") + 1], origin)
        self.assertIn(host, self.services["zeroshot-tls"]["networks"]["default"]["aliases"])
        self.assertIn(f"\n{host} {{", caddyfile)
        self.assertIn(f"reverse_proxy zeroshot:{inner_port}", caddyfile)

    def test_credentials_reach_only_broodling(self) -> None:
        self.assertIn({"path": "./broodling.env", "mode": "0600"}, self.compose["x-managed-files"])
        self.assertEqual(self.services["broodling"]["env_file"], "./broodling.env")
        for name, service in self.services.items():
            if name == "broodling":
                continue
            self.assertNotIn("env_file", service)
            self.assertEqual(set(service.get("environment", {})) & CREDENTIAL_NAMES, set())

    def test_initialization_runs_only_on_explicit_request(self) -> None:
        # Without the gate every ordinary deploy would run the refusing helpers and fail.
        include = next(
            task for task in load_yaml(ROLE_TASKS / "main.yml") if task.get("ansible.builtin.include_tasks") == "broodling_initialize.yml"
        )
        self.assertIn("broodling_initialize | default(false) | bool", include["when"])


if __name__ == "__main__":
    unittest.main()
