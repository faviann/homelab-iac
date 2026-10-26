# Homepage media

The media-tier dashboard at `https://homepage.media.faviann.com` sits behind Authentik forward auth. A signed-out user is sent to Authentik first. A signed-in user with media-tier access gets Homepage, which has no login of its own.

## Sub-features

- `homepage-media-gate` sends a signed-out request to the Authentik authorize endpoint.
- `homepage-media-signed-in` serves Homepage's health endpoint to a signed-in user the media tier admits.

## How to get to it (user POV)

- Open `https://homepage.media.faviann.com/` in a browser, sign in to Authentik when asked, and land on the dashboard.

## Driving it with inspect.sh

Preconditions:

- Runs as anonymous for the gate, and as `verify-agent` for the signed-in step, admitted by the order-3 user binding on `app-media-wildcard` in `stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml`.
- Doctor passed for `portal,auth`. Homepage runs on `portal`, and the signed-in step signs in on `auth`.

- **Gate.** Open the health endpoint signed out. Run `./inspect.sh probe https://homepage.media.faviann.com/api/healthcheck`. `PASS` with `status=302 location=https://auth.faviann.com/application/o/authorize/`.
- **Signed in.** Open the same endpoint as `verify-agent`. Run `./inspect.sh journey https://homepage.media.faviann.com/api/healthcheck`. `PASS` with `status=200`, `hops` passing through `https://auth.faviann.com/application/o/authorize/`, and a last hop of `200:https://homepage.media.faviann.com/api/healthcheck`. `body=up`, Homepage's health answer, not an Authentik page.
- **Proof.** Run both into one log: `{ ./inspect.sh probe https://homepage.media.faviann.com/api/healthcheck; echo "exit=$?"; ./inspect.sh journey https://homepage.media.faviann.com/api/healthcheck; echo "exit=$?"; } > "$ev/homepage-media.log" 2>&1`. Two `PASS` lines and two `exit=0`.

## Gotchas

- Homepage has no login of its own, so a `200` from it past forward auth means the media tier admitted `verify-agent`. Authorization is per tier, not per host: the binding admits `verify-agent` to every media-tier host.
- Keep journeys off `music.media.faviann.com`. Navidrome trusts the forwarded username and would create a Navidrome account for `verify-agent`.
- The admin tier has no `verify-agent` binding, so a journey to an admin-tier host such as `homepage.admin.faviann.com` ends `FAIL`. That is the intended boundary, not a fault.
- `detail="not walked: sign-in stopped at ak-stage-captcha"` means Authentik did not see the control node's LAN address and asked for the Turnstile captcha.
