# ADR-006: Accepted Stack Normalization Exceptions

- **Date**: 2026-04-21
- **Status**: Accepted

## Context

Most repo-managed Docker Compose stacks follow the normal stack contract in
[`stacks/README.md`](../../stacks/README.md). A few stacks intentionally differ
because they preserve upstream vendor shape, own infrastructure behavior, use a
VPN network namespace, or protect a special auth boundary.

The exception list needs to be discoverable from stack-wide work without making
the normal stack contract harder to scan.

## Decision

Normal application stacks follow `stacks/README.md`. The stacks below are
accepted exceptions and must not be normalized blindly.

| Stack | Exception Type | Local Notes |
| --- | --- | --- |
| `auth/auth` | Vendor-preserving Authentik base | [`stacks/auth/auth/README.md`](../../stacks/auth/auth/README.md) |
| `seedbox/bittorrent` | VPN namespace routing | [`stacks/seedbox/bittorrent/README.md`](../../stacks/seedbox/bittorrent/README.md) |
| `public/music` | Split native-auth and protected-browser routes | [`stacks/public/music/README.md`](../../stacks/public/music/README.md), [ADR-005](adr-005-navidrome-authentik-sync.md) |
| `portal/traefik3` | Domain-edge reverse proxy infrastructure | [`stacks/portal/traefik3/README.md`](../../stacks/portal/traefik3/README.md) |

These stacks are judgment-heavy examples, not canonical templates for new
stacks.

## Preservation Rule

Style cleanup is allowed only when it does not change routes, ports, auth
boundaries, storage, network namespaces, or secret flow.

Behavior-sensitive changes require explicit human approval or a superseding ADR.

## Consequences

- Stack-wide normalization has one central exception index.
- Stack-specific operational detail stays next to the stack.
- Agents and reviewers can find exceptions without reading every stack README.
- Future machine-readable exception metadata can be added later if validator
  tooling needs it.
