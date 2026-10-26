# Fleet services verification map

This directory is the maintained source for verifying what the fleet serves to its users: HTTPS services reached by name through the edge and Traefik on `portal`. Read the index before driving, then use the matching feature file as the recipe. The harness is `./inspect.sh probe` for anonymous probes and `./inspect.sh journey` for signed-in journeys, both described in [the skill](../SKILL.md#drive).

## Baseline preconditions

- Run from a checkout of this repository on a control node (the `workstation` LXC normally).
- The doctor in [the skill](../SKILL.md#doctor) passed in this run, for `portal` and the feature's host.
- An evidence directory exists for this run under `~/.ansible/verify-evidence/`.
- The [rules](../SKILL.md#rules) hold for every journey.

## Driving conventions

- Every journey is `GET`s. An anonymous probe sends them as a signed-out browser. A signed-in journey sends them as `verify-agent` after one Authentik sign-in, following redirects. A journey that needs another identity, a write, or a human step is out of scope. Report it as not verified.
- Pass every URL of one feature's journey to a single call, so one log holds the whole journey. In a signed-in journey the order matters: a native OIDC app's login URL comes before the URLs that need its session.
- Use the stable handles each feature names: route paths and JSON keys, never HTML layout.
- Compare versions against the repo pin the feature file names, read from the checkout at the commit under test.

## Proof and skip reporting

- Proof is the probe or journey log: one `PASS` or `FAIL` line per URL with status, redirect target, content type, and the first 160 characters of the body, plus the command's exit status. A journey line also lists its hops.
- A health endpoint alone proves the backend answers. A feature also needs its user entry point (web UI or login redirect) and, where the feature lists one, the version matching the repo pin.
- Record the feature file and the URLs used with every log.
- Report an unreachable URL with the probe line and the doctor result. Do not report a feature as verified through a different URL than the one its file names.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections in this order: `Sub-features`, `How to get to it (user POV)`, `Driving it with inspect.sh` (starting with `Preconditions:`), and `Gotchas`.

The preconditions start with a `Runs as` line naming the identity: `anonymous` for `./inspect.sh probe`, or `verify-agent` for `./inspect.sh journey` together with the file that holds its access binding.

## Features

- [Authentik sign-in](./auth.md) covers the SSO login page, its health, and the forward-auth redirect protected routes send.
- [Jellyfin](./jellyfin.md) covers the media server's web UI, health, and public server info with its version.
- [Immich](./immich.md) covers the photo library's web UI, API ping, version, and enabled features.
- [Homepage media](./homepage-media.md) covers the media-tier dashboard behind forward auth, signed out and signed in as `verify-agent`.
- [RomM](./romm.md) covers the game library's native OIDC sign-in and its signed-in user, as `verify-agent`.
