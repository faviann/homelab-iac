# Authentik Integration

Read when creating or modifying Authentik providers, applications, or auth bypass rules for a stack.

Traefik edge auth is explicit per protected router via `protected-edge-auth@file`.
Public routers should stay edge-open unless there is a specific reason to protect them at Traefik.

The shared proxy providers cover the protected tiers, so most protected services need no per-app Authentik object just to require login.

Create a dedicated Proxy Provider + Application when:
- access is group-restricted
- the hostname needs a non-catch-all provider
- the service is self-auth and should stay edge-open at Traefik

Repo-specific rules:
- admin uses shared `admin-wildcard-forwardauth`
- home uses shared `home-wildcard-forwardauth`
- media uses shared `media-wildcard-forwardauth`
- root `faviann.com` uses `Provider for Domain Wide Forward Auth Catch All` when edge auth is desired
- shared callback tiers rely on global `AUTHENTIK_COOKIE_DOMAIN=.faviann.com`

Important: only protected routers should send traffic through Traefik forwardAuth. Public apps that use native auth or OIDC should not also sit behind Traefik forwardAuth.
For protected tiers, the matching provider still needs the outpost callback URL allowlisted in `Unauthenticated URLs / Paths`, including `https://<domain>/outpost.goauthentik.io/...`.

| Need | Action |
| --- | --- |
| Basic protected-tier login | add `protected-edge-auth@file`; shared provider handles login |
| Public app with native auth/OIDC | no Traefik auth middleware |
| Shared admin-tier login | keep `admin-wildcard-forwardauth` synced |
| Group restriction | create provider + application and bind groups |

Current shared protected-tier providers: `admin-wildcard-forwardauth`, `home-wildcard-forwardauth`, `media-wildcard-forwardauth`, and `Provider for Domain Wide Forward Auth Catch All`.

## Native OIDC Pattern

For public apps that should stay edge-open and handle login themselves:

- do not add `protected-edge-auth@file` to the Traefik router
- create an Authentik OAuth2/OpenID provider plus application
- select an Authentik signing key explicitly in the provider so the JWKS endpoint publishes keys for the client
- add the app's OIDC environment variables via `.env.j2`
- keep the redirect URI exact: `https://<host>/api/oauth/openid`

RomM is the repo example for this pattern:

- Authentik blueprint: `stacks/auth/auth/appdata/authentik/blueprints/35-public-romm-oidc.yaml.j2`
- RomM stack env: `stacks/public/romm/.env.j2`

RomM-specific notes from the official docs:

- Authentik 2025.10+ defaults `email_verified` to `false`, so RomM needs a scope mapping that returns `email_verified: True`
- `OIDC_SERVER_APPLICATION_URL` should use the Authentik application URL with its trailing slash intact
- the user's email in RomM must match the user's email in Authentik
- first-time OIDC users are created in RomM with viewer permissions
- if the provider is left on Authentik's symmetric default signing mode, metadata may advertise `HS256` and the JWKS endpoint may return `{}`, which breaks RomM's OIDC login flow
- repo-managed RomM OIDC uses `auth_romm_oidc_signing_certificate_name` from `inventory/host_vars/auth.yml`; the referenced certificate/keypair must exist in Authentik
