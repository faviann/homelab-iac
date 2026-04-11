# Authentik Integration

Read when creating or modifying Authentik providers, applications, or auth bypass rules for a stack.

The catch-all provider covers `faviann.com` and its subdomains, so most routed services need no per-app Authentik object just to require login.

Create a dedicated Proxy Provider + Application when:
- access is group-restricted
- the hostname needs a non-catch-all provider
- the service is self-auth and should bypass Traefik login

Repo-specific rules:
- admin uses shared `admin-wildcard-forwardauth`
- home uses shared `home-wildcard-forwardauth`
- public self-auth services use `public.faviann.com` plus shared `public-wildcard-forwardauth`
- shared callback tiers rely on global `AUTHENTIK_COOKIE_DOMAIN=.faviann.com`

Important: auth runs at the Traefik `websecure` entrypoint. Any pre-login URL must be allowlisted in the matching provider's `Unauthenticated URLs / Paths`, including `https://<domain>/outpost.goauthentik.io/...`. Router-level empty middleware chains do not bypass entrypoint auth.

| Need | Action |
| --- | --- |
| Basic login only | none; catch-all handles it |
| Shared admin-tier login | keep `admin-wildcard-forwardauth` synced |
| Group restriction | create provider + application and bind groups |
| Self-auth public app | use `public.faviann.com` and `public-wildcard-forwardauth` |

Current non-catch-all providers: `admin-wildcard-forwardauth`, `home-wildcard-forwardauth`, and `homepage-media`.
