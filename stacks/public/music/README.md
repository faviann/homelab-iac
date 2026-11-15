# Music Stack

This stack runs Navidrome on the `public` Docker host with a split auth model.
`music.public.faviann.com` stays edge-open for Navidrome native auth and
Subsonic clients. `music.media.faviann.com` uses `protected-edge-auth@file` for
browser access.

ADR-0023 documents the Authentik/Navidrome sync decision:
[`docs/adr/0023-use-navidrome-native-auth-on-the-public-music-hostname.md`](../../../docs/adr/0023-use-navidrome-native-auth-on-the-public-music-hostname.md).

## Normalization Boundary

This stack intentionally does not follow every ordinary app-stack default.

Preserve:

- Do not collapse the public and protected Traefik routers into one route.
- Do not add forwardAuth to the public music router.
- Keep `strip-authentik-identity@file` on the public music router. Navidrome
  trusts `X-authentik-username` from Traefik, so without it a client could
  sign in as any user by sending that header.
- Do not remove the protected media router.

Do not use this stack as a template for normal application stacks.

## Ownership

Stack-owned:

- `compose.yaml`
- `.env.j2`
- Navidrome routing

Auth-owned:

- the Authentik `media-wildcard` application, which gates `music.media`

Host-owned:

- music library path
- public host vault-backed variable bindings in `inventory/host_vars/public.yml`

## Deploy

```bash
./run.sh --limit public --stack music
```
