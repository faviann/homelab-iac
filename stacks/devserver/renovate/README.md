# Renovate

Self-hosted Renovate for this repository. The repository config is
[`renovate.json`](../../../renovate.json); what it does is described in
[Image Updates](../../README.md#image-updates).

## How it runs

`renovate` is a long-running service. Its command loops under the image's own
entrypoint: run Renovate, sleep six hours, repeat. A failed run is logged and
the loop carries on. A deploy that recreates the container, or a restart, runs
Renovate immediately. Read the runs with `docker logs renovate`.

Every run looks up all images and refreshes the Dependency Dashboard. The
weekly window is `schedule` in `renovate.json`: all of Saturday, Montreal time.
Outside it, Renovate creates no new branch or PR. A PR that already exists is
still rebased and updated by any run.

A tick on the Dependency Dashboard does not wait for the window. The ticked
item is created by the next run, within six hours. Items held only by the
schedule are listed under "Awaiting Schedule", and ticking one creates it
early.

The loop sleeps six hours, so every Saturday window gets several runs.

The container needs no volume. Its cache lives in the container filesystem and
survives restarts until the container is recreated.

## Token

`RENOVATE_TOKEN` comes from `vault_renovate_token`. Use a fine-grained GitHub
token scoped to `faviann/homelab-iac` with read and write access to:

- Contents
- Pull requests
- Issues (for the Dependency Dashboard)
- Commit statuses (Renovate reports the 14-day release age as a status)

Fine-grained tokens expire. An expired token makes Renovate fail without any
GitHub-side signal: the Dependency Dashboard simply stops updating. Check
`docker logs renovate` when it goes quiet, and rotate the token with
`./vault.sh edit` (or `./vault.sh set ... --replace`), then
`./run.sh --limit devserver`.

Workflows permission is not needed while the repository has no GitHub Actions
workflows. Store the token with `./vault.sh edit`, or with
`./vault.sh set vault_renovate_token --from-file <path> --create
--strip-final-newline` from a file holding only the token.

## Deploy

```bash
./run.sh --limit devserver
```

The first run onboards nothing, because `renovate.json` already exists. Unless
you deploy on a Saturday (Montreal time), it only builds the Dependency
Dashboard. Digest-pin and other new PRs open in the Saturday window, or at the
next run after you tick them under "Awaiting Schedule". Updates under
`stacks/auth/` and `stacks/portal/` also need their tick.
