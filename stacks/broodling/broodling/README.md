# broodling

Broodling accepts a GitHub issue URL over HTTP and dispatches the work to a
Zeroshot target that runs the coding agent and opens the pull request. This
stack is the installation that Broodling's ADR 0002 describes. It has one
Compose project with `broodling`, one target per environment
(`zeroshot-dotnet`), and `zeroshot-tls`, a Caddy proxy that terminates each
target's HTTPS origin (`https://zeroshot-dotnet.dev.faviann.com`).

Broodling's deployment guide, `deployment/README.md` in the Broodling
repository, owns the image contract, the initialization helpers,
`bootstrap-target`, `check-target`, root rotation, and target image changes.
This README covers what this repository adds.

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

Until the initialization finishes, `broodling` and `zeroshot-tls` restart and
the target stays exited.

Use the flag on an empty installation only. Each helper refuses existing
state, so a rerun on an initialized installation fails at the TLS root and
changes nothing.

If state under `/data/broodling` is lost, restore it. Do not initialize over
it, because a new TLS root and new native state do not match what the store
retains.

### Recover from a failed initialization

A first initialization that failed partway refuses to run again. Nothing in
the installation is worth keeping until one initialization succeeds. A human
resets it on the LXC and reruns the command above:

1. In `/conf/docker/stacks/broodling`, run `docker compose -p broodling down -v`.
   This also removes Caddy's data volume, which holds an intermediate signed by
   the old root.
2. Delete the contents of `/data/broodling/broodling`,
   `/data/broodling/targets/dotnet/state`, `/data/broodling/targets/dotnet/home`,
   `/data/broodling/zeroshot-tls/key`, and `/data/broodling/zeroshot-tls/root`.
   Keep the directories.

## Every deploy

After stack sync, every run installs the control token with `bootstrap-target`
and then runs `check-target`. The check runs on the LXC as root, because it
needs the Docker socket, from a copy of the pinned image's application and
runtime in `/opt/broodling/check-target/<digest>/`. Either failure fails the
run. Check mode runs neither.

## Credentials

Each credential is a file in the stack directory with its recipient's owner
and mode, as `x-managed-files` in `compose.yaml` declares. Native accepts a
token or key of exactly 64 lowercase hex characters with no newline. Ansible
keeps a template's final newline, so these templates end without one.

`GATEWAY_API_KEY` (`vault_broodling_gateway_api_key`) is a sub2api key
dedicated to Broodling, in the Claude group, with a spend quota and a model
allowlist of exactly `claude-opus-5-5`. Create it in the sub2api admin UI, so
the quota caps what agent runs can spend, the allowlist pins the model, and
revoking it affects nothing else. Every model call goes through
`https://gateway.ai.faviann.com`; nothing here uses the paid Anthropic API.

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
  bootstraps it. This includes the LXC reboot that a run makes after the
  readiness check when a package upgrade requires one.
