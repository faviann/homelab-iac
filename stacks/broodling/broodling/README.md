# broodling

Broodling accepts a GitHub issue URL over HTTP and dispatches the work to a
Zeroshot target that runs the coding agent and opens the pull request. This
stack is the installation that Broodling's
[ADR 0002](https://github.com/faviann/broodling/blob/main/docs/adr/0002-one-directtarget-per-environment-behind-one-tls-proxy.md)
describes. It has one Compose project with `broodling`, one target per
environment (`zeroshot-dotnet`), and `zeroshot-tls`, a Caddy proxy that
terminates each target's HTTPS origin (`https://zeroshot-dotnet.dev.faviann.com`).

Broodling's [deployment guide](https://github.com/faviann/broodling/blob/main/deployment/README.md)
owns the image contract, the initialization helpers, `bootstrap-target`,
`check-target`, root rotation, and target image changes. This README covers
what this repository adds.

## Reach it

- `broodling` publishes port 8080 on the LXC's private address only. Compose
  reads that address from `BROODLING_HTTP_BIND` in `.env`, which renders from
  the LXC's facts, and refuses to start without it. The API is
  unauthenticated, so the LAN is the trust boundary.
- `zeroshot-tls` publishes 443 on `127.0.0.1` only, because `check-target`
  dials that publication. The targets publish nothing.
- No Traefik route exists yet. The route, the `*.dev.faviann.com` certificate,
  and DNS are issue #354.

## Before the first deploy

1. Replace the placeholders marked `TODO(coordinator)` in
   `inventory/host_vars/broodling.yml`. They are the Broodling image and its
   source revision, and the `dotnet-r3` image and manifest digest from that
   revision's `src/Broodling/environments/dotnet-r3.adoption.json`. Copy the
   image reference byte for byte, because the catalog image must match an
   adoption bundled in the Broodling image.
2. Add the four `vault_broodling_*` keys from `inventory/vault.yml.example` with
   `./vault.sh edit`. Generate the control token and the bootstrap key as two
   different values.
3. On Firewalla, reserve an address for the MAC in `lxc_hwaddr` and name it
   `broodling.faviann.vms`.
4. Run `./inspect.sh plan --limit broodling`.

## Initialize a fresh installation

The first deploy creates the TLS root, the target's native state bound to its
origin, and the Broodling store:

```bash
./run.sh --limit broodling -- -e broodling_initialize=true > /tmp/broodling.log 2>&1
```

Stack sync starts the project first. Until the initialization finishes,
`broodling` and `zeroshot-tls` restart and the target stays exited. Then
`tasks/broodling.yml` in `config/lxc_docker_environment` runs the steps in the
order the deployment guide requires.

Use the flag on an empty installation only. Each helper refuses existing
state, so a rerun on an initialized installation fails at the TLS root and
changes nothing.

If state under `/data/broodling` is lost, restore it. Do not initialize over
it, because a new TLS root and new native state do not match what the store
retains.

### Recover from a failed initialization

A first initialization that failed partway refuses to run again. Nothing in
the installation is worth keeping until one initialization succeeds, so reset
it on the LXC and rerun the command above:

1. In `/conf/docker/stacks/broodling`, run `docker compose -p broodling down -v`.
   This also removes Caddy's data volume, which holds an intermediate signed by
   the old root.
2. Delete the contents of `/data/broodling/broodling`,
   `/data/broodling/targets/dotnet/state`, `/data/broodling/targets/dotnet/home`,
   `/data/broodling/zeroshot-tls/key`, and `/data/broodling/zeroshot-tls/root`.
   Keep the directories.

## Every deploy

After stack sync, every run that reconciles this stack does two things:

1. It runs `bootstrap-target`, which installs the control token in the target.
   A started target refuses all control until then, and every restart loses
   the token. A target that already holds the token is sent nothing.
2. It runs `check-target` on the LXC as root, because it needs the Docker
   socket that no container mounts. The run copies the application and the
   .NET runtime out of the pinned Broodling image into
   `/opt/broodling/check-target/<digest>/` once per image digest, and writes
   its configuration beside them. The configuration is the deployed catalog
   with host paths for the root certificate and the root-owned token copy.

The run fails when either command fails or the target is not ready. Check mode
runs neither.

## Credentials

| File in the stack directory | Owner, mode | Recipient |
| --- | --- | --- |
| `broodling.env` | Docker user, `0600` | `broodling` only, through `env_file`: `GH_TOKEN`, `GATEWAY_API_KEY`, and the gateway URL |
| `zeroshot-dotnet-control-token` | `1654:1654`, `0400` | `broodling`, as a Compose secret that the catalog names |
| `zeroshot-dotnet-control-token.check` | `0:0`, `0400` | `check-target` |
| `zeroshot-dotnet-bootstrap-key` | `0:0`, `0400` | the target, as a Compose secret |
| `zeroshot-dotnet-bootstrap-key.bootstrap` | `1654:1654`, `0400` | the one-off `bootstrap-target` container only |

Native accepts a token or key of exactly 64 lowercase hex characters with no
newline. Ansible keeps a template's final newline, so these templates end
without one.

## Image updates

Renovate is disabled for this stack in `renovate.json`. `check-target` requires
the exact `zeroshot-tls` image, and the Broodling and target images change only
with a Broodling release. To move to a new release, update every field under
`lxc_docker_env_stack_vars.broodling` in `inventory/host_vars/broodling.yml`
together, and follow the deployment guide's target image transition.

## Known gaps

- No `x-busy-check` protects a running agent. The nightly deploy from the
  bootstrap node can upgrade packages, restart Docker, reboot the LXC, or
  change an image, and each of these ends a run. Broodling has no idle signal
  to probe yet.
- Native agents can reach the mutating routes on `broodling:8080` until
  broodling#240.
- The target has restart policy `no`, as readiness requires. A target that
  stops outside Ansible stays stopped until the next deploy starts and
  bootstraps it.
