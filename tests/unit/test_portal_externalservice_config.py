#!/usr/bin/env python3
"""Contract tests for portal external Traefik services."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


class PortalExternalServiceConfigTests(unittest.TestCase):
    def test_aoe_external_route_contract(self) -> None:
        externalservice_path = (
            REPO_ROOT / "stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml"
        )
        config = yaml.safe_load(externalservice_path.read_text(encoding="utf-8"))

        self.assertEqual(
            config["http"]["routers"]["aoe"],
            {
                "rule": "Host(`aoe.local.faviann.com`)",
                "entryPoints": "websecure",
                "service": "aoe-workstation",
                "priority": 1000,
                "middlewares": ["local-ip-restriction"],
            },
        )
        self.assertEqual(
            config["http"]["services"]["aoe-workstation"],
            {
                "loadBalancer": {
                    "servers": [{"url": "http://workstation.faviann.vms:4001"}],
                }
            },
        )

    def test_openclaw_external_route_contract(self) -> None:
        externalservice_path = (
            REPO_ROOT / "stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml"
        )
        config = yaml.safe_load(externalservice_path.read_text(encoding="utf-8"))

        self.assertEqual(
            config["http"]["routers"]["authentik-outpost-ai"],
            {
                "rule": "Host(`ai.local.faviann.com`) && PathPrefix(`/outpost.goauthentik.io`)",
                "entryPoints": "websecure",
                "service": "authentik",
                "priority": 1001,
                "middlewares": ["sslheader"],
            },
        )
        self.assertEqual(
            config["http"]["routers"]["ai"],
            {
                "rule": "Host(`ai.local.faviann.com`)",
                "entryPoints": "websecure",
                "service": "openclaw-dashboard",
                "priority": 1000,
                "middlewares": ["local-ip-restriction", "protected-edge-auth@file", "openclaw-operator-scopes"],
            },
        )
        self.assertEqual(
            config["http"]["middlewares"]["openclaw-operator-scopes"],
            {
                "headers": {
                    "customRequestHeaders": {
                        "X-OpenClaw-Scopes": "operator.read,operator.write,operator.admin",
                    }
                }
            },
        )
        self.assertEqual(
            config["http"]["services"]["openclaw-dashboard"],
            {
                "loadBalancer": {
                    "servers": [{"url": "http://workstation.faviann.vms:18789"}],
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
