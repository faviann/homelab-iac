#!/usr/bin/env python3
"""Static contract checks for the complete Overmind deployment."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_ROOT = REPO_ROOT / "stacks/overmind/overmind"


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
        self.assertEqual(overrides["description"], "Overmind memory service managed via Ansible")
        self.assertEqual(overrides["tags"], ["ansible", "overmind", "memory"])
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

        self.assertEqual(compose["name"], "overmind")
        self.assertEqual(list(services), ["postgres", "bootstrap", "migrate", "server"])
        self.assertEqual(services["bootstrap"]["depends_on"]["postgres"]["condition"], "service_healthy")
        self.assertEqual(
            services["migrate"]["depends_on"]["bootstrap"]["condition"],
            "service_completed_successfully",
        )
        self.assertEqual(
            services["server"]["depends_on"]["migrate"]["condition"],
            "service_completed_successfully",
        )
        self.assertEqual(services["postgres"]["image"], "docker.io/library/postgres:18")
        self.assertIn("/data/overmind/postgres/pgdata:/var/lib/postgresql", services["postgres"]["volumes"])
        self.assertEqual(services["server"]["ports"], ["${OVERMIND_HTTP_BIND:-0.0.0.0}:${OVERMIND_HTTP_PORT:-8080}:8080"])
        self.assertNotIn("ports", services["postgres"])
        self.assertTrue(services["server"]["volumes"][0]["read_only"])
        self.assertEqual(services["server"]["volumes"][0]["target"], "${MEMSRV_AGENT_KEYS_PATH:-/run/secrets/agent-keys.yaml}")
        for service in services.values():
            self.assertNotIn("labels", service)
            self.assertNotIn("networks", service)

    def test_images_are_pinned_and_healthchecks_match_the_runtime_contract(self) -> None:
        compose = load_yaml(STACK_ROOT / "compose.yaml")
        services = compose["services"]
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")

        self.assertEqual(overmind_vars["lxc_docker_env_stack_vars"]["overmind"]["overmind_version"], "1.0.0")
        for service_name in ["migrate", "server"]:
            image = services[service_name]["image"]
            self.assertIn("${OVERMIND_VERSION:?", image)
            self.assertFalse(image.endswith(":latest"))
        self.assertIn("pg_isready -U postgres -d postgres", services["postgres"]["healthcheck"]["test"][1])
        self.assertEqual(
            services["server"]["healthcheck"]["test"],
            [
                "CMD",
                "/bin/bash",
                "-ec",
                "exec 3<>/dev/tcp/127.0.0.1/8080; "
                'printf "GET /healthz HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n" >&3; '
                'IFS= read -r status <&3; [[ "$$status" == *" 200 "* ]]',
            ],
        )

    def test_secret_templates_and_managed_key_file_contract(self) -> None:
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        vault_example = load_yaml(REPO_ROOT / "inventory/group_vars/all/vault.yml.example")
        compose = load_yaml(STACK_ROOT / "compose.yaml")
        env_template = (STACK_ROOT / ".env.j2").read_text(encoding="utf-8")
        keys_template = (STACK_ROOT / "agent-keys.yaml.j2").read_text(encoding="utf-8")
        stack_vars = overmind_vars["lxc_docker_env_stack_vars"]["overmind"]

        self.assertEqual(stack_vars["postgres_admin_password"], "{{ vault_overmind_postgres_password }}")
        self.assertEqual(stack_vars["memsrv_password"], "{{ vault_overmind_memsrv_password }}")
        self.assertEqual(stack_vars["agent_key"], "{{ vault_overmind_homelab_dev_agent_key }}")
        self.assertIn("temporary during active application design", env_template.lower())
        self.assertIn("POSTGRES_ADMIN_PASSWORD={{ stack_vars.postgres_admin_password | compose_env }}", env_template)
        self.assertIn("MEMSRV_PASSWORD={{ stack_vars.memsrv_password | compose_env }}", env_template)
        self.assertIn("key: {{ stack_vars.agent_key | quote }}", keys_template)
        self.assertIn("agent_id: homelab-dev", keys_template)
        self.assertIn("default_namespace: memory-system", keys_template)
        self.assertIn("- memory-system", keys_template)
        self.assertEqual(
            compose["x-managed-files"],
            [{"path": "./agent-keys.yaml", "mode": "0600"}],
        )
        self.assertEqual(
            vault_example["vault_overmind_homelab_dev_agent_key"],
            "REPLACE_WITH_RANDOM_BEARER_KEY",
        )
        self.assertNotIn("REPLACE_ME", env_template)
        self.assertNotIn("REPLACE_ME", keys_template)

    def test_obsolete_ansible_provisioning_is_removed_and_backup_remains(self) -> None:
        overmind_vars = load_yaml(REPO_ROOT / "inventory/host_vars/overmind.yml")
        main_tasks = (
            REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/tasks/main.yml"
        ).read_text(encoding="utf-8")
        role_tasks = REPO_ROOT / "playbooks/roles/config/lxc_docker_environment/tasks"

        self.assertNotIn("overmind_postgres_bootstrap", overmind_vars)
        self.assertNotIn("overmind_migrations", overmind_vars)
        self.assertNotIn("overmind_postgres_bootstrap.yml", main_tasks)
        self.assertNotIn("overmind_migrations.yml", main_tasks)
        self.assertFalse((role_tasks / "overmind_postgres_bootstrap.yml").exists())
        self.assertFalse((role_tasks / "overmind_migrations.yml").exists())
        self.assertIn("overmind_postgres_backup.yml", main_tasks)

        backup = overmind_vars["overmind_postgres_backup"]
        self.assertTrue(overmind_vars["overmind_postgres_backup_enabled"])
        self.assertEqual(backup["container_name"], "overmind-postgres")
        self.assertEqual(backup["admin_user"], "postgres")
        self.assertEqual(backup["admin_password"], "{{ vault_overmind_postgres_password }}")
        self.assertEqual(backup["database"], "memory")
        self.assertEqual(backup["backup_dir"], "/backups/overmind")

    def test_stack_metadata_documents_host_binding(self) -> None:
        metadata = load_yaml(STACK_ROOT / "stack.yaml")
        host_requirements = metadata["runtime"]["host_requirements"]

        self.assertEqual(metadata["name"], "overmind")
        self.assertEqual(metadata["portability"]["tier"], "host-bound-app")
        self.assertNotIn("template_inputs", metadata["runtime"])
        self.assertEqual(host_requirements["external_networks"], [])
        self.assertEqual(
            host_requirements["host_directories"],
            ["/data/overmind/postgres/pgdata", "/tank/overmind", "/tank/backups/overmind"],
        )


if __name__ == "__main__":
    unittest.main()
