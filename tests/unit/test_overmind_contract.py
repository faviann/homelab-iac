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
        self.assertNotIn("ansible_host", overmind_vars)
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
        self.assertEqual(bind_mounts["mp4"], "/tank/backups/overmind,mp=/backups/overmind")

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
        self.assertEqual(backups["owner"], "100000")
        self.assertEqual(backups["group"], "100000")
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

    def test_overmind_migrations_run_from_tagged_ghcr_image(self) -> None:
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        main_tasks = (
            REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/tasks/main.yml"
        ).read_text(encoding="utf-8")
        migration_tasks = (
            REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/tasks/overmind_migrations.yml"
        ).read_text(encoding="utf-8")

        self.assertTrue(overmind_vars["overmind_migrations_enabled"])
        self.assertEqual(overmind_vars["overmind_image_repository"], "ghcr.io/faviann/overmind")
        self.assertEqual(overmind_vars["overmind_image_tag"], "0.1.0")
        self.assertNotEqual(overmind_vars["overmind_image_tag"], "latest")
        self.assertEqual(overmind_vars["overmind_migration_network"], "postgres_default")

        self.assertLess(
            main_tasks.index("overmind_postgres_bootstrap.yml"),
            main_tasks.index("overmind_migrations.yml"),
        )
        self.assertIn("{{ overmind_image_repository }}:{{ overmind_image_tag }}", migration_tasks)
        self.assertIn("MEMSRV_ADMIN_CONNECTION_STRING", migration_tasks)
        self.assertIn("--entrypoint", migration_tasks)
        self.assertIn("memctl", migration_tasks)
        self.assertIn("migrate", migration_tasks)
        self.assertIn("changed_when: false", migration_tasks)
        self.assertIn("no_log: true", migration_tasks)
        self.assertIn("Fail when overmind DbUp migrations fail", migration_tasks)
        self.assertNotIn("ghcr.io/faviann/overmind:latest", migration_tasks)
        self.assertNotIn("schemaversions", migration_tasks)
        self.assertNotIn("CREATE TABLE", migration_tasks)
        self.assertNotIn("ALTER TABLE", migration_tasks)

    def test_overmind_admin_connection_string_is_not_deployed(self) -> None:
        searched_files = [
            *REPO_ROOT.glob("stacks/overmind/postgres/**/*"),
            *(
                REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/templates"
            ).glob("overmind*"),
            *(
                REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/files"
            ).glob("overmind*"),
        ]

        for path in searched_files:
            if path.is_file():
                self.assertNotIn(
                    "MEMSRV_ADMIN_CONNECTION_STRING",
                    path.read_text(encoding="utf-8"),
                    str(path.relative_to(REPO_ROOT)),
                )

    def test_overmind_postgres_backup_contract(self) -> None:
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        backup = overmind_vars["overmind_postgres_backup"]
        vault_example = load_yaml(REPO_ROOT / "inventory/group_vars/all/vault.yml.example")

        self.assertTrue(overmind_vars["overmind_postgres_backup_enabled"])
        self.assertEqual(backup["container_name"], "overmind-postgres")
        self.assertEqual(backup["admin_user"], "overmind")
        self.assertEqual(backup["admin_password"], "{{ vault_overmind_postgres_password }}")
        self.assertEqual(backup["database"], "memory")
        self.assertEqual(backup["backup_dir"], "/backups/overmind")
        self.assertGreaterEqual(backup["retention_count"], 7)
        self.assertGreaterEqual(backup["freshness_max_age_seconds"], 36 * 60 * 60)
        self.assertEqual(
            backup["discord_webhook_url"],
            "{{ vault_overmind_backup_discord_webhook_url }}",
        )
        self.assertIn("vault_overmind_backup_discord_webhook_url", vault_example)
        self.assertNotIn("REPLACE_ME", vault_example["vault_overmind_backup_discord_webhook_url"])

    def test_overmind_backup_role_assets_exist(self) -> None:
        role = REPO_ROOT / "playbooks/roles/config/lxc_docker_environment"

        for relative_path in [
            "files/overmind-postgres-backup",
            "files/overmind-postgres-backup-freshness",
            "templates/overmind-postgres-backup.env.j2",
            "templates/overmind-postgres-backup.service.j2",
            "templates/overmind-postgres-backup.timer.j2",
            "tasks/overmind_postgres_backup.yml",
        ]:
            self.assertTrue((role / relative_path).exists(), relative_path)

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
        self.assertEqual(
            host_requirements["bind_mounts"],
            ["/tank/overmind,mp=/data/overmind", "/tank/backups/overmind,mp=/backups/overmind"],
        )


if __name__ == "__main__":
    unittest.main()
