# Authentik sign-in

Authentik at `https://auth.faviann.com` is the single sign-on every protected service uses. A user opening it lands on the login flow, and a user opening a protected service is redirected to it before the service answers.

## Sub-features

- `auth-login` serves the default authentication flow to an anonymous user.
- `auth-health` reports the server live and ready (database and cache reachable).
- `auth-forward` sends anonymous requests for a protected route to the Authentik authorize endpoint.

## How to get to it (user POV)

- Open `https://auth.faviann.com/` in a browser.
- Open any protected route, for example `https://homepage.admin.faviann.com/`, while signed out.

## Driving it with inspect.sh

Preconditions:

- Runs as anonymous.
- Doctor passed for `portal,auth`.
- `auth.faviann.com` resolves (`getent ahostsv4 auth.faviann.com`). On the LAN it resolves to the edge, `10.1.0.2`.

- **Login page.** Open the root signed out. Run `./inspect.sh probe https://auth.faviann.com/`. `PASS` with `status=302 location=https://auth.faviann.com/flows/-/default/authentication/`.
- **Health.** Check live and ready. Run `./inspect.sh probe https://auth.faviann.com/-/health/live/ https://auth.faviann.com/-/health/ready/`. Both `PASS` with `status=200` and an empty body.
- **Forward auth.** Open a protected route signed out. Run `./inspect.sh probe https://homepage.admin.faviann.com/`. `PASS` with `status=302 location=https://auth.faviann.com/application/o/authorize/`.
- **Proof.** Run all four URLs in one call into the evidence directory: `./inspect.sh probe https://auth.faviann.com/ https://auth.faviann.com/-/health/live/ https://auth.faviann.com/-/health/ready/ https://homepage.admin.faviann.com/ > "$ev/auth.log" 2>&1; echo "exit=$?" >> "$ev/auth.log"`. Four `PASS` lines and `exit=0`.

## Gotchas

- Two Traefik routers match `auth.faviann.com`: the Docker-label route from `stacks/auth/auth/compose.override.yaml.j2` and the file router `authentik` in `stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml`. The file router has priority 1000 and serves the name, so debug routing there first.
- `ready` returns `503` while Authentik is starting or its database is down. `live` can pass at the same time. Report `ready`, not `live`, as the backend proof.
- The probe strips the redirect's query. The authorize URL's `state` and `client_id` never reach the evidence. Do not re-fetch them with another client.
- A `302` to the flow proves the login page is served, not that sign-in works. Every signed-in journey signs in before its first URL, so [Homepage media](./homepage-media.md) or [RomM](./romm.md) proves sign-in.
