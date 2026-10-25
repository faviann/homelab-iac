# RomM

RomM at `https://romm.public.faviann.com` serves the game library and signs users in through Authentik with native OIDC. A user's first sign-in creates a RomM viewer account for them.

## Sub-features

- `romm-oidc-login` takes RomM's login start through Authentik's authorize endpoint and back to RomM's callback, which opens a RomM session.
- `romm-me` answers the signed-in session's own user from the RomM API.

## How to get to it (user POV)

- Open `https://romm.public.faviann.com/` in a browser and choose the Authentik login. RomM redirects to Authentik and back.

## Driving it with inspect.sh

Preconditions:

- Runs as `verify-agent`, admitted by `verify_agent: true` on RomM in `stacks/auth/auth/appdata/authentik/oidc-apps.yaml`, which generates its order-3 binding in `80-oidc-apps.yaml.j2`.
- Doctor passed for `portal,auth,public`. RomM runs on `public`, and the journey signs in on `auth`.

- **Login.** Run RomM's login start signed in. The first URL of the proof below is `https://romm.public.faviann.com/api/login/openid`. `PASS` with `status=200`, and `hops` that start at that URL, pass through `https://auth.faviann.com/application/o/authorize/` and RomM's callback `https://romm.public.faviann.com/api/oauth/openid`, and end on a RomM page.
- **Signed-in user.** The second URL, `https://romm.public.faviann.com/api/users/me`, reads the user the session belongs to. `PASS` with `status=200 content_type=application/json` and JSON for `verify-agent`, whose email is `verify-agent@faviann.com`.
- **Proof.** Run both URLs in one journey, login first: `./inspect.sh journey https://romm.public.faviann.com/api/login/openid https://romm.public.faviann.com/api/users/me > "$ev/romm.log" 2>&1; echo "exit=$?" >> "$ev/romm.log"`. Two `PASS` lines and `exit=0`.

## Gotchas

- The first journey creates one RomM viewer account for `verify-agent` ([stacks/public/romm/README.md](../../../../stacks/public/romm/README.md)). Later journeys reuse it. That account is the one write the rules allow here.
- Order matters. `/api/users/me` before the login, or alone, answers `403 {"detail":"Forbidden"}`, because no RomM session exists yet.
- RomM matches users by email. `verify-agent`'s email comes from `stacks/auth/auth/appdata/authentik/blueprints/50-service-accounts.yaml`.
- The hops drop queries, so the authorization code and `state` on the callback never reach the evidence.
- `*.public.faviann.com` takes the WAN path. See the Jellyfin gotcha.
