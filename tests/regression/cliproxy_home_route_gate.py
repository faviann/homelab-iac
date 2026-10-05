"""Explicit local-Docker gate for the Home LAN route and shipped panel flow.

Run: ./validate.sh tests tests/regression/cliproxy_home_route_gate.py
The default handoff never collects this Docker-dependent filename. Temporary
resources use only the local Unix socket and synthetic imported credentials.
A canceled provider callback proves session creation and callback paste handling;
successful provider sign-in and token exchange remain a human acceptance gate.
"""
from __future__ import annotations

import copy
import http.client
import ipaddress
import json
import re
import socket
import ssl
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
import yaml

from cliproxy_home_recovery_gate import (
    HOME_IMAGE, HomeCPAPair, LEGACY_KEY, MANAGEMENT_KEY, MODEL, REPO,
)

pytestmark = pytest.mark.serial
HOME_HOST = "cliproxy-home.local.faviann.com"
CLIENT_HOST = "cliproxy.local.faviann.com"
TRAEFIK = REPO / "stacks/portal/traefik3"


def require(condition: bool, stage: str) -> None:
    __tracebackhide__ = True
    if not condition:
        pytest.fail(stage, pytrace=False)


class HomeRoutePair(HomeCPAPair):
    def start_edge(self) -> None:
        __tracebackhide__ = True
        production = yaml.safe_load((TRAEFIK / "appdata/traefik3/config/conf.d/externalservice.yaml").read_text())["http"]
        routers = {name: copy.deepcopy(production["routers"][name]) for name in ("cliproxy-home", "cliproxy")}
        services = {name: copy.deepcopy(production["services"][name]) for name in routers}
        services["cliproxy-home"]["loadBalancer"]["servers"][0]["url"] = self.home_url.removesuffix("/v8/management")
        services["cliproxy"]["loadBalancer"]["servers"][0]["url"] = self.cpa_url.removesuffix("/v1")
        allowlist = copy.deepcopy(production["middlewares"]["local-ip-restriction"])
        info = json.loads(self.docker("network", "inspect", self.network, stage="isolated bridge observation").stdout)[0]
        self.gateway = info["IPAM"]["Config"][0]["Gateway"]
        require(not any(ipaddress.ip_address(self.gateway) in ipaddress.ip_network(cidr, strict=False)
                        for cidr in allowlist["IPAllowList"]["sourceRange"]), "fixture peer must be outside unchanged LAN allowlist")
        configuration = self.directory("edge")
        (configuration / "routes.yaml").write_text(yaml.safe_dump({"http": {
            "routers": routers, "services": services,
            "middlewares": {"local-ip-restriction": allowlist},
        }}))
        # One HTTPS listener, using Traefik's generated default certificate only
        # for synthetic transport. No ACME, access logs or trusted proxy headers.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.edge_port = listener.getsockname()[1]
        image = yaml.safe_load((TRAEFIK / "compose.yaml").read_text())["services"]["traefik"]["image"]
        available = self.docker("image", "inspect", image, stage="portal Traefik image lookup", check=False)
        if available.returncode:
            self.docker("pull", image, stage="portal Traefik image pull", timeout=300)
        self.edge_name = self.network + "-edge"
        self.docker("run", "-d", "--pull", "never", "--name", self.edge_name,
                    "--network", "host", "--mount", f"type=bind,src={configuration},dst=/fixture,readonly", image,
                    "--global.checknewversion=false", "--global.sendanonymoususage=false",
                    "--log.level=ERROR", f"--entrypoints.websecure.address=127.0.0.1:{self.edge_port}",
                    "--entrypoints.websecure.http.tls=true", "--providers.file.filename=/fixture/routes.yaml",
                    stage="loopback HTTPS edge startup")
        self.wait(lambda: self.edge(HOME_HOST, "/management.html")[0] == 200, "Home route panel readiness")

    def edge(self, host: str, path: str, key: str | None = None, *, method: str = "GET",
             body: object = None, source: str = "127.0.0.1", forged: bool = False) -> tuple[int, bytes]:
        __tracebackhide__ = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection("127.0.0.1", self.edge_port, timeout=5,
                                                context=context, source_address=(source, 0))
        headers = {"Host": host}
        if key is not None:
            # These are the headers emitted by the shipped management panel.
            headers.update({"Authorization": "Bearer " + key, "X-Management-Key": key})
        if forged:
            headers["X-Forwarded-For"] = "127.0.0.1"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        except (OSError, http.client.HTTPException):
            return 0, b""
        finally:
            connection.close()

    def close(self) -> None:
        __tracebackhide__ = True
        try:
            if hasattr(self, "edge_name"):
                self.docker("container", "rm", "--force", self.edge_name, stage="temporary HTTPS edge cleanup")
        finally:
            super().close()


@pytest.fixture
def home_route_pair():
    __tracebackhide__ = True
    with tempfile.TemporaryDirectory(prefix="cliproxy-home-route-") as temporary:
        pair = HomeRoutePair(Path(temporary))
        pair.root.chmod(0o700)
        try:
            pair.prepare()
            state = pair.directory("state")
            pair.native(state, "-import", "-config", "/recovery/source/config.yaml", "-auth-dir",
                        "/recovery/source/auth", stage="reused synthetic native import")
            pair.start_home(state)
            node = pair.enroll()
            pair.start_cpa(pair.directory("cpa-cache"))
            pair.wait(lambda: pair.connected(node), "reused native CPA enrollment")
            pair.start_edge()
            yield pair
        except Exception:
            pytest.fail("synthetic route fixture failed", pytrace=False)
        finally:
            pair.close()


def test_home_route_native_panel_and_client_boundary(home_route_pair):
    __tracebackhide__ = True
    pair = home_route_pair
    stage = "route gate setup"
    try:
        require(yaml.safe_load((REPO / "stacks/overmind/cliproxy/compose.yaml").read_text())["services"]["cliproxy-home"]["image"] == HOME_IMAGE,
                "Home fixture must match deployed image pin")
        stage = "Docker-served management panel and local JavaScript assets"
        status, panel = pair.edge(HOME_HOST, "/management.html")
        require(status == 200, stage)
        scripts = re.findall(r'<script\b[^>]*\bsrc=["\']([^"\']+)["\']', panel.decode())
        require(bool(scripts), "shipped panel must reference JavaScript assets")
        bundle = panel.decode()
        for script in scripts:
            asset = urlsplit(script)
            require(not asset.scheme and not asset.netloc, "panel script must stay on Home origin")
            path = script if script.startswith("/") else "/" + script.removeprefix("./")
            status, raw = pair.edge(HOME_HOST, path)
            require(status == 200, stage)
            bundle += raw.decode()
        # Discover the native flow from the actual served bundle, rather than
        # substituting Home's newer API names for the bundled panel's calls.
        for literal in ("/v0/management", "X-Management-Key", "Bearer", "/config", "/capabilities",
                        "codex", "-auth-url", "is_webui", "/oauth-callback", "redirect_url", "/get-auth-status"):
            require(literal in bundle, "shipped password/account-add/callback flow changed")

        stage = "native imported-password connection through Home route"
        base = "/v0/management"
        require(pair.edge(HOME_HOST, base + "/config")[0] in (401, 403), "missing imported password must reject")
        require(pair.edge(HOME_HOST, base + "/config", "synthetic-wrong-password")[0] in (401, 403),
                "wrong imported password must reject")
        for endpoint in ("/config", "/capabilities"):
            require(pair.edge(HOME_HOST, base + endpoint, MANAGEMENT_KEY)[0] == 200, stage)

        stage = "native account-add session through Home route"
        status, raw = pair.edge(HOME_HOST, base + "/codex-auth-url?is_webui=true", MANAGEMENT_KEY)
        session = json.loads(raw)
        require(status == 200 and session.get("status") == "ok" and bool(session.get("state")), stage)
        query = parse_qs(urlsplit(session["url"]).query)
        require(query.get("state") == [session["state"]] and
                query.get("redirect_uri") == ["http://localhost:1455/auth/callback"], "native provider callback context")
        status_path = base + "/get-auth-status?" + urlencode({"state": session["state"]})
        status, raw = pair.edge(HOME_HOST, status_path, MANAGEMENT_KEY)
        require(status == 200 and json.loads(raw).get("status") == "wait", "native account-add session must be pending")
        stage = "native pasted canceled callback through Home route"
        callback = "http://localhost:1455/auth/callback?" + urlencode({"state": session["state"], "error": "access_denied"})
        status, raw = pair.edge(HOME_HOST, base + "/oauth-callback", MANAGEMENT_KEY, method="POST",
                                body={"provider": "codex", "redirect_url": callback})
        require(status == 200 and json.loads(raw).get("status") == "ok", stage)
        status, raw = pair.edge(HOME_HOST, status_path, MANAGEMENT_KEY)
        require(status == 200 and json.loads(raw) == {"status": "error", "error": "Authentication failed"},
                "native canceled callback must report authentication failure")

        stage = "real non-LAN socket peer restriction"
        for forged in (False, True):
            require(pair.edge(HOME_HOST, "/management.html", source=pair.gateway, forged=forged)[0] == 403, stage)
        stage = "unchanged client route"
        status, raw = pair.edge(CLIENT_HOST, "/v1/models", LEGACY_KEY)
        require(status == 200 and any(item["id"] == MODEL for item in json.loads(raw)["data"]), stage)
        require(pair.edge(CLIENT_HOST, "/management.html")[0] == 404, "client listener must not expose Home management panel")
    except Exception:
        pytest.fail(stage + ": failed", pytrace=False)
