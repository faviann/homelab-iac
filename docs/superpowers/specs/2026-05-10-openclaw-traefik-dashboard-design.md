# OpenClaw Dashboard Through Traefik — Design Spec

**Date:** 2026-05-10
**Status:** Ready for approval

## Context

OpenClaw runs on the `workstation` LXC as a Home Manager user service and listens on port `18789`. The current browser access story is awkward because OpenClaw is in token-auth mode, while the desired entrypoint is `https://ai.local.faviann.com` through the existing portal Traefik and Authentik setup.

Existing local routes such as `aoe.local.faviann.com` and `hermes.local.faviann.com` are defined as static external services in `stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml` and protected by `local-ip-restriction`. The portal Traefik certificate already covers `*.local.faviann.com`.

Live/repo discovery for this design:

- `portal.faviann.vms` resolves to `10.1.0.2`.
- `workstation.faviann.vms` resolves to `10.1.4.25`.
- Authentik user `faviann` has email `faviann@gmail.com` and is a member of the existing `admins` group.

## Goals

- Expose the OpenClaw dashboard at `https://ai.local.faviann.com`.
- Require both local/VPN source access and Authentik login before the browser reaches OpenClaw.
- Avoid a manual browser token prompt for the dashboard.
- Keep local OpenClaw CLI/TUI usage working on the workstation.
- Keep OpenClaw state and secrets out of git.
- Keep the gateway reachable from `portal` only, not broadly across the LAN.

## Non-Goals

- Do not containerize OpenClaw in this change.
- Do not expose OpenClaw publicly beyond the existing local/VPN access pattern.
- Do not add OpenClaw tokens, passwords, or generated secrets to this repository.
- Do not redesign the existing Traefik/Auth/Authentik topology.
- Do not introduce a dedicated `ai` Authentik group in v1.

## Approaches Considered

1. **Dedicated single-host Authentik provider plus Traefik static route.** This is the selected approach. It keeps the local hostname explicit, gives the Authentik outpost a concrete callback route for `ai.local.faviann.com`, and avoids overloading the existing root/admin/home/media wildcard providers.
2. **Reuse an existing wildcard provider.** This was rejected because the existing protected-tier callbacks do not cover `*.local.faviann.com`, and relying on unrelated wildcard domains would make auth behavior harder to reason about.
3. **Expose OpenClaw directly with native token/password auth.** This was rejected because the goal is browser SSO through the existing portal edge, and direct LAN reachability would make trusted-proxy mode unsafe.

## Decisions

- Authentik access policy: bind the OpenClaw application to the existing `admins` group for v1.
- OpenClaw trusted identity: use Authentik header `X-authentik-email` and restrict `gateway.auth.trustedProxy.allowUsers` to `faviann@gmail.com`.
- Trusted proxy source: set `gateway.trustedProxies` to the portal IPv4 address `10.1.0.2` only.
- Workstation firewall source: resolve the allowed host from inventory/DNS as the existing firewall role does; the expected current result is `10.1.0.2`.
- Browser hostname: `https://ai.local.faviann.com`.
- Upstream service URL: `http://workstation.faviann.vms:18789`.

## Recommended Approach

Use Traefik and Authentik as the browser identity boundary, and configure OpenClaw for `trusted-proxy` browser access.

The browser path becomes:

```text
browser -> https://ai.local.faviann.com -> portal Traefik -> Authentik forwardAuth -> workstation OpenClaw :18789
```

The local TUI path remains direct on the workstation:

```text
openclaw TUI/CLI on workstation -> local OpenClaw gateway
```

OpenClaw trusted-proxy mode requires two safeguards:

- `gateway.trustedProxies` must contain only the actual portal/proxy source address.
- `gateway.controlUi.allowedOrigins` must include `https://ai.local.faviann.com`.

OpenClaw token auth is mutually exclusive with trusted-proxy mode. To preserve local CLI/TUI access, the implementation must configure a local direct password fallback in OpenClaw state, not a repo-managed plaintext token. The user should not have to remember this password; it is local service state used by OpenClaw clients.

## Components

### Portal Traefik

Add an `ai` router to `stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml`:

- Rule: ``Host(`ai.local.faviann.com`)``
- Entrypoint: `websecure`
- Service: `openclaw-dashboard`
- Middlewares:
  - `local-ip-restriction`
  - `protected-edge-auth@file`

Add an `openclaw-dashboard` service pointing to:

```text
http://workstation.faviann.vms:18789
```

Add a higher-priority Authentik callback router in the same file:

- Name: `authentik-outpost-ai`
- Rule: ``Host(`ai.local.faviann.com`) && PathPrefix(`/outpost.goauthentik.io`)``
- Entrypoint: `websecure`
- Service: `authentik`
- Priority: `1001`
- Middleware: `sslheader`

Traefik should forward WebSocket upgrades normally; verification must prove that the dashboard can establish its WebSocket session.

### Authentik

Add a dedicated Authentik proxy provider/application for `ai.local.faviann.com`.
This is mandatory: the existing embedded outpost only covers root/admin/home/media/auth providers, and local subdomains do not currently have an Authentik callback route.

Add provider/application/outpost wiring:

- Provider name: `openclaw-ai-forwardauth`
- Application slug: `openclaw-ai`
- Application name: `OpenClaw AI`
- External host: `https://ai.local.faviann.com`
- Policy binding: `admins`
- Add the provider to the embedded outpost in `stacks/auth/auth/appdata/authentik/blueprints/60-outposts.yaml`.

Implementation files:

- `stacks/auth/auth/appdata/authentik/blueprints/30-providers.yaml`: add a `forward_single` proxy provider for `openclaw-ai-forwardauth`, with strict redirect URIs for `https://ai.local.faviann.com/outpost.goauthentik.io/callback?X-authentik-auth-callback=true` and `https://ai.local.faviann.com?X-authentik-auth-callback=true`.
- `stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml`: add the `openclaw-ai` application and one policy binding for group `admins`.
- `stacks/auth/auth/appdata/authentik/blueprints/60-outposts.yaml`: add `openclaw-ai-forwardauth` to `authentik Embedded Outpost`.

Use the existing blueprint style. Do not commit generated secrets. An Authentik OAuth client ID is not a secret, but any generated client secret, token, cookie, or password must stay out of git and out of logs.

### Workstation OpenClaw

Update the mutable OpenClaw config on the workstation, without committing secret values:

- Set `gateway.auth.mode` to `trusted-proxy`.
- Remove `gateway.auth.token` to avoid mixed token/trusted-proxy startup failure.
- Set `gateway.trustedProxies` to `10.1.0.2`.
- Set `gateway.auth.trustedProxy.userHeader` to `x-authentik-email`.
- Set `gateway.auth.trustedProxy.requiredHeaders` to include `x-forwarded-proto` and `x-forwarded-host`.
- Set `gateway.auth.trustedProxy.allowUsers` to `faviann@gmail.com`.
- Add `https://ai.local.faviann.com` to `gateway.controlUi.allowedOrigins`.
- Configure local direct password fallback for same-host OpenClaw CLI/TUI use:
  - set `gateway.auth.password` in mutable OpenClaw state or the equivalent supported OpenClaw setting;
  - update the local OpenClaw client/TUI config to use that local fallback;
  - restart `openclaw-gateway.service`;
  - verify local `openclaw tui`/CLI behavior before deploying the browser route.

The exact config mutation should happen through an OpenClaw command if available. If no suitable command exists, use a small structured JSON update and avoid printing secret values.

### Workstation Firewall

Restrict inbound access to port `18789` on `workstation` by extending the existing workstation nftables template/service, not by adding a second competing base-chain table.

Implementation details:

- Add `workstation_openclaw_gateway_port: 18789`.
- Reuse the existing `workstation_aoe_proxy_firewall_allowed_hosts` source list for the same trusted ingress host, with `portal` as the only allowed host.
- Extend `workstation-aoe-proxy.nft.j2` or rename/generalize it so the same nft table allows:
  - loopback to `18789`;
  - portal's resolved IPv4 address, currently `10.1.0.2`, to `18789`;
  - drop all other TCP traffic to `18789`.
- Keep the existing `4001` and `9119` protections intact.
- Add/update regression tests for the rendered nft rules.

Prefer the smallest safe change: extend the existing firewall role and template rather than introducing a second service/table. A later cleanup can rename AoE-specific variable names if the route set grows further.

## Security Model

There are three gates:

1. DNS/network locality: `ai.local.faviann.com` follows the local/VPN-only pattern.
2. Traefik local IP allowlist: non-local sources are rejected before Authentik.
3. Authentik + OpenClaw trusted-proxy: only authenticated, allowed users become trusted OpenClaw browser users.

The OpenClaw gateway must not be reachable directly from arbitrary clients, because trusted-proxy auth delegates browser identity to Traefik/Authentik.

## Verification

Implementation must verify:

- `openclaw --version` still reports `2026.5.7` or newer.
- `openclaw-gateway.service` is active after config changes.
- `openclaw doctor` and/or `openclaw security audit` findings are reviewed; trusted-proxy warnings are expected but missing `trustedProxies`, empty `allowUsers`, mixed token config, and missing origin are not acceptable.
- `curl`/browser through `https://ai.local.faviann.com` reaches the dashboard only after Authentik.
- WebSocket dashboard connection succeeds through Traefik.
- Authentik identity and forwarded headers reach OpenClaw on HTTP and WebSocket paths:
  - `X-authentik-email`
  - `X-Forwarded-Proto`
  - `X-Forwarded-Host`
- OpenClaw rejects requests that omit the required forwarded headers or use an unlisted Authentik email.
- Direct access to `workstation.faviann.vms:18789` from non-portal hosts is blocked.
- Direct non-portal requests with spoofed identity headers are blocked before OpenClaw.
- Local workstation OpenClaw CLI/TUI still works after switching away from token auth.
- `ai.local.faviann.com` resolves to portal from LAN/VPN before browser testing.
- Unit tests cover the Traefik static route contract:
  - `ai` router
  - `openclaw-dashboard` service URL
  - Authentik callback router
  - middleware order
- No token, password, private key, or generated secret is printed or committed.

Targeted local tests:

```bash
uv run --locked pytest tests/unit/test_portal_externalservice_config.py -v
uv run --locked pytest tests/regression/test_workstation_aoe_firewall_resolution.py -v
```

If implementation changes Authentik blueprint structure, also run the Authentik blueprint unit tests:

```bash
uv run --locked pytest tests/unit/test_authentik_auth_flow_blueprints.py tests/unit/test_authentik_blueprint_idempotency.py -v
```

## Rollout Plan

1. Implement repo changes in a branch/worktree or clean working state.
2. Use one implementation subagent for the bounded config changes.
3. Use a second review subagent to inspect the patch for auth bypasses, direct-port exposure, and secret leakage.
4. Run targeted tests and live verification.
5. Deploy only the affected stacks/hosts where possible:
   - `portal` for Traefik/Authentik changes
   - `workstation` for OpenClaw config/firewall changes
6. Commit and push after verification passes.

Do not stage or commit unrelated `BACKLOG.md` changes.

## Spec Self-Review

- Placeholder scan: no placeholders or TODOs remain.
- Internal consistency: Authentik, Traefik, OpenClaw, and nftables all use the same hostname, upstream URL, trusted proxy IP, and owner identity.
- Scope check: this is one deployable slice; it adds one browser route and tightens one existing workstation firewall surface.
- Ambiguity check: v1 access is `admins` only, OpenClaw `allowUsers` is `faviann@gmail.com`, and portal source IP is `10.1.0.2`.
