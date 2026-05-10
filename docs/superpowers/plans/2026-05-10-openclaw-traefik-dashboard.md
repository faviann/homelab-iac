# OpenClaw Traefik Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose OpenClaw at `https://ai.local.faviann.com` through portal Traefik and Authentik while keeping direct workstation CLI/TUI use working.

**Architecture:** Add one static Traefik route and one Authentik proxy provider/application/outpost binding for the local OpenClaw hostname. Extend the existing workstation nftables role so only loopback and portal can reach OpenClaw port `18789`. Mutate OpenClaw runtime state on the workstation during deployment; never commit OpenClaw passwords, tokens, or generated secrets.

**Tech Stack:** Ansible, Traefik file provider YAML, Authentik blueprints, nftables, pytest, OpenClaw Home Manager user service.

---

## File Map

| File | Responsibility |
| --- | --- |
| `stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml` | Static Traefik router/service/callback for `ai.local.faviann.com` |
| `tests/unit/test_portal_externalservice_config.py` | Contract tests for the OpenClaw Traefik route and Authentik callback |
| `stacks/auth/auth/appdata/authentik/blueprints/30-providers.yaml` | Authentik proxy provider for OpenClaw forwardAuth |
| `stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml` | Authentik application and `admins` policy binding |
| `stacks/auth/auth/appdata/authentik/blueprints/60-outposts.yaml` | Embedded outpost provider list |
| `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml` | Workstation OpenClaw gateway port default |
| `playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml` | Role argument spec for the new port variable |
| `playbooks/roles/config/lxc_workstation_baseline/templates/workstation-aoe-proxy.nft.j2` | nftables rules for AoE, Hermes, and OpenClaw |
| `tests/unit/test_workstation_baseline_role.py` | Contract tests for role defaults/argument specs |
| `tests/regression/fixtures/workstation_aoe_firewall_resolution_failure.yml` | Regression fixture should pass the new required port var |
| `/home/aperture/repos/dotfiles/home/workstation.nix` | Already owns OpenClaw Home Manager wiring and preserves mutable `~/.openclaw/openclaw.json`; inspect during live verification but do not change unless Home Manager overwrites runtime settings |

## Task 1: Traefik Route Contract

**Files:**
- Modify: `tests/unit/test_portal_externalservice_config.py`
- Modify: `stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml`

- [ ] **Step 1: Write the failing route test**

Add this test method to `PortalExternalServiceConfigTests`:

```python
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
                "middlewares": ["local-ip-restriction", "protected-edge-auth@file"],
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --locked pytest tests/unit/test_portal_externalservice_config.py -v
```

Expected: FAIL with missing `authentik-outpost-ai` or `ai` router.

- [ ] **Step 3: Add Traefik routers and service**

In `externalservice.yaml`, add the callback router near the existing Authentik outpost routers:

```yaml
    authentik-outpost-ai:
      rule: "Host(`ai.local.faviann.com`) && PathPrefix(`/outpost.goauthentik.io`)"
      entryPoints: websecure
      service: authentik
      priority: 1001
      middlewares:
        - sslheader
```

Add the user-facing router near `aoe` and `hermes`:

```yaml
    ai:
      rule: "Host(`ai.local.faviann.com`)"
      entryPoints: websecure
      service: openclaw-dashboard
      priority: 1000
      middlewares:
        - local-ip-restriction
        - protected-edge-auth@file
```

Add the service under `http.services`:

```yaml
    openclaw-dashboard:
      loadBalancer:
        servers:
          - url: "http://workstation.faviann.vms:18789"
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run --locked pytest tests/unit/test_portal_externalservice_config.py -v
```

Expected: PASS.

## Task 2: Authentik Blueprint Contract

**Files:**
- Modify: `stacks/auth/auth/appdata/authentik/blueprints/30-providers.yaml`
- Modify: `stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml`
- Modify: `stacks/auth/auth/appdata/authentik/blueprints/60-outposts.yaml`

- [ ] **Step 1: Add OpenClaw proxy provider**

Append this present provider in `30-providers.yaml` before the LDAP provider:

```yaml
- model: authentik_providers_proxy.proxyprovider
  state: present
  identifiers:
    name: openclaw-ai-forwardauth
  attrs:
    name: openclaw-ai-forwardauth
    mode: forward_single
    external_host: https://ai.local.faviann.com
    internal_host: ''
    internal_host_ssl_validation: true
    access_token_validity: hours=24
    refresh_token_validity: days=30
    client_id: F8bRzw3cP4pQmK7nT2xYhV6sD9aLcE1uG5jN0wXi
    cookie_domain: ''
    redirect_uris:
    - matching_mode: strict
      url: https://ai.local.faviann.com/outpost.goauthentik.io/callback?X-authentik-auth-callback=true
    - matching_mode: strict
      url: https://ai.local.faviann.com?X-authentik-auth-callback=true
    skip_path_regex: '^https://ai\.local\.faviann\.com/outpost\.goauthentik\.io/.*$

      ^/outpost\.goauthentik\.io/.*$'
    intercept_header_auth: true
    basic_auth_enabled: false
    basic_auth_user_attribute: ''
    basic_auth_password_attribute: ''
    jwt_federation_sources: []
    jwt_federation_providers: []
    authorization_flow: !Find [authentik_flows.flow, [slug, default-provider-authorization-implicit-consent]]
    invalidation_flow: !Find [authentik_flows.flow, [slug, default-provider-invalidation-flow]]
    property_mappings:
    - !Find [authentik_providers_oauth2.scopemapping, [managed, goauthentik.io/providers/proxy/scope-proxy]]
    - !Find [authentik_providers_oauth2.scopemapping, [managed, goauthentik.io/providers/oauth2/scope-email]]
    - !Find [authentik_providers_oauth2.scopemapping, [managed, goauthentik.io/providers/oauth2/scope-openid]]
    - !Find [authentik_providers_oauth2.scopemapping, [managed, goauthentik.io/providers/oauth2/scope-profile]]
    - !Find [authentik_providers_oauth2.scopemapping, [managed, goauthentik.io/providers/oauth2/scope-entitlements]]
```

- [ ] **Step 2: Add OpenClaw application and policy binding**

Append this in `40-applications.yaml` before LDAP:

```yaml
- id: app-openclaw-ai
  model: authentik_core.application
  state: present
  identifiers:
    slug: openclaw-ai
  attrs:
    name: OpenClaw AI
    slug: openclaw-ai
    provider: !Find [authentik_providers_proxy.proxyprovider, [name, openclaw-ai-forwardauth]]
    policy_engine_mode: any
    launch_url: https://ai.local.faviann.com
    open_in_new_tab: false
    meta_launch_url: ''
    meta_publisher: ''
    meta_description: ''
- model: authentik_policies.policybinding
  state: present
  identifiers:
    target: !KeyOf 'app-openclaw-ai'
    order: 0
  attrs:
    target: !KeyOf 'app-openclaw-ai'
    order: 0
    enabled: true
    negate: false
    failure_result: false
    timeout: 30
    group: !Find [authentik_core.group, [name, admins]]
```

- [ ] **Step 3: Add provider to embedded outpost**

In `60-outposts.yaml`, add this item to `authentik Embedded Outpost` providers:

```yaml
    - !Find [authentik_providers_proxy.proxyprovider, [name, openclaw-ai-forwardauth]]
```

- [ ] **Step 4: Run blueprint parser tests**

Run:

```bash
uv run --locked pytest tests/unit/test_authentik_auth_flow_blueprints.py tests/unit/test_authentik_blueprint_idempotency.py -v
```

Expected: PASS. These tests parse repo blueprints through the existing custom YAML constructors and catch syntax regressions.

## Task 3: Workstation Firewall Contract

**Files:**
- Modify: `tests/unit/test_workstation_baseline_role.py`
- Modify: `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml`
- Modify: `playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml`
- Modify: `playbooks/roles/config/lxc_workstation_baseline/templates/workstation-aoe-proxy.nft.j2`
- Modify: `tests/regression/fixtures/workstation_aoe_firewall_resolution_failure.yml`

- [ ] **Step 1: Write failing defaults and argument spec tests**

In `test_role_defaults_contract`, add:

```python
        self.assertEqual(defaults["workstation_openclaw_gateway_port"], 18789)
```

In `test_role_argument_specs_contract`, add:

```python
        self.assertEqual(options["workstation_openclaw_gateway_port"]["type"], "int")
        self.assertFalse(options["workstation_openclaw_gateway_port"]["required"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --locked pytest tests/unit/test_workstation_baseline_role.py -v
```

Expected: FAIL with missing `workstation_openclaw_gateway_port`.

- [ ] **Step 3: Add the role default and argument spec**

In `defaults/main.yml`, add:

```yaml
workstation_openclaw_gateway_port: 18789
```

In `meta/argument_specs.yml`, add:

```yaml
      workstation_openclaw_gateway_port:
        type: int
        required: false
        description: >-
          Port the OpenClaw gateway dashboard binds to (default 18789). Firewall
          rules for this port are added to the AoE nft table when
          workstation_aoe_proxy_firewall_enabled is true.
```

- [ ] **Step 4: Extend nftables rules**

In `workstation-aoe-proxy.nft.j2`, add this block after the Hermes block:

```jinja
    iifname "lo" tcp dport {{ workstation_openclaw_gateway_port }} accept
    tcp dport {{ workstation_openclaw_gateway_port }} ip saddr @allowed_ipv4 accept
    tcp dport {{ workstation_openclaw_gateway_port }} drop
```

- [ ] **Step 5: Keep regression fixture explicit**

In `tests/regression/fixtures/workstation_aoe_firewall_resolution_failure.yml`, add:

```yaml
    workstation_openclaw_gateway_port: 18789
```

- [ ] **Step 6: Run workstation tests**

Run:

```bash
uv run --locked pytest tests/unit/test_workstation_baseline_role.py tests/regression/test_workstation_aoe_firewall_resolution.py -v
```

Expected: PASS.

## Task 4: Review, Local Test, And Deploy

**Files:**
- No additional repo edits unless tests expose an issue.

- [ ] **Step 1: Check the scoped diff**

Run:

```bash
git diff -- \
  docs/superpowers/specs/2026-05-10-openclaw-traefik-dashboard-design.md \
  docs/superpowers/plans/2026-05-10-openclaw-traefik-dashboard.md \
  stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml \
  tests/unit/test_portal_externalservice_config.py \
  stacks/auth/auth/appdata/authentik/blueprints/30-providers.yaml \
  stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml \
  stacks/auth/auth/appdata/authentik/blueprints/60-outposts.yaml \
  playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml \
  playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml \
  playbooks/roles/config/lxc_workstation_baseline/templates/workstation-aoe-proxy.nft.j2 \
  tests/unit/test_workstation_baseline_role.py \
  tests/regression/fixtures/workstation_aoe_firewall_resolution_failure.yml
```

Expected: only OpenClaw dashboard, Authentik, Traefik, workstation firewall, spec, and plan changes are present. Do not stage `BACKLOG.md`.

- [ ] **Step 2: Run targeted local tests**

Run:

```bash
uv run --locked pytest \
  tests/unit/test_portal_externalservice_config.py \
  tests/unit/test_authentik_auth_flow_blueprints.py \
  tests/unit/test_authentik_blueprint_idempotency.py \
  tests/unit/test_workstation_baseline_role.py \
  tests/regression/test_workstation_aoe_firewall_resolution.py \
  -v
```

Expected: PASS.

- [ ] **Step 3: Deploy portal/Auth changes**

Run:

```bash
uv run --locked ansible-playbook site.yml --limit auth,portal > /tmp/openclaw-portal-auth-deploy.log 2>&1
tail -40 /tmp/openclaw-portal-auth-deploy.log
rg "failed=|unreachable=|FAILED|authentik|traefik|openclaw|ai.local" /tmp/openclaw-portal-auth-deploy.log
```

Expected: `failed=0`, `unreachable=0`. If the deploy is skipped because the controller hostname matches a target, rerun with `-e proxmox_skip_self=false --limit auth,portal` only if the target is intentionally the controller.

- [ ] **Step 4: Deploy workstation firewall changes**

Run:

```bash
uv run --locked ansible-playbook site.yml --limit workstation > /tmp/openclaw-workstation-deploy.log 2>&1
tail -40 /tmp/openclaw-workstation-deploy.log
rg "failed=|unreachable=|FAILED|workstation-aoe-proxy|18789|openclaw" /tmp/openclaw-workstation-deploy.log
```

Expected: `failed=0`, `unreachable=0`.

## Task 5: OpenClaw Runtime State And Live Verification

**Files:**
- No ServerManagementScripts repo files. Work happens in mutable OpenClaw state on `workstation`.
- `/home/aperture/repos/dotfiles/home/workstation.nix` is a possible follow-up only if verification proves Home Manager still overwrites OpenClaw runtime config despite the existing mutable-config activation hooks.

- [ ] **Step 1: Inspect OpenClaw version and config help without printing secrets**

Run:

```bash
ssh -l faviann -i .ansible/ssh/proxmox_lxc workstation.faviann.vms 'openclaw --version && openclaw --help | sed -n "1,120p"'
```

Expected: version `2026.5.7` or newer and a usable config/onboard/status command path.

- [ ] **Step 2: Confirm Home Manager is not the source of immutable OpenClaw auth settings**

Run:

```bash
git -C /home/aperture/repos/dotfiles status --short
rg -n "openclaw|openclawMutableConfig|openclawSaveConfig" /home/aperture/repos/dotfiles/home/workstation.nix
```

Expected: dotfiles is clean and `home/workstation.nix` contains the existing `openclawSaveConfig` and `openclawMutableConfig` activation hooks. Do not edit dotfiles unless a later verification step shows those hooks are insufficient.

- [ ] **Step 3: Configure trusted-proxy browser auth and local fallback**

Use an OpenClaw command if available. If no command supports these fields, use a structured JSON/YAML edit of `~/.openclaw` on the workstation. Required effective settings:

```yaml
gateway:
  auth:
    mode: trusted-proxy
    trustedProxy:
      userHeader: x-authentik-email
      requiredHeaders:
        - x-forwarded-proto
        - x-forwarded-host
      allowUsers:
        - faviann@gmail.com
    password: <local generated password, do not print>
  trustedProxies:
    - 10.1.0.2
  controlUi:
    allowedOrigins:
      - https://ai.local.faviann.com
```

Also remove any effective `gateway.auth.token` setting. Do not print the local password or any existing token.

- [ ] **Step 4: Restart and check OpenClaw**

Run:

```bash
ssh -l faviann -i .ansible/ssh/proxmox_lxc workstation.faviann.vms 'systemctl --user restart openclaw-gateway.service && systemctl --user is-active openclaw-gateway.service && openclaw doctor'
```

Expected: service is `active`; `openclaw doctor` has no missing trusted proxy, empty allowUsers, mixed token, or missing allowed origin finding.

- [ ] **Step 5: Verify direct firewall behavior**

From a non-portal host, run:

```bash
curl -k -sS -D - -o /dev/null http://workstation.faviann.vms:18789/
```

Expected: connection timeout/refusal from non-portal paths after nftables is applied. From workstation loopback, the gateway should answer.

- [ ] **Step 6: Verify browser route and Authentik path**

Run:

```bash
getent ahostsv4 ai.local.faviann.com
curl -k -sS -D - -o /dev/null https://ai.local.faviann.com/
curl -k -sS -D - -o /dev/null https://ai.local.faviann.com/outpost.goauthentik.io/ping
```

Expected: DNS resolves to portal, unauthenticated dashboard request redirects/401s through Authentik, callback path reaches Authentik rather than OpenClaw.

- [ ] **Step 7: Verify authenticated dashboard and WebSocket**

Use a browser session or authenticated curl cookie jar. Confirm:

- Authenticated `https://ai.local.faviann.com` reaches OpenClaw dashboard.
- Dashboard WebSocket connects through Traefik.
- OpenClaw sees `x-authentik-email`, `x-forwarded-proto`, and `x-forwarded-host`.
- Requests with missing required forwarded headers or an unlisted email are rejected.
- Local workstation OpenClaw CLI/TUI still works through the local password fallback.

## Task 6: Commit And Push

**Files:**
- Commit only the approved spec, implementation plan, and scoped implementation files.

- [ ] **Step 1: Inspect status**

Run:

```bash
git status --short
```

Expected: no unrelated staged files and no `BACKLOG.md` staging.

- [ ] **Step 2: Stage only scoped files**

Run:

```bash
git add \
  docs/superpowers/specs/2026-05-10-openclaw-traefik-dashboard-design.md \
  docs/superpowers/plans/2026-05-10-openclaw-traefik-dashboard.md \
  stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml \
  tests/unit/test_portal_externalservice_config.py \
  stacks/auth/auth/appdata/authentik/blueprints/30-providers.yaml \
  stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml \
  stacks/auth/auth/appdata/authentik/blueprints/60-outposts.yaml \
  playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml \
  playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml \
  playbooks/roles/config/lxc_workstation_baseline/templates/workstation-aoe-proxy.nft.j2 \
  tests/unit/test_workstation_baseline_role.py \
  tests/regression/fixtures/workstation_aoe_firewall_resolution_failure.yml
```

- [ ] **Step 3: Commit and push**

Run:

```bash
git commit -m "feat: expose openclaw dashboard through portal"
git push
```

Expected: commit succeeds and branch pushes to the configured upstream.

## Self-Review

- Spec coverage: Traefik route, Authentik provider/application/outpost callback, local IP restriction, Authentik middleware, workstation nftables, OpenClaw trusted-proxy, local fallback, WebSocket/header/DNS/direct-port verification, tests, deploy, commit, and push are covered.
- Placeholder scan: no implementation step contains `TBD`, `TODO`, or an unfilled code placeholder. The only angle-bracket value is a required secret-handling reminder that must never be committed or printed.
- Type consistency: route names, service names, provider names, application slug, port, trusted proxy IP, and Authentik identity match the approved spec.
