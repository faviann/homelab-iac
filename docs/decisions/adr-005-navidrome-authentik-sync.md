# ADR-005: Navidrome uses native auth on the public hostname

- **Date**: 2026-04-18
- **Status**: Accepted

## Context

Navidrome needed to support mobile Subsonic clients first. Those clients require direct access to `/rest` and cannot rely on browser-style Authentik forwardAuth redirects.

During implementation, a browser-forwardAuth design was explored for `music.public.faviann.com`, including a dedicated Authentik proxy provider, application, outpost wiring, and portal callback routers. That path repeatedly introduced routing instability and mixed two incompatible auth models on the same public hostname.

At the same time, Authentik still needed to remain the source of truth for account approval, password changes, and media-group lifecycle.

## Decision

We keep `music.public.faviann.com` edge-open at Traefik and use Navidrome native auth on that hostname.

Auth-related behavior is split as follows:

- Authentik expression policies mirror plaintext passwords into Navidrome only during flows where plaintext is available.
- A periodic reconciler manages user creation, enablement, disablement, and email updates.
- The reconciler does not set passwords.
- Authentik-side Navidrome sync uses the internal URL `http://public.faviann.vms:4533`, not the public hostname.
- Navidrome admin API calls use `POST /auth/login` and `X-ND-Authorization: Bearer <token>`, not HTTP Basic auth.
- Public Traefik exposure for the Navidrome stack uses the minimal route-export contract: `traefik.enable=true` plus `traefik.http.services.music.loadbalancer.server.port=4533`.

Browser convenience, if reintroduced later, must use a separate hostname rather than changing `music.public.faviann.com`.

## Principle

- **SRP**: Authentik password mirroring and reconciler lifecycle sync have separate responsibilities.
- **DRY**: Authentik remains the identity source; Navidrome does not become a second manual identity authority.
- **Dependency Inversion**: Sync logic depends on stable contracts: Authentik flow context, Navidrome login flow, and declared environment variables.

## Consequences

This makes mobile and API behavior stable:

- `https://music.public.faviann.com/rest/...` works for Subsonic clients.
- `https://music.public.faviann.com/api/user` works through Navidrome-native login/token flow.
- Browser users log into Navidrome directly on the public hostname.

This makes browser SSO less convenient on the public hostname:

- There is no automatic Authentik browser login on `music.public.faviann.com`.
- Reintroducing browser convenience on the same hostname would risk mobile regressions and route-export drift.

Operational facts to retain:

- Navidrome JSON admin API is token-based, not Basic-auth based.
- Resetting the automation user password non-interactively required a TTY-backed Navidrome CLI session.
- Re-applying the password-change blueprint may hit duplicate binding collisions on `policy,target,order`.

## Deviation Conditions

A superseding ADR is required if either of the following becomes true:

- mobile/Subsonic support is no longer the primary priority
- browser convenience is required strongly enough to justify a second hostname or a different auth boundary

## DES-010 Resolution

The hardcoded `pbm_uuid` in blueprint 27 was replaced with a stable `!Find` reference:

```yaml
target: !Find [authentik_flows.flowstagebinding, [stage__name, default-password-change-prompt]]
```

`default-password-change-prompt` is an Authentik managed stage - it exists with a stable name on every instance from first startup. No manual bootstrap step is required. See `docs/decisions/adr-006-authentik-find-tag-internals.md` for the `!Find` `__` traversal reference.