# broodling

Broodling accepts a GitHub issue URL over HTTP, prepares and admits the work,
and dispatches it to a Zeroshot DirectTarget that runs the coding agent and
opens the pull request. This stack is the single supported installation from
[broodling ADR 0001](https://github.com/faviann/broodling/blob/main/docs/adr/0001-directtarget-https-origin-and-compose-topology.md):
one Compose project with `broodling`, `zeroshot` (the target) and
`zeroshot-tls` (Caddy, terminating the target's HTTPS origin
`https://zeroshot.dev.faviann.com`).

The upstream [deployment guide](https://github.com/faviann/broodling/blob/main/deployment/README.md)
owns the image contract, the initialization helpers, the readiness check,
root rotation and target image transitions. This README covers what this
repository adds: the LXC, its storage, credentials, and the supported way to
run the one-time initialization.

## Storage

All persistent state lives on `/tank/broodling` on the Proxmox host, mounted
at `/data/broodling` in the LXC in place of the fleet-wide `/tank` mount, so
this LXC sees only its own subtree. `inventory/host_vars/broodling.yml`
declares each directory the stack mounts with the ownership the upstream guide
requires and enforces it on every run. The native target's state and home are
the exception. The initialization creates them once, root-owned and private,
because native relaxes the state root's mode for its worker UIDs and used
target storage is never touched again.

The key directory reaches only `zeroshot-tls`, read-only, and the one-off root
helper. `broodling` never mounts Caddy's data. Every LXC shares one idmap, so a
mode keeps out other users, not the same UID elsewhere in the fleet, and root
in any LXC can read everything.

## Credentials

`broodling.env` is rendered from the vault at mode 0600 and given only to the
`broodling` service through `env_file`. It carries `GH_TOKEN`
(`vault_broodling_github_token`, a GitHub token with repository and
pull-request access to the repositories Broodling may work on),
`GATEWAY_API_KEY` (the shared CLIProxy client key,
`vault_overmind_cliproxy_api_key`) and the fixed gateway URL. The target
receives credentials only at dispatch, from Broodling; its environment holds
none.

Add the token before the first deploy:

```bash
./vault.sh edit   # add vault_broodling_github_token
```

## First deploy and initialization

A fresh installation needs one explicit initialization: the TLS root, the
native target state bound to the origin, and the application store. The
upstream helpers refuse non-empty state, so this never regenerates anything on
an initialized installation. Run the first deploy with it:

```bash
./run.sh --limit broodling -- -e broodling_initialize=true > /tmp/broodling.log 2>&1
```

It provisions the LXC, deploys and starts the stack, then runs
`broodling_initialize.yml` in the stack directory, in the order of the
upstream guide's initialization section: the target image's root helper
creates the TLS root, `zeroshot-tls` starts with it, native records the origin
and creates its ledger, and Broodling initializes its store.

Between the stack first starting and the root helper, `broodling` and
`zeroshot-tls` restart until their state exists and `zeroshot` stays exited.
That is the expected window of a few seconds.

The flag is for a fresh installation only. On an installation that has
initialized once, a rerun refuses at the root helper. That is the correct
outcome, and nothing is emptied. A first initialization that failed midway
refuses the same way, and removing only the root does not help, because Caddy
keeps an intermediate signed by the old root in its data directory. To run it
again, a person removes everything inside `/data/broodling/broodling`,
`/data/broodling/zeroshot/state`, `/data/broodling/zeroshot/home` and each
directory under `/data/broodling/zeroshot-tls` on the LXC, keeping those
directories. Nothing in them is worth keeping until the initialization has
succeeded once. Once Traefik holds a copy of `root.crt` (issue #354), such a
reset regenerates the root and that copy needs updating, as after a rotation.

Ordinary deploys (`./run.sh --limit broodling`) never `down` the project.
`docker compose up -d` recreates only a service whose definition changed, so a
Broodling change does not stop the target. Changing the `zeroshot` image is a
native-state transition that the upstream guide owns (installation pause,
drained execution, an established transition). `zeroshot` deliberately has no
restart policy, as upstream readiness requires, so after an LXC reboot it
starts again on the next deploy.

## Reaching it

`zeroshot-tls` publishes 8443 on the LXC (container port 443) and `broodling`
publishes 8080. Both are unauthenticated. The LAN is the trust boundary, as
for cliproxy. The Traefik routes, the `*.dev.faviann.com` certificate and DNS
are issue #354. Inside the project, `zeroshot.dev.faviann.com` resolves to
`zeroshot-tls`, and the target's agents read frozen references from the reader
at `http://broodling:8080`.

## Root rotation and readiness

Root rotation and `check-target` are human-only, documented upstream, and run
against `/conf/docker/stacks/broodling` on the LXC. After a rotation, update
Traefik's copy of `root.crt` (issue #354).
