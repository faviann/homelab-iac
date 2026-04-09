# Debug: Authentik + Traefik Redirect Loop

## Goal

Fix a persistent infinite redirect loop that occurs when `forwardAuth-authentik@file`
is set as a default middleware on the Traefik `websecure` entrypoint. The design intent
is "auth by default with no per-service label noise" — do not suggest moving forwardAuth
to per-router labels as a solution. That approach was deliberately rejected.

---

## Infrastructure

- **Traefik v3** on host `portal` (container: `traefik`, stacks at `/conf/docker/stacks/`)
- **Authentik** on host `auth.faviann.vms:9000` (container: `auth-server-1`)
- **Authentik version**: 2025.12.4
- **Embedded outpost** (no separate outpost container — Authentik's built-in proxy outpost)
- Non-portal services push Docker labels to portal's Redis via `traefik-kop`

---

## Current Traefik Config

### `traefik.yaml` (static config) — key section

```yaml
entryPoints:
  websecure:
    address: ":443"
    asDefault: true
    http:
      middlewares:
        - forwardAuth-authentik@file   # <-- DEFAULT AUTH FOR ALL ROUTES
      tls:
        certResolver: cloudflare
        domains:
          - main: faviann.com
            sans:
              - "*.faviann.com"
              - "*.admin.faviann.com"
              - "*.home.faviann.com"
              - "*.media.faviann.com"
```

### `middleware-authentik.yaml`

```yaml
http:
  middlewares:
    forwardAuth-authentik:
      forwardAuth:
        address: http://auth.faviann.vms:9000/outpost.goauthentik.io/auth/traefik
        trustForwardHeader: true
        authRequestHeaders:
          - X-Forwarded-Proto
        authResponseHeaders:
          - X-authentik-username
          - X-authentik-groups
          - X-authentik-entitlements
          - X-authentik-email
          - X-authentik-name
          - X-authentik-uid
          - X-authentik-jwt
          - X-authentik-meta-jwks
          - X-authentik-meta-outpost
          - X-authentik-meta-provider
          - X-authentik-meta-app
          - X-authentik-meta-version
```

### `externalservice.yaml` — relevant routers

```yaml
http:
  routers:
    authentik:
      rule: "Host(`auth.faviann.com`)"
      entryPoints: websecure
      service: authentik
      priority: 1000
      middlewares:
        - sslheader   # sets X-Forwarded-Proto: https

    # Outpost callback routers — no extra middlewares (rely on outpost recognizing its own paths)
    authentik-outpost-root:
      rule: "Host(`faviann.com`) && PathPrefix(`/outpost.goauthentik.io`)"
      entryPoints: websecure
      service: authentik
      priority: 1001
      middlewares:
        - sslheader

    authentik-outpost-admin:
      rule: "Host(`admin.faviann.com`) && PathPrefix(`/outpost.goauthentik.io`)"
      entryPoints: websecure
      service: authentik
      priority: 1001
      middlewares:
        - sslheader

    authentik-outpost-home:
      rule: "Host(`home.faviann.com`) && PathPrefix(`/outpost.goauthentik.io`)"
      entryPoints: websecure
      service: authentik
      priority: 1001
      middlewares:
        - sslheader

    authentik-outpost-media:
      rule: "Host(`media.faviann.com`) && PathPrefix(`/outpost.goauthentik.io`)"
      entryPoints: websecure
      service: authentik
      priority: 1001
      middlewares:
        - sslheader

  services:
    authentik:
      loadBalancer:
        servers:
          - url: "http://auth.faviann.vms:9000"
```

---

## Authentik Outpost State (confirmed from logs)

The embedded outpost loads these providers on startup:

```
"Provider for Domain Wide Forward Auth Catch All"  host: faviann.com
"admin-proxy-provider"                             host: admin.faviann.com
"auth-passthrough"                                 host: auth.faviann.com
"homepage-editors"                                 host: home.faviann.com
"homepage-media"                                   host: media.faviann.com
```

All providers are **Forward auth (domain level)** mode.

### auth-passthrough provider (for auth.faviann.com)
- External host: `https://auth.faviann.com`
- Expression policy bound: `return True`
- Purpose: allow forwardAuth to pass for the Authentik UI itself

### catch-all provider
- External host: `https://faviann.com`
- Covers requests where X-Forwarded-Host is `faviann.com` or subdomains
- No group restriction (any authenticated user passes)

---

## The Problem

Visiting `auth.faviann.com` while unauthenticated causes an infinite redirect loop
with growing `rd=` query parameters until the browser gives up. Same loop was
observed on other domains before the catch-all external_host was fixed.

### What we know about Traefik v3 entrypoint middleware behavior

**Confirmed**: In Traefik v3, entrypoint-level middlewares are **additive** with
router-level middlewares — they cannot be suppressed per-router. Setting `no-auth`
(empty chain) on a router does NOT bypass the entrypoint's `forwardAuth`. Both run.

This means: every request through the `websecure` entrypoint calls Authentik's
`/outpost.goauthentik.io/auth/traefik` endpoint, including requests to
`auth.faviann.com` and to `/outpost.goauthentik.io/*` callback paths.

### Expected behavior (per Authentik docs)

Authentik's embedded outpost forward auth endpoint (`/outpost.goauthentik.io/auth/traefik`)
is supposed to return **200** when `X-Forwarded-Uri` starts with `/outpost.goauthentik.io/`,
regardless of authentication state. This is required for the domain-level forward auth
flow to work at all — otherwise the outpost's own callback/start URLs would loop.

### Actual behavior

The loop is occurring. Either:
1. The outpost is NOT returning 200 for `/outpost.goauthentik.io/*` paths on
   `auth.faviann.com` (even though it should by design)
2. OR the `auth-passthrough` provider + expression policy is not working as expected
   for unauthenticated users (expression policies only evaluate AFTER authentication,
   so unauthenticated users still get redirected to the login flow first)
3. OR the auth flow for `auth.faviann.com` redirects to a URL that also requires
   forwardAuth, and that URL also loops

---

## What Has Already Been Tried and Ruled Out

1. **`no-auth` empty chain middleware on routers** — does NOT bypass entrypoint default
   in Traefik v3. Confirmed by testing and Traefik docs.

2. **Per-router forwardAuth labels** — works technically but was rejected as a design
   decision. The user wants "auth by default" with no per-service noise.

3. **Duplicate provider conflict** — was `auth.faviann.com` appearing twice as
   external_host (catch-all + auth-passthrough). Fixed by changing catch-all to
   `faviann.com`. Now only `auth-passthrough` covers `auth.faviann.com`. Loop persists.

4. **Missing `authentik-outpost-root` router** — `faviann.com/outpost.goauthentik.io/*`
   was being caught by the Nginx redirect. Fixed by adding the router. Loop persists.

---

## Key Questions to Investigate

1. Does Authentik's embedded outpost (v2025.12.4) actually return 200 for
   `/outpost.goauthentik.io/*` paths in the forwardAuth check, or does it require
   authentication first? Check source or test directly with curl:
   ```bash
   curl -v -H "X-Forwarded-Proto: https" \
        -H "X-Forwarded-Host: auth.faviann.com" \
        -H "X-Forwarded-Uri: /outpost.goauthentik.io/start?rd=https://auth.faviann.com/" \
        http://auth.faviann.vms:9000/outpost.goauthentik.io/auth/traefik
   ```
   Expected: `200 OK`. If `302`, the outpost does NOT recognize its own paths.

2. If the outpost does NOT return 200 for its own paths: is there a way to configure
   it to do so? (Authentik settings, flow config, etc.)

3. If the outpost DOES return 200 for its own paths but `auth.faviann.com` still
   loops: what is the loop URL sequence? Capture from browser devtools.

4. Is `auth-passthrough` with `return True` expression policy the right Authentik
   construct for "allow all traffic including unauthenticated"? If not, what is?

---

## Constraints

- **Do not** move forwardAuth to per-router labels. The entrypoint default is a
  deliberate design choice.
- **Do not** suggest a separate public-facing port/entrypoint for auth.faviann.com.
- Keep the existing tier architecture: `*.admin.faviann.com`, `*.home.faviann.com`,
  `*.media.faviann.com` with domain-level Authentik providers per tier.
- Ansible is available to run commands on portal and auth hosts.
  Activate venv: `. /home/aperture/ServerManagementScripts/.ansible/venv/bin/activate`
  Portal stacks path: `/conf/docker/stacks/`
  Traefik config: `/conf/docker/stacks/traefik3/appdata/traefik3/config/`

---

## Suggested Debugging Steps

1. Run the curl test above against the forwardAuth endpoint to determine if Authentik
   returns 200 or 302 for outpost paths.
2. If 302: research whether there is an Authentik configuration to make outpost paths
   bypass the auth check. This may require creating a special authentication flow with
   no stages, or configuring the outpost differently.
3. If 200: the loop is elsewhere. Enable Traefik DEBUG logs temporarily and capture
   the exact redirect chain to identify where the loop originates.
4. Enable Traefik debug logging:
   In `traefik.yaml`, change `log.level` to `DEBUG`, copy to portal, restart Traefik.
   Logs at: `docker logs traefik 2>&1 | grep auth.faviann.com`
