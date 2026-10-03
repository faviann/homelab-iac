# Renovate

Self-hosted Renovate for this repository. The repository config is
[`renovate.json`](../../../renovate.json); what it does is described in
[Image Updates](../../README.md#image-updates).

## How it runs

`renovate` is a one-shot container. A deploy starts it once, because
`docker compose up -d` starts an exited container. After that, the
`renovate.timer` systemd unit on `devserver` runs it every Saturday at 05:00
with `docker start --attach renovate`, so each run's output lands in the
journal of `renovate.service`. The timer comes from `renovate_timer` in
`inventory/host_vars/devserver.yml`.

The container needs no volume. Its cache lives in the container filesystem and
survives between runs until the container is recreated.

## Token

`RENOVATE_TOKEN` comes from `vault_renovate_token`. Use a fine-grained GitHub
token scoped to `faviann/homelab-iac` with read and write access to:

- Contents
- Pull requests
- Issues (for the Dependency Dashboard)
- Commit statuses (Renovate reports the 14-day release age as a status)

Workflows permission is not needed while the repository has no GitHub Actions
workflows. Store the token with `./vault.sh edit`, or with
`./vault.sh set vault_renovate_token --from-file <path> --create
--strip-final-newline` from a file holding only the token.

## Deploy

```bash
./run.sh --limit devserver
```

The first run onboards nothing, because `renovate.json` already exists. It
opens the Dependency Dashboard issue and the first pin-digest PRs. Updates
under `stacks/auth/` and `stacks/portal/` wait for a tick on the dashboard.
