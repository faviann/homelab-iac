#!/usr/bin/env python3
"""Static contract checks for the overmind Postgres substrate."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class OvermindContractTests(unittest.TestCase):
    def test_overmind_inventory_contract(self) -> None:
        inventory = load_yaml(REPO_ROOT / "inventory/hosts.yml")
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        all_children = inventory["all"]["children"]
        overrides = overmind_vars["proxmox_lxc_overrides"]

        self.assertIn("overmind", all_children["tier_small"]["hosts"])
        self.assertIn("overmind", all_children["cap_docker"]["hosts"])
        self.assertNotIn("overmind", all_children["cap_gpu"]["hosts"])
        self.assertNotIn("overmind", all_children["cap_wireguard"]["hosts"])

        self.assertEqual(overrides["vmid"], 307)
        self.assertEqual(overrides["hostname"], "overmind")
        self.assertEqual(overrides["description"], "Overmind memory substrate managed via Ansible")
        self.assertEqual(overrides["tags"], ["ansible", "overmind", "memory", "database"])
        self.assertEqual(overmind_vars["ansible_host"], "10.1.2.83")
        self.assertFalse(overmind_vars["docker_agents_enabled"])
        self.assertFalse(overmind_vars["traefik_kop_enabled"])

    def test_overmind_storage_contract(self) -> None:
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        directories = {entry["path"]: entry for entry in overmind_vars["lxc_docker_env_host_directories"]}
        host_directories = {entry["path"]: entry for entry in overmind_vars["proxmox_lxc_host_directories"]}
        ownership_overrides = {
            entry["path"]: entry for entry in overmind_vars["lxc_docker_env_path_ownership_overrides"]
        }
        bind_mounts = overmind_vars["proxmox_lxc_bind_mounts_overrides"]

        self.assertEqual(bind_mounts["mp3"], "/tank/overmind,mp=/data/overmind")

        pgdata_source = host_directories["/tank/overmind"]
        self.assertEqual(pgdata_source["owner"], '100000')
        self.assertEqual(pgdata_source["group"], '100000')
        self.assertEqual(pgdata_source["mode"], "0755")

        pgdata = directories["/data/overmind/postgres/pgdata"]
        self.assertEqual(pgdata["owner"], '999')
        self.assertEqual(pgdata["group"], '999')
        self.assertEqual(pgdata["mode"], "0700")
        self.assertEqual(ownership_overrides["/data/overmind/postgres/pgdata"]["owner"], '999')
        self.assertEqual(ownership_overrides["/data/overmind/postgres/pgdata"]["group"], '999')
        self.assertFalse(ownership_overrides["/data/overmind/postgres/pgdata"]["recurse"])

        backups = host_directories["/tank/backups/overmind"]
        self.assertEqual(backups["owner"], "root")
        self.assertEqual(backups["group"], "root")
        self.assertEqual(backups["mode"], "0700")

    def test_overmind_stack_is_postgres_18_without_lan_port(self) -> None:
        compose = load_yaml(REPO_ROOT / "stacks/overmind/postgres/compose.yaml")
        services = compose["services"]

        self.assertEqual(set(services), {"postgres"})
        self.assertEqual(compose["x-prereq-dirs"], ["/data/overmind/postgres/pgdata"])
        postgres = services["postgres"]
        self.assertEqual(postgres["image"], "docker.io/library/postgres:18")
        self.assertNotIn("ports", postgres)
        self.assertNotIn("labels", postgres)
        self.assertIn("/data/overmind/postgres/pgdata:/var/lib/postgresql", postgres["volumes"])
        self.assertEqual(postgres["stop_grace_period"], "60s")

    def test_overmind_stack_env_and_secret_wiring(self) -> None:
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        env_template = (REPO_ROOT / "stacks/overmind/postgres/.env.j2").read_text(encoding="utf-8")

        stack_vars = overmind_vars["lxc_docker_env_stack_vars"]["postgres"]
        self.assertEqual(stack_vars["postgres_password"], "{{ vault_overmind_postgres_password }}")
        self.assertIn("POSTGRES_DB=overmind", env_template)
        self.assertIn("POSTGRES_USER=overmind", env_template)
        self.assertIn("POSTGRES_PASSWORD={{ stack_vars.postgres_password | compose_env }}", env_template)
        self.assertNotIn("MEMSRV_CONNECTION_STRING", env_template)
        self.assertNotIn("REPLACE_ME", env_template)

    def test_overmind_memsrv_database_bootstrap_contract(self) -> None:
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        bootstrap = overmind_vars["overmind_postgres_bootstrap"]
        stack_vars = overmind_vars["lxc_docker_env_stack_vars"]

        self.assertTrue(overmind_vars["overmind_postgres_bootstrap_enabled"])
        self.assertEqual(bootstrap["container_name"], "overmind-postgres")
        self.assertEqual(bootstrap["admin_user"], "overmind")
        self.assertEqual(bootstrap["admin_database"], "overmind")
        self.assertEqual(bootstrap["admin_password"], "{{ vault_overmind_postgres_password }}")
        self.assertEqual(bootstrap["memory_database"], "memory")
        self.assertEqual(bootstrap["memsrv_role"], "memsrv")
        self.assertEqual(bootstrap["memsrv_password"], "{{ vault_overmind_memsrv_password }}")
        self.assertEqual(
            overmind_vars["overmind_memsrv_connection_string"],
            "postgresql://memsrv:{{ vault_overmind_memsrv_password | urlencode }}@overmind-postgres:5432/memory",
        )
        self.assertEqual(
            stack_vars["memsrv"],
            {"memsrv_connection_string": "{{ overmind_memsrv_connection_string }}"},
        )
        self.assertNotIn("memsrv_connection_string", stack_vars["postgres"])

    def test_overmind_stack_metadata_documents_host_binding(self) -> None:
        metadata = load_yaml(REPO_ROOT / "stacks/overmind/postgres/stack.yaml")
        host_requirements = metadata["runtime"]["host_requirements"]

        self.assertEqual(metadata["portability"]["tier"], "host-bound-app")
        self.assertNotIn("template_inputs", metadata["runtime"])
        self.assertEqual(host_requirements["external_networks"], [])
        self.assertEqual(
            host_requirements["host_directories"],
            ["/data/overmind/postgres/pgdata", "/tank/overmind", "/tank/backups/overmind"],
        )
        self.assertEqual(host_requirements["ownership_overrides"], ["/data/overmind/postgres/pgdata"])
        self.assertEqual(host_requirements["bind_mounts"], ["/tank/overmind,mp=/data/overmind"])


if __name__ == "__main__":
    unittest.main()
