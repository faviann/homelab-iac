# Landing page

`https://faviann.com` is the front door for family and friends. It sits behind Authentik forward auth. A signed-in user lands on a static page that links every user-facing service, unless they are in `admins` or `content-editor`, whose Homepage dashboards it redirects them to. `/about`, `/privacy`, and `/terms` stay public for the social login provider consoles.

## Sub-features

- `landing-gate` sends a signed-out request for the page to the Authentik authorize endpoint.
- `landing-legal` serves the three legal pages without sign-in.

## How to get to it (user POV)

- Open `https://faviann.com/` in a browser and sign in to Authentik when asked. Admins land on their dashboard and can open the page at `https://faviann.com/index.html`.

## Driving it with inspect.sh

Preconditions:

- Runs as anonymous.
- Doctor passed for `portal,auth`. The page runs in the `portal-entry` stack on `portal`.

- **Gate.** Open the page signed out. Run `./inspect.sh probe https://faviann.com/`. `PASS` with `status=302 location=https://auth.faviann.com/application/o/authorize/`.
- **Legal.** Open the legal pages signed out. Run `./inspect.sh probe https://faviann.com/about https://faviann.com/privacy https://faviann.com/terms`. Three `PASS` lines with `status=200`.
- **Proof.** Run all four URLs in one call: `./inspect.sh probe https://faviann.com/ https://faviann.com/about https://faviann.com/privacy https://faviann.com/terms > "$ev/landing.log" 2>&1; echo "exit=$?" >> "$ev/landing.log"`. Four `PASS` lines and `exit=0`.

## Gotchas

- A signed-in journey stops at `default-provider-authorization-explicit-consent`, because the `faviann-domain` application asks `verify-agent` for consent. The signed-in page is out of reach until that changes.
- The redirect for admins and content editors reads the `X-authentik-groups` header in `stacks/portal/portal-entry/appdata/nginx/conf.d/redirect.conf`. A user in neither group gets the page.
