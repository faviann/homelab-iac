#!/usr/bin/env python3
"""Static inventory checks for the workstation LXC contract."""

from __future__ import annotations

import posixpath
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSTATION_HOME = "{{ workstation_home }}"
EXTERNALSERVICE_PATH = (
    REPO_ROOT / "stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml"
)
WORKSTATION_ORIGIN_HOST = "workstation.faviann.vms"
# A workstation URL with no port uses its scheme default; any other scheme raises
# KeyError rather than dropping the backend from the check.
DEFAULT_PORTS = {"http": 80, "https": 443}

# Every home path that must survive an LXC rebuild. Dropping one loses that
# state on the next rebuild, so removal is a deliberate edit here; adding a
# path needs none. A bind file's content seeds a fresh workstation; without it
# the role creates an empty .claude.json, which is not valid JSON.
DURABLE_HOME_LINKS = (
    ("claude", "bind_mount", ".claude", "0700", None),
    ("claude_config", "bind_file", ".claude.json", "0600", "{}\n"),
    ("codex", "bind_mount", ".codex", "0700", None),
    ("agents", "bind_mount", ".agents", "0700", None),
    ("pi", "bind_mount", ".pi", "0700", None),
    ("omp", "bind_mount", ".omp", "0700", None),
    ("opencode_config", "bind_mount", ".config/opencode", "0700", None),
    ("opencode_data", "bind_mount", ".local/share/opencode", "0700", None),
    ("opencode_state", "bind_mount", ".local/state/opencode", "0700", None),
    ("agent_of_empires", "bind_mount", ".config/agent-of-empires", "0700", None),
    ("hermes", "bind_mount", ".hermes", "0700", None),
    ("openclaw", "bind_mount", ".openclaw", "0700", None),
    ("moraine", "bind_mount", ".moraine", "0700", None),
    ("lobu", "bind_mount", ".config/lobu", "0700", None),
    ("herdr", "bind_mount", ".config/herdr", "0700", None),
    ("collie_state", "bind_mount", ".local/state/collie", "0700", None),
    ("repos", "bind_mount", "repos", "0755", None),
)


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def routed_workstation_ports(services: dict) -> set[int]:
    """Effective port of every Traefik backend whose URL targets the workstation."""
    ports = set()
    for service in services.values():
        for server in service["loadBalancer"]["servers"]:
            url = urlsplit(server["url"])
            if url.hostname == WORKSTATION_ORIGIN_HOST:
                ports.add(url.port or DEFAULT_PORTS[url.scheme])
    return ports


def at_or_under(path: str, ancestor: str) -> bool:
    """True when path is ancestor itself or lives beneath it.

    Compares whole path components so `.../herdr` and `.../herdr-x` stay distinct.
    """
    path = posixpath.normpath(path)
    ancestor = posixpath.normpath(ancestor)
    return path == ancestor or path.startswith(ancestor + "/")


class WorkstationInventoryTests(unittest.TestCase):
    def test_workstation_capabilities(self) -> None:
        inventory = load_yaml(REPO_ROOT / "inventory/hosts.yml")
        workstation_vars = load_yaml(REPO_ROOT / "inventory/host_vars/workstation.yml")
        all_children = inventory["all"]["children"]

        self.assertIn("workstation", all_children["cap_docker"]["hosts"])
        self.assertNotIn("workstation", all_children["cap_wireguard"]["hosts"])
        self.assertIs(workstation_vars["workstation_enabled"], True)
        self.assertIs(workstation_vars["lxc_origin_firewall_enabled"], True)
        self.assertIs(workstation_vars["workstation_persistent_home_enabled"], True)
        self.assertIs(workstation_vars["docker_agents_enabled"], False)
        self.assertIs(workstation_vars["traefik_kop_enabled"], False)

    def test_workstation_user_keeps_the_uid_that_owns_its_durable_data(self) -> None:
        # Persistent-home backing files and stack appdata already on the host
        # are owned by the mapped UID/GID 1000. A different effective docker_uid
        # would leave the workstation user unable to read its own durable state.
        workstation_vars = load_yaml(REPO_ROOT / "inventory/host_vars/workstation.yml")
        cap_docker_vars = load_yaml(REPO_ROOT / "inventory/group_vars/cap_docker/vars.yml")

        self.assertNotIn("docker_uid", workstation_vars)
        self.assertNotIn("docker_gid", workstation_vars)
        self.assertEqual(cap_docker_vars["docker_uid"], 1000)
        self.assertEqual(cap_docker_vars["docker_gid"], 1000)

    def test_every_routed_workstation_origin_port_is_firewalled(self) -> None:
        workstation_vars = load_yaml(REPO_ROOT / "inventory/host_vars/workstation.yml")
        routed_ports = routed_workstation_ports(load_yaml(EXTERNALSERVICE_PATH)["http"]["services"])

        self.assertTrue(routed_ports)
        self.assertLessEqual(
            routed_ports, set(workstation_vars["lxc_origin_firewall_protected_ports"])
        )
        self.assertEqual(workstation_vars["lxc_origin_firewall_allowed_hosts"], ["portal"])

    def effective_persistent_home_links(self) -> list[dict]:
        """Resolve the list the workstation host actually deploys.

        The role default applies unless inventory/host_vars/workstation.yml overrides it,
        so the assertions below follow an override if one is ever added.
        """
        workstation_vars = load_yaml(REPO_ROOT / "inventory/host_vars/workstation.yml")
        if "workstation_persistent_home_links" in workstation_vars:
            return workstation_vars["workstation_persistent_home_links"]
        defaults = load_yaml(
            REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml"
        )
        return defaults["workstation_persistent_home_links"]

    def test_workstation_persistent_home_keeps_durable_state(self) -> None:
        declared = {
            (
                link["name"],
                link["type"],
                link["path"],
                link["target"],
                link["mode"],
                link.get("content"),
            )
            for link in self.effective_persistent_home_links()
        }

        for name, link_type, relative_path, mode, content in DURABLE_HOME_LINKS:
            self.assertIn(
                (
                    name,
                    link_type,
                    f"{WORKSTATION_HOME}/{relative_path}",
                    f"{{{{ workstation_persistent_home_root }}}}/{relative_path}",
                    mode,
                    content,
                ),
                declared,
            )

    def test_workstation_persistent_home_excludes_regenerable_state(self) -> None:
        # Two concrete paths must stay ephemeral: ~/.config/systemd/user/collie.service is
        # regenerated by Collie and embeds checkout-specific paths, and
        # ~/.local/state/herdr/agent-detection is rebuilt by herdr. Persisting either pins a
        # stale copy that survives a rebuild and then contradicts the running checkout.
        # Mounting ~/.local/state itself is the realistic way the herdr cache gets dragged in,
        # so the parent is rejected too — only ~/.local/state/collie is in the contract.
        forbidden_trees = (
            f"{WORKSTATION_HOME}/.config/systemd/user",
            f"{WORKSTATION_HOME}/.local/state/herdr",
            f"{WORKSTATION_HOME}/.lobu/cache",
        )
        forbidden_exact = f"{WORKSTATION_HOME}/.local/state"

        for link in self.effective_persistent_home_links():
            path = link["path"]
            for tree in forbidden_trees:
                self.assertFalse(
                    at_or_under(path, tree) or at_or_under(tree, path),
                    msg=(
                        f"persistent home entry {link['name']!r} path {path!r} must not persist "
                        f"regenerable state under {tree!r}"
                    ),
                )
            self.assertNotEqual(
                posixpath.normpath(path),
                posixpath.normpath(forbidden_exact),
                msg=(
                    f"persistent home entry {link['name']!r} must mount a specific directory "
                    f"under {forbidden_exact!r}, not the parent"
                ),
            )


if __name__ == "__main__":
    unittest.main()
