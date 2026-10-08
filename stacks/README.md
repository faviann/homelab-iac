# Per-Host Docker Compose Stacks

This directory defines repo-managed Docker Compose stacks, grouped by `inventory_hostname`. The role deploys `stacks/<host>/` to `/conf/docker/stacks/` inside the target container and starts every discovered `compose.yml` / `compose.yaml`.

## Portability Model

Stack portability is explicit. A stack being under `stacks/<host>/<stack>/` does not mean every input belongs inside the stack folder.

| Tier | Meaning | Examples | Change Style |
| --- | --- | --- | --- |
| Portable app stack | Normal application stack that can carry its Compose files, non-secret `.env.j2`, and repo-only `README.md` beside the stack. | `stacks/servarr/notifiarr`, `stacks/servarr/kapowarr` | Small stack-local changes are allowed. |
| Host-bound app stack | App stack whose runtime depends on host-local storage, GPU, VPN, external networks, or ownership mechanics. It can still have stack-local docs, but host mechanics stay in inventory. | `stacks/jellyfin/jellyfin`, `stacks/seedbox/bittorrent` | Keep deployment mechanics in host vars. |
| Foundational controlled migration | Cross-host or platform stack that other stacks depend on, or that has scripts with hardcoded repo paths. | `stacks/auth/auth`, `stacks/portal/traefik3`, `stacks/portal/dockhand`, `stacks/public/romm` OIDC coupling | Treat as a controlled migration with a dedicated plan. |

Foundational stacks are intentionally less portable. Authentik/OIDC has cross-host coupling, `scripts/authentik_blueprint_sync.py` depends on the current auth stack paths, and `portal_instance` controls portal discovery, Traefik KOP behavior, Hawser inclusion, and Dockhand seeding.

Accepted normalization exceptions are indexed in [ADR-006](../docs/decisions/adr-006-stack-normalization-exceptions.md). Stack-local details live in each stack README.

This directory is only for repo-managed stacks that Ansible deploys and reconciles.

## Stack Contract

```text
stacks/
  <inventory_hostname>/
    <stack_name>/
      compose.yaml
      compose.override.yaml   # optional: vendor-preserving overrides
      .env | .env.j2
      appdata/
```

### Ownership Rules

Stack-owned files:

- `compose.yaml`, `compose.yml`, and optional `compose.override.yaml`
- `.env.j2` when values are rendered from inventory/vault variables
- committed app config under `appdata/`
- stack-local `README.md` and files under `docs/`
- Compose extension blocks such as `x-prereq-dirs`, `x-managed-files`, `x-busy-check`, and `x-restart-on-change`

Host/inventory-owned settings:

- `default_domain`
- `lxc_docker_env_stack_vars`
- `proxmox_lxc_overrides`
- `lxc_hwaddr`
- tier and capability group membership
- LXC CPU, RAM, disk, mount, and resource settings
- `lxc_docker_env_external_networks`
- `lxc_docker_env_host_directories`
- `lxc_docker_env_path_ownership_overrides`
- vault-backed secret bindings in `inventory/host_vars/*.yml`
- `portal_instance`, `traefik_kop_enabled`, Hawser, and Dockhand host orchestration

Do not dynamically include stack-local variable files into Ansible host scope. Templates render from normal Ansible inventory, group, host, and vault variables plus the injected `stack_name`.

- Host folder must match `inventory_hostname`.
- Stack folder name is the Compose project name. The role pins it with `docker compose -p`, so do not set a top-level `name:` in repo-owned Compose files. Vendor files may keep upstream's. During `.j2` rendering, the role also injects `stack_name`.
- `.j2` files are rendered with inventory, host, group, vault variables, `stack_name`, and the current stack `stack_vars` task-scoped render data, then deployed without the `.j2` suffix. Each template renders once; the full render context, including `item`, is in [the lxc_stack_sync README](../playbooks/roles/config/lxc_stack_sync/README.md#template-render-context).
- Other files are copied verbatim.
- Stack-local `README.md` and `docs/**` are repo-only and are excluded from deployment.
- Compose-relative persistent data should live under `./appdata/...`.
- All bind-mount target directories must exist before first deploy. If they do not, Docker creates them as root on first start, causing permission errors for non-root container processes. Declare dirs that need pre-creation in an `x-prereq-dirs` block in the repo-managed compose definition for the stack; the Ansible role creates each missing directory on the LXC with Docker user ownership and mode `0755`. This is create-if-absent behavior: once a declared directory exists, `x-prereq-dirs` does not change its mode, owner, or group. Use `compose.yaml` by default. If the stack intentionally preserves an upstream vendor `compose.yaml`, place `x-prereq-dirs` in `compose.override.yaml` instead. This applies to empty `./appdata/` dirs, `/ephemeral/<stack>/` paths, and new `/data/` subpaths.
- Files that must exist before container start with a specific mode can be declared in `x-managed-files`. Relative `./` paths are resolved from the deployed stack directory. Repository-synced files are rendered or copied directly with the declaration's mode; other declared files are created empty when absent without truncating existing content. This is intended for generated state files such as Traefik ACME storage that must exist with restricted permissions.
- Changing a synced file does not by itself restart the container that reads it. See [Restart on Change](#restart-on-change).
- Dirs that contain committed files do not need an `x-prereq-dirs` entry; Ansible creates them automatically when deploying the files.
- Do not use `.gitkeep`.
- If both `.env` and `.env.j2` exist for the same output path, the templated output wins.
- Hosts with no folder here are valid; they just get no repo-managed stacks.

| Path Type | Purpose | Example | Notes |
| --- | --- | --- | --- |
| `./appdata/...` | Persistent container config or state | `./appdata/jellyfin/config` | Use `x-prereq-dirs` only when the dir is otherwise empty |
| `/ephemeral/...` | Regenerable data on fast local storage | `/ephemeral/romm/resources` | Declare in `x-prereq-dirs` if the stack needs it created |
| `/data/...` | Shared external pool | `/data/media` | Only declare new subpaths in `x-prereq-dirs`; leave pre-existing paths alone |

## Build a Stack

1. Create `stacks/<host>/<stack>/compose.yaml`.
2. Add `.env` or `.env.j2` if the stack needs environment variables.
3. For bind-mount target dirs that need pre-creation, add an `x-prereq-dirs` block to the repo-managed compose definition for the stack. Use `compose.yaml` by default. If you are intentionally preserving a vendor upstream base compose, put it in `compose.override.yaml` instead. Dirs that already contain committed config files need no entry.
4. Add Traefik and Homepage labels only to the user-facing service.
5. Walk the Review Checklist.
6. Deploy with:

```bash
./run.sh --limit <host>
```

To iterate on a single stack without reconciling the others:

```bash
./run.sh --limit <host> --stack <stack>
```

No registration step is required; the role discovers everything under `stacks/<host>/` automatically.

## Restart on Change

`docker compose up -d` recreates a container only when its image or service
definition changes. It never sees the content of a bind-mounted file. An app
that reads a synced file only at startup keeps running the old content.

After a stack's `up -d`, stack sync recreates a single service with
`docker compose up -d --force-recreate --no-deps <service>` when one of its
tracked files was modified after the service's container last started. A
service tracks these files:

- **Every synced file it bind-mounts on its own.** No declaration is needed.
  Ansible replaces a synced file by atomic rename, and a single-file mount stays
  attached to the old inode until the container restarts. This applies
  whether or not the app would re-read the file. Mounts are matched by inode.
- **Every file declared for it in `x-restart-on-change`.** Declare a file in a
  mounted directory when the app reads it only at startup:

  ```yaml
  x-restart-on-change:
    portal-entry:
      - ./appdata/nginx/conf.d/redirect.conf
  ```

  Paths are resolved from the stack directory. Each one must be a file the
  stack syncs from the repo. An unknown service, a malformed value, a path
  outside the stack, or a path the stack does not sync fails the run before
  anything is synced, and the error names the stack and the path.

Rules:

- Never declare a file the app writes itself. Its own writes make the file newer
  than the container, so every run would recreate the service.
- Do not declare a file the app watches or hot-reloads, such as Traefik's
  `conf.d/` routers. A recreate interrupts the service for nothing.
- A service that shares another service's network namespace
  (`network_mode: service:<name>`) loses its network when that service is
  recreated alone. Do not declare files for such a provider service.

The check keeps no state, so a failed run's recreate happens on the next run, and deferred stacks and `./run.sh --check` recreate nothing.

## Image Updates

Renovate opens image update PRs against this repository on Saturdays. It runs as a service on `devserver` (`stacks/devserver/renovate/`), looping every six hours, and its repository config, including the weekly `schedule` window, is [`renovate.json`](../renovate.json). Runs outside the window still refresh the Dependency Dashboard and existing PRs, and a dashboard tick takes effect at the next run. [ADR-0016](../docs/adr/0016-use-self-hosted-renovate-for-stack-image-updates.md) records why.

- Every image reference in a stack's Compose files is tracked. A reference that contains a variable is skipped, except the vendor version pins below.
- Updates are grouped into one PR per stack folder. Majors get a separate PR per folder.
- Floating tags such as `latest` or `16-alpine` keep the tag and gain a digest (`image:tag@sha256:...`). A new digest arrives as a PR.
- Application majors open as PRs labelled `major` once the release is 14 days old. Nothing merges automatically.
- Database majors (`postgres`, `pgvector`, `mariadb`, `valkey`, `redis` in the image name) wait on the Dependency Dashboard issue, because they need a dump and restore rather than a tag change.
- Every update under `stacks/auth/` and `stacks/portal/` waits on the Dependency Dashboard. A tick there opens the PR.

**Assisted stacks.** When a stack's upgrade needs a runbook, hold its updates on the dashboard and link the runbook from the PR body. Add one rule to `renovate.json` in the same change as the runbook:

```json
{
  "description": "<stack>: upgrades follow <runbook>",
  "matchFileNames": ["stacks/<host>/<stack>/**"],
  "dependencyDashboardApproval": true,
  "prBodyNotes": ["Follow <link to runbook> before merging."]
}
```

To preview what Renovate would report from a checkout, without a token or any write:

```bash
npx --package renovate@<version in stacks/devserver/renovate/compose.yaml> renovate --platform=local --dry-run=lookup
```

It reads committed files only, so commit `renovate.json` changes first.

## Vendor Stacks

A vendor stack keeps upstream's Compose file unchanged so that an upgrade is a re-download. Immich (`stacks/public/immich`) and Authentik (`stacks/auth/auth`) are vendor stacks.

- **Marker.** The first line of `compose.yaml` is `# vendor: <upstream compose URL>`, and everything below it is upstream's file byte-for-byte. Use a versioned URL when upstream publishes one (Immich: `https://github.com/immich-app/immich/releases/download/<version>/docker-compose.yml`). Otherwise use the unversioned URL (Authentik: `https://docs.goauthentik.io/compose.yml`).
- **Pin.** The version lives in the stack's `.env.j2` (`IMMICH_VERSION`, `AUTHENTIK_TAG`), which overrides the default tag inside upstream's file. Renovate bumps it there through a regex manager in `renovate.json`.
- **Overrides.** Every local change goes in `compose.override.yaml` or `compose.override.yaml.j2`, including `x-prereq-dirs` and `x-busy-check`. Never edit the vendored file.
- **Lint.** The vendored `compose.yaml` path is listed in the exclude lists of `.ansible-lint` and `.yamllint`, because upstream formatting fails the lint gate. Renovate's `docker-compose` manager is disabled for it, so images inside it change only with upstream's file.
- **Sync.** When Renovate bumps the pin, it runs `scripts/vendor-sync.sh`. The script re-downloads the marker URL, with the new version substituted into it when the URL is versioned, and rewrites the file with the marker restored. The PR then shows upstream's Compose diff next to the pin change. To resync by hand, edit the version in the marker URL if it has one, then run:

  ```bash
  sh scripts/vendor-sync.sh stacks/<host>/<stack>/compose.yaml
  ```

A new vendor stack adds its marker, its `.env.j2` pin, a regex manager and the path in the vendored-file rule in `renovate.json`, and the two lint excludes, in one change.

## Busy Checks

A lifecycle run can interrupt a stack: `docker compose up -d` recreates changed services, Docker runtime changes or a package upgrade can restart the Docker daemon, and a reboot or host-side reconciliation restarts the LXC. A stack that runs long jobs can declare a busy check so the run leaves it alone while it reports busy.

Declare it as a top-level block in `compose.yaml`, or in `compose.override.yaml` for a vendor-preserving stack. Declare it in one file only, and never in a `.j2` template:

```yaml
x-busy-check:
  service: worker
  command: ["sh", "-c", "test ! -e /tmp/job.lock"]
  timeout: 10
```

- `service` names a service in the stack.
- `command` is a non-empty list of strings, run with `docker exec` in a running container of that service. Nothing quotes or parses it. Use `["sh", "-c", "..."]` when you need a shell, or call the app's status endpoint from a command, for example with `curl`.
- `timeout` is whole seconds, from 1 to 60.

The run rejects any other shape, a block in a `.j2` template, and a block in both the base and the override, and defers that stack as a failed check.

Before any step that could interrupt the stack, the run executes the check. Exit `0` means idle, and the run proceeds. Exit `1` means busy. Any other exit status, a timeout, a service with no running container, a Docker error, an unreachable LXC, or an invalid block counts as busy too. The check fails closed. A stack opts in with a line that starts with `x-busy-check:`. A stack without one is never parsed for a busy check, so its Compose errors fail the run as before.

A busy stack is skipped for that run. Its files are not synced or rendered, it is not brought up or recreated, and quarantine does not take it down. Its host also skips host-side reconciliation, Docker and NVIDIA runtime configuration, the package upgrade, and the reboot. Everything else still runs. The run reports each deferred stack with its reason, and `./run.sh` exits `3` when it deferred anything and nothing failed. A scheduled caller can treat `3` as "retry later". `./run.sh --interrupt-busy` skips the checks and interrupts deliberately.

A host can also declare a busy probe at the host level: a command in its `lxc_busy_check_host_command` host variable, run on the host itself with a 30-second limit. The workstation does: it is busy while an agent is mid-turn or a run holds its lifecycle lock, and [docs/bootstrap-node.md](../docs/bootstrap-node.md#the-probe) explains why. Every run against such a host defers its interrupting steps while the probe reports busy, unless `--interrupt-busy` is passed. Exit `0` means idle, `1` means busy, and any other answer defers as a failed check. The probe holds back only the host's steps above, not its stacks: a stack that must be protected declares its own check. A run that includes its own control node (`./run.sh --include-controller`) defers that host's interrupting steps without asking its probe. The run reports `<host>: busy (<reason>)`, `<host>: check failed (<reason>)`, or `<host>: run includes its own control node`.

Limits:

- A Compose project with no containers is not checked or deferred, because nothing runs that could be interrupted.
- Removing an LXC (`state: absent`) does not run checks, because removal retires the host. A rebuild stays protected.
- Check mode (`./run.sh --check`) does not run checks, so its report shows a busy stack as if it would be deployed.
- A stack removed from the repo loses its protection with its declaration, so quarantine can stop it while it is busy. To retire a protected stack without risking a running job, wait until it is idle, or remove its `x-busy-check` deliberately, before deleting it.
- A job can start between an idle answer and the interruption. That window is accepted; the check narrows it, it does not close it.

## Traefik

Some Docker hosts act as label sources for Traefik on `portal`: `traefik-kop` copies their Docker labels into portal's Redis. Stacks on the reverse-proxy host use Traefik directly.

### Discovery Contract

- `traefik.enable=true` means the service should be routed.
- No Traefik labels means the service stays internal.
- Put labels on the user-facing container, not sidecars or databases.
- `traefik.domain=<domain>` only overrides the host's `default_domain`.
- Use an explicit `traefik.http.routers.<name>.rule=Host(...)` only when you need a non-default hostname.

Default hostname:

```text
Host(`<compose-project>.<default_domain>`)
```

### Defaults You Should Not Restate

- `websecure` is the default entrypoint.
- TLS is automatic on `websecure`.

So you normally should not add `entrypoints=websecure` or `tls=true`.

### Common Patterns

| Situation | Labels |
| --- | --- |
| Standard routed service | `traefik.enable=true` |
| Protected routed service | above + `traefik.http.routers.<router>.middlewares=protected-edge-auth@file` |
| Different domain than host default | above + `traefik.domain=<domain>` |
| Custom hostname | above + `traefik.http.routers.<name>.rule=Host(...)` |
| Ambiguous service port | above + `traefik.http.services.<name>.loadbalancer.server.port=<port>` |

Public services should omit the auth middleware label. Protected tiers add it explicitly.

Port labels name the port Traefik can reach. For label-exported routes, such as routes copied by `traefik-kop` from a Docker host that is not running the reverse proxy, Traefik reaches the service through the published host port. If the service publishes `host_port:container_port` and those ports differ, set `traefik.http.services.<name>.loadbalancer.server.port` to the host port.

Example:

```yaml
services:
  myapp:
    ports:
      - 8990:8989
    labels:
      traefik.enable: true
      traefik.http.services.myapp.loadbalancer.server.port: 8990
```

### Usually Leave Unlabeled

- internal databases and caches
- workers/background jobs
- internal helper APIs
- VPN support containers

### Shared Docker Network

Use one external `shared` network when multiple stacks on the same LXC need stable Docker-network access to each other. This is host-local cross-stack plumbing; it is not a cross-LXC network.

```yaml
services:
  myapp:
    networks:
      - shared

networks:
  shared:
    external: true
```

Also declare the external network in host vars:

```yaml
lxc_docker_env_external_networks:
  - shared
```

Do not add `shared` only because a stack has Traefik labels or because `traefik-kop` exports those labels. Label-exported routes need a reachable published port; `shared` is only for same-LXC stack-to-stack traffic.

### Domains

Set `default_domain` per host in `inventory/host_vars/<host>.yml`. The docker-agents `.env.j2` passes it to traefik-kop as `DOMAIN`.

| Host | `default_domain` | Example |
| --- | --- | --- |
| `portal` | `faviann.com` | `media.faviann.com` |
| `seedbox` | `admin.faviann.com` | `bittorrent.admin.faviann.com` |
| `jellyfin` | `public.faviann.com` | `jellyfin.public.faviann.com` |

`*.ai.faviann.com` and `*.local.faviann.com` are LAN/VPN-only tiers with no Docker-label host: Firewalla overrides each wildcard to `10.1.0.2`, while public DNS sends them to the WAN through `*.faviann.com`. The name protects nothing; each router on these tiers must carry `local-ip-restriction`.

When adding a new tier subdomain, also add its wildcard SAN in `stacks/portal/traefik3/appdata/traefik3/config/traefik.yaml` or TLS will fail.

## Secrets and `.env`

→ [docs/stacks-secrets.md](../docs/stacks-secrets.md) — read when adding secrets or environment variables to a stack.

## Homepage Labels

→ [docs/stacks-homepage.md](../docs/stacks-homepage.md) — read when adding or changing Homepage visibility for a service.

## Authentik

→ [docs/stacks-authentik.md](../docs/stacks-authentik.md) — read when creating or modifying Authentik providers, applications, or auth bypass rules.

## RomM

→ [stacks/public/romm/README.md](public/romm/README.md) — read for RomM native OIDC behavior and Authentik coupling notes.

## Docker Agents

→ [docs/stacks-docker-agents.md](../docs/stacks-docker-agents.md) — read when debugging the managed docker-agents stack or changing agent configuration.

## Networking

→ [docs/stacks-networking.md](../docs/stacks-networking.md) — read when a stack needs external networks, VPN tunneling, or non-default network configuration.

## Minimal Example

```text
stacks/jellyfin/jellyfin/
├── compose.yaml
└── .env.j2
```

```yaml
x-prereq-dirs:
  - ./appdata/jellyfin

services:
  jellyfin:
    image: lscr.io/linuxserver/jellyfin:latest
    restart: unless-stopped
    container_name: jellyfin
    volumes:
      - ./appdata/jellyfin:/config
      - /data/media:/data/media:ro
    labels:
      traefik.enable: true
      homepage.group: Media
      homepage.name: Jellyfin
      homepage.href: https://${HOMEPAGE_FQDN}
      homepage.description: Media streaming server
      homepage.icon: jellyfin
```

```jinja2
PUID={{ docker_uid }}
PGID={{ docker_gid }}
TZ=America/Montreal
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
```

## Normalization Defaults

Ordinary app stacks follow these defaults. Vendor-preserving, foundational, and VPN-namespace stacks, and the exceptions in [ADR-006](../docs/decisions/adr-006-stack-normalization-exceptions.md), may differ intentionally.

| Area | Default |
| --- | --- |
| Labels | Map syntax |
| Restart | `restart: unless-stopped` |
| `container_name` | The service name, or a clearer operational name documented in the stack README |
| `hostname` | Set only when the application needs it |
| LSIO images | `PUID`/`PGID`/`TZ` environment variables and no `user:` directive |
| Other images | Keep `user:` when file ownership or application behavior needs it |
| Image tags | Keep intentional tags; pin stateful databases |

## Review Checklist

1. Exposure intent is explicit.
2. Only user-facing services carry Traefik labels.
3. Every protected router names `protected-edge-auth@file`; public and native-auth routers do not.
4. Homepage labels match the intended access tier.
5. All bind-mount target dirs that need pre-creation are declared in `x-prereq-dirs` in the repo-managed compose definition for the stack. `compose.yaml` is the default location; vendor-preserving stacks may use `compose.override.yaml`. No `.gitkeep` files.
6. Routed services are reachable: label-exported routes publish a host port and name it in the `loadbalancer.server.port` label when it differs from the container port; VPN-namespace apps publish on the VPN service.
7. External networks used in Compose are listed in the host's `lxc_docker_env_external_networks`.
8. No two bindings on the host share the same `(host_ip, port, protocol)`.
9. GPU configuration appears only on hosts with `gpu_enabled`.
10. Any new subdomain tier also updates Traefik SANs.
11. Secrets live in vault-backed `.env.j2`, not static `.env`.
12. Stateful databases should not use floating `latest` tags; pin them and give them a realistic `stop_grace_period`.
13. Portability tier is clear: portable app, host-bound app, or foundational controlled migration.
14. Stack-local docs contain no plaintext secrets or secret-shaped values.
15. Foundational stacks (`auth`, `portal`, Authentik/OIDC-coupled public apps) are changed only through dedicated migration plans, and ADR-006 exceptions keep their behavior unless the user asks to change it.
16. A stack whose jobs must not be interrupted declares one `x-busy-check` in a non-templated Compose file, and its command exits `0` only when idle and `1` only when busy.
17. A vendored `compose.yaml` is upstream byte-for-byte below its `# vendor:` marker, and every local change lives in the override file.

## Notes

- The role discovers both `compose.yml` and `compose.yaml`.
- A host with no folder here is not an error.
