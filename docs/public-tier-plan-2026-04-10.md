# Plan: public Tier — Self-Auth Services (*.public.faviann.com)

Date: 2026-04-10  
Status: Reviewed

## Context

Moving Jellyfin, Jellystat, and Seerr from `*.media.faviann.com` to `*.public.faviann.com`.

The `public` tier is for services that manage their own authentication and must not be forced through Traefik's entrypoint-level forward-auth flow. Jellyfin is the primary driver because Authentik forward-auth breaks native clients and casting. Jellystat and Seerr move with it because the `jellyfin` host is now intentionally becoming a public-tier host by default.

Traefik v3's entrypoint-level `forwardAuth-authentik@file` still applies to every `websecure` request. Router-level empty chains do not bypass it. The public tier therefore uses the same pattern as the other shared wildcard tiers:

- shared Authentik provider in `forward_domain` mode
- callback anchor on `https://public.faviann.com`
- wildcard outpost routing for `*.public.faviann.com`
- full-URL allowlist that makes the provider effectively passthrough for the entire public tier

This change does not retire the media tier. `media.faviann.com` remains active for other media-facing surfaces, including the portal-hosted media homepage.

## Decisions

- Internet-accessible with no IP restriction
- All three stacks on the `jellyfin` host move together: `jellyfin`, `jellystat`, `seerr`
- `jellyfin` is now a public-tier host by default; future user-facing stacks there should default to `public.faviann.com` unless explicitly overridden
- Old `*.media.faviann.com` URLs for these three services die at cutover; no compatibility redirect
- `public.faviann.com` is only the shared callback anchor and DNS root for the tier; a `404` on `/` is acceptable
- Cloudflare records for `public.faviann.com` and `*.public.faviann.com` are `DNS only`
- Authentik provider and application remain manual for now
- HTTP-level validation is sufficient for this homelab
- Accepted debt: Jellystat secrets remain as-is for now

---

## What Changes In Repo

### 1. `inventory/host_vars/jellyfin.yml`

Change the host default domain:

```yaml
default_domain: public.faviann.com
```

This moves all three stacks via the existing `.env.j2` pattern:

```jinja2
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
```

Because `traefik-kop` also uses the host `DOMAIN` value, new public routes are registered automatically after deploy.

### 2. `stacks/jellyfin/jellystat/compose.yaml`

Jellystat is no longer admin-only in Homepage. Its labels change from `homepage.instance.admin.*` to plain `homepage.*` so it appears on the public/media-facing dashboard like Jellyfin and Seerr.

### 3. `stacks/portal/traefik3/appdata/traefik3/config/traefik.yaml`

Add `*.public.faviann.com` to the SAN list.

Important detail: `public.faviann.com` itself is already covered by the existing `*.faviann.com` wildcard. The new SAN is required for `jellyfin.public.faviann.com`, `jellystat.public.faviann.com`, and `seerr.public.faviann.com`.

### 4. `stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml`

Add two outpost callback routers:

```yaml
    authentik-outpost-public:
      rule: "Host(`public.faviann.com`) && PathPrefix(`/outpost.goauthentik.io`)"
      entryPoints: websecure
      service: authentik
      priority: 1001
      middlewares:
        - sslheader

    authentik-outpost-public-subdomains:
      rule: "HostRegexp(`^[a-z0-9-]+\\.public\\.faviann\\.com$`) && PathPrefix(`/outpost.goauthentik.io`)"
      entryPoints: websecure
      service: authentik
      priority: 1001
      middlewares:
        - sslheader
```

The root host router covers the shared callback anchor. The wildcard router covers app subdomains.

---

## Manual Steps (Outside Repo)

### A. Cloudflare DNS

Add two `DNS only` records pointing at the same public IP as the other `faviann.com` wildcards:

- `public.faviann.com`
- `*.public.faviann.com`

### B. Authentik — One Shared Wildcard Provider + One Application

Create the provider manually in the Authentik UI.

**Provider**:

- Name: `public-wildcard-forwardauth`
- Mode: `forward_domain`
- External host: `https://public.faviann.com`
- `skip_path_regex`: `^https://([a-z0-9-]+\.)?public\.faviann\.com/.*$`
- Bind to the embedded outpost
- Do not set `cookie_domain`

This is intentionally a full-host passthrough pattern. The goal is for any request on `public.faviann.com` or `*.public.faviann.com` to return `200` from the Authentik forward-auth check so the application's own login screen is reached instead of `auth.faviann.com`.

**Application**:

- Name / Slug: `public-wildcard`
- Provider: `public-wildcard-forwardauth`
- No group policy binding

### C. Deploy Repo Changes

Use sequential Ansible runs in one change window.

```bash
source .ansible/venv/bin/activate
ansible-playbook site.yml --limit portal
ansible-playbook site.yml --limit jellyfin
```

`portal` goes first because it owns the static Traefik config and outpost callback routing. `jellyfin` goes second because it republishes the actual app routes via `traefik-kop`.

---

## Routing Model And Safety

This design does not depend on provider-level `cookie_domain`. On this installation, shared wildcard behavior has been driven by provider mode, callback routing, and Authentik's global cookie-domain behavior, not by provider-local cookie settings.

The safety model is instead:

- `external_host=https://public.faviann.com`
- shared wildcard provider in `forward_domain` mode
- full-URL allowlist for `public.faviann.com` and `*.public.faviann.com`
- explicit public outpost routers on portal

That makes the public tier structurally parallel to the shared admin and home tiers, but with a passthrough allowlist instead of a login-enforcing allowlist.

---

## Validation

Run the checks below after the sequential deploy. Allow roughly 60 to 120 seconds before declaring the old media URLs dead, because `traefik-kop` polls on a 60-second interval.

```bash
# 1. Shared callback anchor exists
curl -kI https://public.faviann.com/outpost.goauthentik.io/ping

# 2. Wildcard subdomain outpost routing exists
curl -kI https://jellyfin.public.faviann.com/outpost.goauthentik.io/ping

# 3. Jellyfin reaches Jellyfin, not Authentik
curl -kIL --max-redirs 3 https://jellyfin.public.faviann.com/

# 4. Seerr reaches Seerr, not Authentik
curl -kIL --max-redirs 3 https://seerr.public.faviann.com/

# 5. Jellystat reaches Jellystat, not Authentik
curl -kIL --max-redirs 3 https://jellystat.public.faviann.com/

# 6. Old media URL is gone after a short grace window
curl -kI https://jellyfin.media.faviann.com/
```

Expected results:

- steps 1 and 2 return `204`
- steps 3 through 5 land on each app's own UI or login screen, not `auth.faviann.com`
- step 6 returns `404`, TLS failure, or another non-working result once `traefik-kop` has had time to remove the stale route

If a public app root still redirects to `auth.faviann.com`, treat that as a provider-selection failure. Check:

- provider name and mode
- `skip_path_regex`
- that the provider is attached to the embedded outpost
- that both public outpost routers are live on portal

---

## Files Modified

| File | Change |
|------|--------|
| `inventory/host_vars/jellyfin.yml` | `default_domain: public.faviann.com` |
| `stacks/jellyfin/jellystat/compose.yaml` | Jellystat Homepage labels become public instead of admin-only |
| `stacks/portal/traefik3/appdata/traefik3/config/traefik.yaml` | Add `*.public.faviann.com` SAN |
| `stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml` | Add public callback routers |

No new roles, scripts, or variables are required for this first cut.
