# Use Navidrome native auth on the public music hostname

Navidrome serves mobile Subsonic clients first. Those clients call `/rest`
directly and cannot follow browser-style Authentik forwardAuth redirects.
Authentik still owns account approval, password changes, and media-group
lifecycle.

So `music.public.faviann.com` stays edge-open at Traefik, and Navidrome native
auth guards it. `https://music.public.faviann.com/rest/...` serves Subsonic
clients, and `https://music.public.faviann.com/api/user` works through the
native login and token flow. Browser convenience gets a separate hostname and
never changes `music.public.faviann.com`. The protected
`music.media.faviann.com` route is that hostname.

## How Authentik stays the identity source

- Navidrome cannot check a Subsonic login against Authentik. Subsonic token
  auth sends a hash of the password and a salt, so the server must hold the
  plaintext password itself.
- Mobile clients authenticate with OpenSubsonic API keys instead of a
  password. A user signs in on `music.media.faviann.com` through Authentik and
  creates one key per player under Settings, Players. Keys ship in the first
  Navidrome release after 0.64.2.
- A periodic reconciler creates, enables, and disables Navidrome users and
  updates their email. It never sets passwords. Disabling a user ends their
  access once Authentik removes them from `media`.
- Navidrome admin API calls log in with `POST /auth/login` and send
  `X-ND-Authorization: Bearer <token>`. The API does not take HTTP Basic auth.
- The stack exports its public route with the minimal contract:
  `traefik.enable=true` plus
  `traefik.http.services.music.loadbalancer.server.port=4533`.

## Accepted costs

- Browser users log in to Navidrome directly on the public hostname. No
  Authentik browser login happens there.
- Browser convenience on the same hostname would risk mobile regressions and
  route-export drift.
- Resetting the automation user's password non-interactively needed a
  TTY-backed Navidrome CLI session.
- A client without API-key support can send the username and the key as a
  plain password. Clients that send only a hashed token cannot connect.

## Rejected

- **Authentik forwardAuth for browsers on `music.public.faviann.com`**: the
  attempt added a dedicated Authentik proxy provider, an application, outpost
  wiring, and portal callback routers. It destabilized routing again and again,
  and it mixed two incompatible auth models on one hostname.
- **Copying plaintext passwords from Authentik into Navidrome**: Authentik
  expression policies sent the password to Navidrome's admin API from the
  sign-up and password-change flows. Authentik sees the plaintext nowhere else,
  so social sign-ins, email recovery, and admin-set passwords left Navidrome
  with a password the user did not know.

## When to revisit

Supersede this decision if mobile and Subsonic support stops being the
priority, or if browser convenience needs a different auth boundary.
