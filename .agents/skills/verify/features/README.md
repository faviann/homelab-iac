# Fleet services verification map

This directory is the maintained source for verifying what the fleet serves to its users: HTTPS services reached by name through the edge and Traefik on `portal`. Read the index before driving, then use the matching feature file as the recipe. The harness is `./inspect.sh probe`, described in [the skill](../SKILL.md#drive).

## Baseline preconditions

- Run from a checkout of this repository on a control node (the `workstation` LXC normally).
- The doctor in [the skill](../SKILL.md#doctor) passed in this run, for `portal` and the feature's host.
- An evidence directory exists for this run under `~/.ansible/verify-evidence/`.
- The [rules](../SKILL.md#rules) hold for every journey.

## Driving conventions

- Every journey is unauthenticated `GET`s, as an anonymous browser sends them. Logged-in journeys need a person's credentials and are out of scope. Report them as not verified.
- Pass every URL of one feature to a single `./inspect.sh probe` call, so one log holds the whole journey.
- Use the stable handles each feature names: route paths and JSON keys, never HTML layout.
- Compare versions against the repo pin the feature file names, read from the checkout at the commit under test.

## Proof and skip reporting

- Proof is the probe log: one `PASS` or `FAIL` line per URL with status, redirect target, content type, and the first 160 characters of the body, plus the command's exit status.
- A health endpoint alone proves the backend answers. A feature also needs its user entry point (web UI or login redirect) and, where the feature lists one, the version matching the repo pin.
- Record the feature file and the URLs used with every log.
- Report an unreachable URL with the probe line and the doctor result. Do not report a feature as verified through a different URL than the one its file names.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections in this order: `Sub-features`, `How to get to it (user POV)`, `Driving it with inspect.sh probe` (starting with `Preconditions:`), and `Gotchas`.

## Features

- [Authentik sign-in](./auth.md) covers the SSO login page, its health, and the forward-auth redirect protected routes send.
- [Jellyfin](./jellyfin.md) covers the media server's web UI, health, and public server info with its version.
- [Immich](./immich.md) covers the photo library's web UI, API ping, version, and enabled features.
