# Stack Normalization Exception Review

Date: 2026-04-21

Purpose: track stack normalization exceptions that need human review before they become policy. These stacks are migration targets with special behavior, not canonical examples for new stacks.

Rules for this review:

- Every exception below is pending review.
- Preserve current behavior until the review decision is recorded.
- Do not inspect, print, paste, or document secret values. Secret-adjacent files may be audited by key name only.
- Low-risk style cleanup is allowed only when it does not alter routes, ports, auth boundaries, storage, network namespaces, or secret flow.
- At the end of the normalization process, review this document and remove anything that became normal repo behavior, was resolved by cleanup, or is too broad to be a useful exception.

## Review Status Legend

| Status | Meaning |
| --- | --- |
| Needs review | Initial analysis exists, but the exception is not accepted policy yet. |
| Accepted | Human-reviewed and intentional. |
| Rework needed | Human-reviewed and should be normalized or redesigned. |

## `auth/auth`

Status: Accepted vendor-preserving base

Initial conclusion: likely a vendor-preserving Authentik stack. The base `compose.yaml` keeps upstream-style structure, including `env_file:`, no `container_name`, a named `database` volume, and upstream image/tag defaults. Repo-specific behavior is layered in `compose.override.yaml.j2` with bind mounts, networks, labels, custom blueprints, and local integration environment.

Review decision: keep the upstream-shaped base compose and repo-owned override split. Do not force normal app-stack style into the base compose. The stack now uses tracked `.env.j2` plus vault-backed host vars as the source of truth while preserving `env_file: .env` in the base compose.

Deferred follow-up questions:

- How reliable would it be to make every repo-managed stack use an override file, versus reserving overrides for vendor-preserving or generated-layer cases?
- Can Authentik stop depending directly on Navidrome automation credentials by letting the reconciler own or manage that credential boundary?

Preserve:

- Do not force full contract normalization into `compose.yaml`.
- Do not remove `env_file:` from the base compose.
- Do not force `container_name` into upstream services.
- Do not convert the base named volume solely for style.
- Do not move repo-specific override behavior into the base compose just to reduce files.

Cleanup candidates:

- Review whether the named database volume should remain upstream-preserving or be fully owned by the repo override.

## `seedbox/bittorrent`

Status: Accepted

Initial conclusion: likely an intentional VPN namespace stack. `qbittorrent` uses `network_mode: service:gluetun`, so qBittorrent ports are expected to publish on `gluetun`, not on the `qbittorrent` service. This is a valid exception to any simple "routed service must declare ports" rule.

Review decision: accepted only for VPN namespace routing. `qbittorrent` and `ws-ephemeral` intentionally share the `gluetun` network namespace, and qBittorrent's reachable ports intentionally publish on `gluetun`. This does not make the rest of the stack a blanket exception to normal cleanup.

Preserve:

- Do not move qBittorrent Web UI or torrenting ports from `gluetun` to `qbittorrent`.
- Do not remove `network_mode: service:gluetun`.
- Do not treat `qbittorrent` route labels without local service ports as a blocker.

## `public/music`

Status: Accepted

Initial conclusion: likely intentional and already partly documented by ADR-005. The stack uses a split auth model: `music.public.faviann.com` stays edge-open for Navidrome native auth and Subsonic clients, while `music.media.faviann.com` uses `protected-edge-auth@file` for browser access. The `reconciler` service name and `container_name: navidrome-reconciler` mismatch appears operationally clearer than forcing the container name to match the generic service name.

Review decision: ADR-005 controls normalization for this stack. The split public/native-auth and protected/browser route model is intentional. Future cleanup may normalize formatting only, and must preserve both route boundaries and the reconciler integration.

Preserve:

- Do not collapse the two Traefik routers into one route.
- Do not add forwardAuth to the public music router.
- Do not remove the protected media router.
- Do not force `container_name: reconciler` solely for style.
- Do not change reconciler secret flow or Authentik/Navidrome integration during stack style cleanup.

## `portal/traefik3`

Status: Accepted, with follow-up cleanup

Initial conclusion: likely an infrastructure/bootstrap stack with intentional deviations from normal app-stack style. The `443:443/tcp` and `443:443/udp` port mappings are not an accidental duplicate because they publish different protocols. Static env key names are secret-adjacent and should be reviewed by key name only.

Review decision: `portal/traefik3` is a domain-edge reverse proxy stack for a specific hosted domain. Its shape is intentional for this role and may repeat if the system later grows a multi-domain or multi-tenant hosting model with additional reverse proxies. Same-number TCP/UDP port mappings are accepted for this pattern. Redis is a normal service in this stack, `x-managed-files` is a normal repo feature, and certificate storage is normal persistent stack state. Runtime env values now use tracked `.env.j2` plus vault-backed portal vars.

Preserve:

- Do not remove either `443/tcp` or `443/udp`.
- Do not treat same-number TCP and UDP ports as a port conflict.
- Do not treat Redis, certificate storage, or `x-managed-files` as exception-only behavior; evaluate them as normal stack features used by a domain-edge reverse proxy.
- Do not read or print files under `stacks/portal/traefik3/secrets/`.
- Do not document `.env` values.
- Do not normalize this stack as if it were a normal routed application; evaluate it as a domain-edge reverse proxy.

Cleanup candidates:

- Review whether Traefik should keep direct read-only Docker socket access or use a socket proxy with the capabilities Traefik's Docker provider requires.

## Batch 3 Outcome

This document records initial analysis and review decisions. Entries marked `Accepted` are accepted only within the preserve boundaries listed for that stack. Entries still marked `Needs review` must be reviewed before changing behavior-sensitive fields.

Final cleanup checkpoint: before handing this work back for the later `create-stack` rewrite, reread this document against the final stack state. Delete stale cleanup notes, narrow any broad exceptions, and keep only decisions that should guide future stack creation or validation.
