#!/usr/bin/env python3
"""Static contract checks for the complete Overmind deployment."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_ROOT = REPO_ROOT / "stacks/overmind/overmind"

sys.path.insert(0, str(REPO_ROOT / "playbooks/filter_plugins"))
from compose_env import credential_is_configured  # noqa: E402


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class OvermindContractTests(unittest.TestCase):
    def test_overmind_capabilities(self) -> None:
        inventory = load_yaml(REPO_ROOT / "inventory/hosts.yml")
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        all_children = inventory["all"]["children"]

        self.assertIn("overmind", all_children["cap_docker"]["hosts"])
        self.assertNotIn("overmind", all_children["cap_gpu"]["hosts"])
        self.assertNotIn("overmind", all_children["cap_wireguard"]["hosts"])
        self.assertFalse(overmind_vars["docker_agents_enabled"])
        self.assertFalse(overmind_vars["traefik_kop_enabled"])

    def test_overmind_storage_contract(self) -> None:
        # 999 is the postgres image's in-container UID/GID; the host-side tank
        # directories use the unprivileged root mapping 100000.
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        directories = {entry["path"]: entry for entry in overmind_vars["lxc_docker_env_host_directories"]}
        host_directories = {entry["path"]: entry for entry in overmind_vars["proxmox_lxc_host_directories"]}
        ownership_overrides = {
            entry["path"]: entry for entry in overmind_vars["lxc_docker_env_path_ownership_overrides"]
        }
        bind_mounts = overmind_vars["proxmox_lxc_bind_mounts_overrides"]

        self.assertEqual(bind_mounts["mp3"], "/tank/overmind,mp=/data/overmind")
        self.assertEqual(bind_mounts["mp4"], "/tank/backups/overmind,mp=/backups/overmind")
        self.assertEqual(host_directories["/tank/overmind"]["owner"], "100000")
        self.assertEqual(host_directories["/tank/overmind"]["group"], "100000")
        self.assertEqual(host_directories["/tank/overmind"]["mode"], "0755")
        self.assertEqual(directories["/data/overmind/postgres/pgdata"]["owner"], "999")
        self.assertEqual(directories["/data/overmind/postgres/pgdata"]["group"], "999")
        self.assertEqual(directories["/data/overmind/postgres/pgdata"]["mode"], "0700")
        self.assertEqual(ownership_overrides["/data/overmind/postgres/pgdata"]["owner"], "999")
        self.assertFalse(ownership_overrides["/data/overmind/postgres/pgdata"]["recurse"])
        self.assertEqual(host_directories["/tank/backups/overmind"]["mode"], "0700")

    def test_compose_owns_complete_upstream_dependency_chain(self) -> None:
        compose = load_yaml(STACK_ROOT / "compose.yaml")
        services = compose["services"]

        self.assertEqual(set(services), {"postgres", "bootstrap", "migrate", "server"})
        self.assertIn("pg_isready", str(services["postgres"]["healthcheck"]["test"]))
        self.assertEqual(services["bootstrap"]["depends_on"]["postgres"]["condition"], "service_healthy")
        self.assertEqual(
            services["migrate"]["depends_on"]["bootstrap"]["condition"],
            "service_completed_successfully",
        )
        self.assertEqual(
            services["server"]["depends_on"]["migrate"]["condition"],
            "service_completed_successfully",
        )
        # Postgres 18 images keep versioned data under /var/lib/postgresql, so the
        # mount target and the major version move together. A major change also
        # needs a dump and restore of the existing cluster.
        self.assertEqual(services["postgres"]["image"], "docker.io/library/postgres:18")
        self.assertIn("/data/overmind/postgres/pgdata:/var/lib/postgresql", services["postgres"]["volumes"])
        self.assertNotIn("ports", services["postgres"])
        for service_name in ["migrate", "server"]:
            image = services[service_name]["image"]
            self.assertIn("${OVERMIND_VERSION:?", image)
            self.assertFalse(image.endswith(":latest"))
        for service in services.values():
            self.assertNotIn("labels", service)
            self.assertNotIn("networks", service)

    def test_secret_templates_and_managed_key_file_contract(self) -> None:
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        vault_example = load_yaml(REPO_ROOT / "inventory/vault.yml.example")
        compose = load_yaml(STACK_ROOT / "compose.yaml")
        env_template = (STACK_ROOT / ".env.j2").read_text(encoding="utf-8")
        keys_template = (STACK_ROOT / "agent-keys.yaml.j2").read_text(encoding="utf-8")
        stack_vars = overmind_vars["lxc_docker_env_stack_vars"]["overmind"]
        server = compose["services"]["server"]

        self.assertEqual(stack_vars["postgres_admin_password"], "{{ vault_overmind_postgres_password }}")
        self.assertEqual(stack_vars["memsrv_password"], "{{ vault_overmind_memsrv_password }}")
        self.assertEqual(stack_vars["agent_key"], "{{ vault_overmind_homelab_dev_agent_key }}")
        self.assertIn("POSTGRES_ADMIN_PASSWORD={{ stack_vars.postgres_admin_password | compose_env }}", env_template)
        self.assertIn("MEMSRV_PASSWORD={{ stack_vars.memsrv_password | compose_env }}", env_template)
        self.assertIn(
            "key: {{ stack_vars.agent_key | required_credential | quote }}",
            keys_template,
        )
        self.assertIn({"path": "./agent-keys.yaml", "mode": "0600"}, compose["x-managed-files"])
        key_mounts = [
            volume
            for volume in server["volumes"]
            if volume["target"] == "${MEMSRV_AGENT_KEYS_PATH:-/run/secrets/agent-keys.yaml}"
        ]
        self.assertEqual(len(key_mounts), 1)
        self.assertIs(key_mounts[0]["read_only"], True)

        example_key = vault_example["vault_overmind_homelab_dev_agent_key"]
        self.assertTrue(example_key)
        self.assertFalse(credential_is_configured(example_key))

    def test_backup_targets_the_deployed_database(self) -> None:
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        compose = load_yaml(STACK_ROOT / "compose.yaml")
        main_tasks = (
            REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/tasks/main.yml"
        ).read_text(encoding="utf-8")
        backup = overmind_vars["overmind_postgres_backup"]
        backup_mount = overmind_vars["proxmox_lxc_bind_mounts_overrides"]["mp4"]
        postgres = compose["services"]["postgres"]

        self.assertIn("overmind_postgres_backup.yml", main_tasks)
        self.assertTrue(overmind_vars["overmind_postgres_backup_enabled"])
        self.assertEqual(backup["container_name"], postgres["container_name"])
        self.assertEqual(backup["admin_user"], postgres["environment"]["POSTGRES_USER"])
        self.assertEqual(
            backup["admin_password"],
            overmind_vars["lxc_docker_env_stack_vars"]["overmind"]["postgres_admin_password"],
        )
        self.assertIn(
            f"SELECT 'CREATE DATABASE {backup['database']}'",
            "\n".join(compose["services"]["bootstrap"]["command"]),
        )
        self.assertEqual(f"mp={backup['backup_dir']}", backup_mount.split(",")[1])


if __name__ == "__main__":
    unittest.main()
