# Per-Host Docker Compose Stacks

This directory defines repo-managed Docker Compose stacks, grouped by `inventory_hostname`. The role deploys `stacks/<host>/` to `/conf/docker/stacks/` inside the target container and starts every discovered `compose.yml` / `compose.yaml`.

## Portability Model

Stack portability is explicit. A stack being under `stacks/<host>/<stack>/` does not mean every input belongs inside the stack folder.

| Tier | Meaning | Examples | Change Style |
| --- | --- | --- | --- |
| Portable app stack | Normal application stack that can carry its Compose files, non-secret `.env.j2`, repo-only `README.md`, and non-secret `stack.yaml` beside the stack. | `stacks/servarr/notifiarr`, `stacks/servarr/kapowarr` | Small stack-local changes are allowed after stack sync deploy exclusions are in place. |
| Host-bound app stack | App stack whose runtime depends on host-local storage, GPU, VPN, external networks, or ownership mechanics. It can still have stack-local docs/metadata, but host mechanics stay in inventory. | `stacks/jellyfin/jellyfin`, `stacks/seedbox/bittorrent` | Keep host dependencies documented in stack metadata; keep deployment mechanics in host vars. |
| Foundational controlled migration | Cross-host or platform stack that other stacks depend on, or that has scripts with hardcoded repo paths. | `stacks/auth/auth`, `stacks/portal/traefik3`, `stacks/portal/dockhand`, `stacks/public/romm` OIDC coupling | Treat as a controlled migration with a dedicated plan. Do not use these as the first metadata/portability pilot. |

Foundational stacks are intentionally less portable. Authentik/OIDC has cross-host coupling, `scripts/authentik_blueprint_sync.py` depends on the current auth stack paths, and `portal_instance` controls portal discovery, Traefik KOP behavior, Hawser inclusion, and Dockhand seeding.

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
- non-secret `stack.yaml` metadata
- Compose extension blocks such as `x-prereq-dirs` and `x-managed-files`

Host/inventory-owned settings:

- `default_domain`
- `proxmox_lxc_overrides`
- `lxc_hwaddr`
- tier and capability group membership
- LXC CPU, RAM, disk, mount, and resource settings
- `lxc_docker_env_external_networks`
- `lxc_docker_env_host_directories`
- `lxc_docker_env_path_ownership_overrides`
- vault-backed secret bindings in `inventory/host_vars/*.yml`
- `portal_instance`, `traefik_kop_enabled`, Hawser, and Dockhand host orchestration

Do not dynamically include stack-local variable files into Ansible host scope. Stack metadata is non-secret role data; templates still render from normal Ansible inventory, group, host, and vault variables plus the injected `stack_name`.

- Host folder must match `inventory_hostname`.
- Stack folder name becomes the Compose project name. During `.j2` rendering, the role also injects `stack_name`.
- `.j2` files are rendered with inventory, host, group, and vault variables, then deployed without the `.j2` suffix.
- Other files are copied verbatim.
- Stack-local `README.md`, `docs/**`, `stack.yaml`, `stack.yml`, and `metadata.*` files are repo-only and are excluded from deployment.
- Do not use stack-local metadata for secrets or runtime variable injection.
- Compose-relative persistent data should live under `./appdata/...`.
- All bind-mount target directories must exist before first deploy. If they do not, Docker creates them as root on first start, causing permission errors for non-root container processes. Declare dirs that need pre-creation in an `x-prereq-dirs` block in the repo-managed compose definition for the stack; the Ansible role creates them on the LXC with docker user ownership. Use `compose.yaml` by default. If the stack intentionally preserves an upstream vendor `compose.yaml`, place `x-prereq-dirs` in `compose.override.yaml` instead. This applies to empty `./appdata/` dirs, `/ephemeral/<stack>/` paths, and new `/data/` subpaths.
- Files that must exist before container start with a specific mode can be declared in `x-managed-files`. Relative `./` paths are resolved from the deployed stack directory. This is intended for generated state files such as Traefik ACME storage that must exist with restricted permissions.
- Dirs that contain committed files do not need an `x-prereq-dirs` entry; Ansible creates them automatically when deploying the files.
- Do not use `.gitkeep`.
- If both `.env` and `.env.j2` exist for the same output path, the templated output wins.
- Hosts with no folder here are valid; they just get no repo-managed stacks.

| Path Type | Purpose | Example | Notes |
| --- | --- | --- | --- |
| `./appdata/...` | Persistent container config or state | `./appdata/jellyfin/config` | Use `x-prereq-dirs` only when the dir is otherwise empty |
| `/ephemeral/...` | Regenerable data on fast local storage | `/ephemeral/romm/resources` | Declare in `x-prereq-dirs` if the stack needs it created |
| `/data/...` | Shared external pool | `/data/media` | Only declare new subpaths in `x-prereq-dirs`; leave pre-existing paths alone |

## Stack Metadata

Portable and host-bound app stacks may include `stack.yaml` for non-secret metadata:

```yaml
schema_version: 1
kind: stack
name: notifiarr
description: Notification and automation companion
portability:
  tier: portable-app
  owner: stack
runtime:
  template_inputs:
    - docker_uid
    - docker_gid
    - default_domain
    - stack_name
  host_requirements:
    external_networks:
      - servarr-internal
    host_directories: []
    ownership_overrides: []
exposure:
  traefik: protected
  homepage_instances:
    - admin
```

Rules:

- `stack.yaml` is not copied to `/conf/docker/stacks`.
- `stack.yaml` is parsed only as `lxc_stack_sync_manifest_plan.stack_metadata`.
- `stack.yaml` must not contain secrets, vault references, API tokens, passwords, private keys, or credentials.
- `stack.yaml` does not define Ansible variables and does not override host vars.
- Host requirements listed in metadata are documentation until a future explicit aggregation design exists.

## Build a Stack

1. Create `stacks/<host>/<stack>/compose.yaml`.
2. Add `.env` or `.env.j2` if the stack needs environment variables.
3. For bind-mount target dirs that need pre-creation, add an `x-prereq-dirs` block to the repo-managed compose definition for the stack. Use `compose.yaml` by default. If you are intentionally preserving a vendor upstream base compose, put it in `compose.override.yaml` instead. Dirs that already contain committed config files need no entry.
4. Add Traefik and Homepage labels only to the user-facing service.
5. Deploy with:

```bash
ansible-playbook site.yml --limit <host>
```

To iterate on a single stack without reconciling the others:

```bash
ansible-playbook site.yml --limit <host> -e stack_filter=<stack>
```

No registration step is required; the role discovers everything under `stacks/<host>/` automatically.

## Traefik

Non-portal hosts are exposed through Traefik on `portal` via `traefik-kop`, which copies Docker labels into portal's Redis. Portal-hosted stacks use Traefik directly.

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

### Usually Leave Unlabeled

- internal databases and caches
- workers/background jobs
- internal helper APIs
- VPN support containers

### `proxy` Network

Use the external `proxy` network only when a stack explicitly needs to attach a service to the host-local shared proxy bridge:

```yaml
services:
  myapp:
    networks:
      - proxy

networks:
  proxy:
    external: true
```

Also declare the external network in host vars:

```yaml
lxc_docker_env_external_networks:
  - proxy
```

`proxy` is local to each Docker host. Portal-hosted routed services use it so Traefik can reach them directly. Non-portal Traefik labels are replicated by `traefik-kop`; that label replication does not by itself require every routed service to join `proxy`.

### Domains

Set `default_domain` per host in `inventory/host_vars/<host>.yml`. The docker-agents `.env.j2` passes it to traefik-kop as `DOMAIN`.

| Host | `default_domain` | Example |
| --- | --- | --- |
| `portal` | `faviann.com` | `media.faviann.com` |
| `seedbox` | `admin.faviann.com` | `bittorrent.admin.faviann.com` |
| `jellyfin` | `public.faviann.com` | `jellyfin.public.faviann.com` |

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

## Review Checklist

1. Exposure intent is explicit.
2. Only user-facing services carry Traefik labels.
3. Homepage labels match the intended access tier.
4. All bind-mount target dirs that need pre-creation are declared in `x-prereq-dirs` in the repo-managed compose definition for the stack. `compose.yaml` is the default location; vendor-preserving stacks may use `compose.override.yaml`. No `.gitkeep` files.
5. Any new subdomain tier also updates Traefik SANs.
6. Secrets live in vault-backed `.env.j2`, not static `.env`.
7. Stateful databases should not use floating `latest` tags; pin them and give them a realistic `stop_grace_period`.
8. Portability tier is clear: portable app, host-bound app, or foundational controlled migration.
9. Host-level deployment mechanics remain in inventory/host vars, not stack metadata.
10. Stack-local docs and `stack.yaml` contain no plaintext secrets or secret-shaped values.
11. Foundational stacks (`auth`, `portal`, Authentik/OIDC-coupled public apps) are changed only through dedicated migration plans.

## Notes

- The role discovers both `compose.yml` and `compose.yaml`.
- A host with no folder here is not an error.
