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

- Authentik expression policies mirror plaintext passwords into Navidrome. They
  run only in flows where the plaintext is available.
- A periodic reconciler creates, enables, and disables Navidrome users and
  updates their email. It never sets passwords.
- Authentik reaches Navidrome at the internal URL
  `http://public.faviann.vms:4533`, not the public hostname.
- Navidrome admin API calls log in with `POST /auth/login` and send
  `X-ND-Authorization: Bearer <token>`. The API does not take HTTP Basic auth.
- The stack exports its public route with the minimal contract:
  `traefik.enable=true` plus
  `traefik.http.services.music.loadbalancer.server.port=4533`.

The password-change blueprint, blueprint 27, finds its policy binding target
by the managed stage's stable name instead of a hardcoded `pbm_uuid`:

```yaml
target: !Find [authentik_flows.flowstagebinding, [stage__name, default-password-change-prompt]]
```

`default-password-change-prompt` is an Authentik managed stage. It exists under
that name on every instance from first startup, so no manual bootstrap step is
needed. [Blueprint `!Find` lookups](../stacks-authentik.md#blueprint-find-lookups)
explains the `__` traversal.

## Accepted costs

- Browser users log in to Navidrome directly on the public hostname. No
  Authentik browser login happens there.
- Browser convenience on the same hostname would risk mobile regressions and
  route-export drift.
- Resetting the automation user's password non-interactively needed a
  TTY-backed Navidrome CLI session.
- Re-applying the password-change blueprint can hit duplicate binding
  collisions on `policy,target,order`.

## Rejected

- **Authentik forwardAuth for browsers on `music.public.faviann.com`**: the
  attempt added a dedicated Authentik proxy provider, an application, outpost
  wiring, and portal callback routers. It destabilized routing again and again,
  and it mixed two incompatible auth models on one hostname.

## When to revisit

Supersede this decision if mobile and Subsonic support stops being the
priority, or if browser convenience needs a different auth boundary.
