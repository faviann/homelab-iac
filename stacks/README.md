# Per-Host Docker Compose Stacks

This directory contains Docker Compose stacks organized by LXC hostname.
Ansible deploys each host's stacks to `/conf/docker/stacks/` on the target container.

## Directory Structure

```
stacks/
├── portal/
│   ├── homepage-media/           # Homepage for media tier (media.faviann.com)
│   │   ├── compose.yaml
│   │   ├── .env
│   │   └── appdata/homepage/config/
│   │       └── docker.yaml.j2    # Templated Homepage config
│   ├── homepage-editors/         # Homepage for editors tier (home.faviann.com)
│   │   ├── compose.yaml
│   │   ├── .env
│   │   └── appdata/homepage/config/
│   ├── homepage-admin/           # Homepage for admin tier (admin.faviann.com)
│   │   ├── compose.yaml
│   │   ├── .env
│   │   └── appdata/homepage/config/
│   └── traefik3/
│       ├── compose.yaml
│       ├── .env
│       ├── secrets/
│       └── appdata/traefik3/
├── seedbox/
│   ├── bittorrent/
│   │   ├── compose.yaml
│   │   ├── .env.j2              # Templated env (rendered with inventory vars)
│   │   └── appdata/
│   └── sabnzbd/
│       ├── compose.yaml
│       └── .env
└── README.md
```

## Conventions

- **One folder per host**: The folder name must match the `inventory_hostname`.
- **One subfolder per stack**: Each stack gets its own directory with a `compose.yaml` (or `compose.yml`).
- **Templating**: Files ending in `.j2` are rendered via Jinja2 (the `.j2` suffix is stripped on deploy). All inventory variables, host_vars, group_vars, and vault vars are available.
- **Static files**: All other files are copied verbatim.
- **Hybrid-safe**: Stacks created manually via Dockge are never touched by Ansible. Only stacks defined here are managed.
- **Auto-started**: Every deployed `compose.yaml` is automatically started with `docker compose up -d`.
- **Appdata**: Persistent data volumes use `./appdata/<service>/` relative to the compose file. Use `.gitkeep` for empty directories that must exist on the controller.
- **Stack name inference**: During `.j2` rendering, Ansible injects `stack_name` derived from the stack folder name.

## Adding a New Stack

1. Create `stacks/<hostname>/<stack-name>/compose.yaml` (or `.yaml.j2` for templating).
2. Optionally add `.env` or `.env.j2` for environment variables.
3. Add `appdata/` subdirectories if the stack needs persistent volume mounts.
4. Run `ansible-playbook site.yml --limit <hostname>` to deploy.
5. Decide authentication level: if any logged-in user should access it, no Authentik action needed (catch-all covers it). If group-restricted, create a Proxy Provider + Application in Authentik, bind the required groups, and add to the outpost.

The role discovers all files under `stacks/<hostname>/` automatically — no registration needed.

---

## Traefik Integration

Services on non-portal hosts reach the internet through the **Traefik** reverse proxy running on `portal`. The mechanism is **traefik-kop**: it reads Docker labels on each host and replicates them into the portal's Redis, where Traefik picks them up.

### Traefik Discovery Contract

Treat labels as the discovery contract:

- `traefik.enable=true` on a service means Traefik should route it.
- `traefik.domain=<domain>` is optional and only needed to override the host default domain.
- No Traefik labels means no route is expected.
- Add labels only on the user-facing service container, not every sidecar or dependency.

Use this exposure decision before editing labels:

1. Is this service intentionally internet-reachable over HTTP(S)?
2. If yes, add Traefik labels to the user-facing container.
3. If no, keep it unlabeled and internal.

### Exposing a Service via Traefik

Add these labels to the user-facing container:

```yaml
services:
  myapp:
    image: example/myapp:latest
    labels:
      - traefik.enable=true
```

By default, `traefik-kop` auto-generates the hostname from the Docker Compose **project name** (i.e. the stack folder name) and the host's `default_domain` (`DOMAIN` in docker-agents `.env`):

```
Host(`<project-name>.<default_domain>`)
```

So a stack in `stacks/seedbox/bittorrent/` on host `seedbox` (`default_domain=admin.faviann.com`) becomes reachable at `bittorrent.admin.faviann.com` without adding `traefik.domain`.

Use `traefik.domain` only when a single service needs a different domain than the host default.

### Traefik Label Reference

Traefik is configured with defaults that make most labels unnecessary:

- **`websecure` is the default entrypoint** (`asDefault: true`) — never add `entrypoints=websecure`
- **TLS is automatic** on all websecure routers via entrypoint-level certResolver — never add `tls=true`
- **Auth must be added explicitly** via `forwardAuth-authentik@file` on each router — Traefik v3 entrypoint-level default middlewares cannot be bypassed per-router, so auth is opt-in per service rather than a global default
- **Hostname is auto-generated** from the compose project name and `traefik.domain` — only add an explicit `rule=Host(...)` when you need a non-default hostname

| Situation | Labels needed |
|-----------|--------------|
| Standard protected service | `traefik.enable=true` + `traefik.http.routers.<name>.middlewares=forwardAuth-authentik@file` |
| Custom hostname | above + `traefik.http.routers.<name>.rule=Host(...)` |
| Different domain than host default | above + `traefik.domain=<domain>` |
| Ambiguous port (multiple exposed) | above + `traefik.http.services.<name>.loadbalancer.server.port=<port>` |
| Public service (no auth) | `traefik.enable=true` only — omit the middleware label |

`traefik.domain` is only used by the defaultRule to build the auto-generated hostname. If you set an explicit `rule=Host(...)`, `traefik.domain` is ignored and can be omitted.

### Services That Should Usually Stay Unlabeled

Do not add Traefik labels by default to:

- Internal stateful dependencies (`postgres`, `redis`, etc.)
- Workers/background jobs with no direct user UI
- VPN-isolated workloads that are intentionally private
- Internal-only API/support services used by other containers

If one of these must become public, document the intent first and then add labels intentionally.

### When to Use the `proxy` External Network

Only stacks on the **portal** host (where Traefik runs) need to join the `proxy` external network. Non-portal hosts use traefik-kop label replication — no shared network required.

If a stack on portal needs Traefik routing, add:

```yaml
services:
  myapp:
    networks:
      - proxy
networks:
  proxy:
    external: true
```

And ensure the host's `host_vars` declares the network:

```yaml
# inventory/host_vars/portal.yml
lxc_docker_env_external_networks:
  - proxy
```

The `lxc_docker_environment` role creates these networks before starting any stacks.

### Domain Conventions

| Host | `default_domain` | Example URL |
|------|------------------|-------------|
| portal | `faviann.com` | `media.faviann.com`, `home.faviann.com`, `admin.faviann.com` |
| seedbox | `admin.faviann.com` | `bittorrent.admin.faviann.com` |

Set `default_domain` in each host's `host_vars`. The docker-agents `.env.j2` passes it to traefik-kop as `DOMAIN`.

**When adding a new tier subdomain** (e.g. `dev.faviann.com`), also add a wildcard SAN to the Traefik cert config so TLS works for all services on that subdomain:

```yaml
# stacks/portal/traefik3/appdata/traefik3/config/traefik.yaml
domains:
  - main: faviann.com
    sans:
      - "*.faviann.com"
      - "*.admin.faviann.com"
      - "*.dev.faviann.com"   # <-- add this
```

Without the SAN, services on the new subdomain will get a TLS certificate error.

### Review Checklist For New/Changed Stacks

Use this list in reviews and before merging stack changes:

1. Exposure intent is explicit (public via Traefik vs internal-only).
2. Public user-facing services include Traefik labels.
3. Internal support services are intentionally unlabeled.
4. Expected hostname follows `<stack-name>.<default_domain>` unless `traefik.domain` override is set.
5. `proxy` external network is used only for portal-hosted routed services.
6. No accidental public routes were introduced.
7. `forwardAuth-authentik@file` middleware is present on all routers that should require auth — it is **not** automatic.
8. Homepage labels match the correct access tier — see Homepage Labels section for tier/label mapping.

---

## Secrets Management

### Pattern: `.env.j2` with Vault References

Never put secrets directly in `.env` files checked into git. Instead:

1. Define secret variables in `inventory/host_vars/<hostname>.yml` that reference vault:
   ```yaml
   # inventory/host_vars/seedbox.yml
   seedbox_qbit_username: "{{ vault_seedbox_qbit_username }}"
   seedbox_qbit_password: "{{ vault_seedbox_qbit_password }}"
   ```

2. Add the actual secrets to `inventory/group_vars/all/vault.yml` (encrypted with `ansible-vault`).

3. Create a `.env.j2` template in the stack directory:
   ```
   QBIT_USERNAME={{ seedbox_qbit_username }}
   QBIT_PASSWORD={{ seedbox_qbit_password | replace('$', '$$') }}
   ```

4. The role renders the `.j2` file on deploy, producing a `.env` with real values on the target host.

### Pattern: Dynamic Homepage URL (One Variable)

Use one env var for Homepage links instead of splitting hostname/domain.

In each stack `.env.j2`:

```jinja2
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
```

- `stack_name` is injected by the role from the stack folder name (`stacks/<host>/<stack-name>/...`)
- `default_domain` comes from `inventory/host_vars/<hostname>.yml`

In `compose.yaml` labels:

```yaml
labels:
  homepage.href: https://${HOMEPAGE_FQDN}
```

That is the full pattern. No split variables required.

### Dollar-Sign Escaping

Docker Compose interprets `$` as variable interpolation. If a secret value may contain `$`, use the `replace('$', '$$')` Jinja2 filter to escape it in the rendered `.env`.

### Static `.env` vs `.env.j2`

If a stack has **both** a static `.env` and a `.env.j2`, the role prefers the templated output path and skips copying the static duplicate. To keep intent obvious, still use one or the other, never both for the same purpose. Prefer `.env.j2` when any value comes from vault or inventory.

---

## Homepage Labels

Homepage runs three instances on the `portal` host (`media`, `editors`, `admin`), each protected by Authentik. Services are autodiscovered from every host in `cap_docker` via read-only Docker socket proxies.

### Access Tiers

Each service must be labelled for the correct access tier:

| Tier | Who sees it | Label pattern |
|------|-------------|---------------|
| Media | All signed-in users | plain `homepage.*` |
| Admin | Admin only | `homepage.instance.admin.*` |
| Editors + Admin | Editors and admin | `homepage.instance.editors.*` + `homepage.instance.admin.*` |

Plain `homepage.*` labels are visible on all instances. Instance-scoped labels are visible only on the named instance.

### Required Labels

| Label | Required | Purpose |
|-------|----------|---------|
| `homepage.group` | **Yes** | Dashboard section (e.g., `Downloads`, `Media`) |
| `homepage.name` | **Yes** | Display name |
| `homepage.href` | Recommended | Canonical public URL (Traefik URL) |
| `homepage.description` | Recommended | Short description |
| `homepage.icon` | Recommended | Icon name (see Homepage icon catalogue) |

Do not rely on partial labels or fallback naming. If a service should be visible in Homepage, label it intentionally.

Widgets are out of scope for the baseline stack contract. Keep `homepage.widget.*` labels opt-in for later, since they often require extra secrets or internal-only URLs.

### Example — Media Tier (visible to all)

```yaml
labels:
  homepage.group: Media
  homepage.name: My App
  homepage.href: https://${HOMEPAGE_FQDN}
  homepage.description: Example service
  homepage.icon: myapp
```

### Example — Admin Tier (admin only)

```yaml
labels:
  homepage.instance.admin.group: Admin
  homepage.instance.admin.name: My App
  homepage.instance.admin.href: https://${HOMEPAGE_FQDN}
  homepage.instance.admin.description: Example service
  homepage.instance.admin.icon: myapp
```

And in `.env.j2` for that same stack:

```jinja2
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
```

---

## Authentik Integration

A domain-wide **`Faviann Domain`** Proxy Provider in Authentik covers `faviann.com` and all subdomains. Any service behind `forwardAuth-authentik@file` middleware gets authentication enforced automatically — no individual Authentik app registration needed just to require login.

For **group-based access restriction** (e.g., admin-only services), a dedicated Proxy Provider + Application with group bindings must be created and added to the outpost. The individual provider for that hostname takes precedence over the catch-all.

| Need | Authentik action required |
|------|--------------------------|
| Require login only | None — catch-all handles it |
| Restrict to specific group(s) | Create Proxy Provider + Application, bind groups, add to outpost |

Current per-app providers: `homepage-admin` (`admin.faviann.com`), `homepage-editors` (`home.faviann.com`), `homepage-media` (`media.faviann.com`).

---

## Docker Agents (Managed Stack)

Every `cap_docker` host automatically receives the **docker-agents** managed stack, deployed by the `lxc_docker_environment` role. You do not define this stack in `stacks/` — it is rendered from role templates.

### Base Services (always deployed when `docker_agents_enabled: true`)

| Service | Image | Purpose | Port |
|---------|-------|---------|------|
| `docker-metadata-proxy` | `tecnativa/docker-socket-proxy` | Read-only Docker API for Homepage discovery | `2375` (published) |
| `dockwatch-socket-proxy` | `tecnativa/docker-socket-proxy` | Write-capable proxy for container start/stop | internal only |
| `dockwatch` | `ghcr.io/notifiarr/dockwatch` | Container monitoring and update UI | `9999` |

These services run on an isolated `admin` bridge network, separate from user stacks.

### Override Service (when `traefik_kop_enabled: true`)

| Service | Image | Purpose |
|---------|-------|---------|
| `traefik-kop` | `ghcr.io/jittering/traefik-kop` | Replicates Docker labels to portal's Redis for Traefik routing |

This is deployed via `compose.override.yaml` — Docker Compose merges it automatically with the base `compose.yml`.

### Feature Flags

| Variable | Default | Set in | Effect |
|----------|---------|--------|--------|
| `docker_agents_enabled` | `true` | `cap_docker/vars.yml` | Deploy the entire docker-agents stack |
| `traefik_kop_enabled` | `true` | `cap_docker/vars.yml` | Deploy traefik-kop override + `.env` |

Override per-host in `host_vars`:
```yaml
# inventory/host_vars/portal.yml
traefik_kop_enabled: false   # Portal runs Traefik itself, doesn't need kop
```

### Why Two Socket Proxies?

- **docker-metadata-proxy**: Read-only (`POST=0`). Exposes container/image/network metadata for Homepage and traefik-kop. Published on port 2375 so Homepage on portal can reach it.
- **dockwatch-socket-proxy**: Write-capable (`ALLOW_START=1`, `ALLOW_STOP=1`). Needed by Dockwatch to restart containers. Never published externally.

---

## Networking Model

### Network Types Used

| Network | Type | Used by | When |
|---------|------|---------|------|
| `proxy` | External bridge | Traefik + portal services | Only on portal host |
| `admin` | Internal bridge | docker-agents services | Every cap_docker host |
| `network_mode: service:<vpn>` | Shared network namespace | VPN-tunneled stacks | When services must route through a VPN container |

### External Networks

External networks are created by the role before any stacks start. Declare them in `host_vars`:

```yaml
lxc_docker_env_external_networks:
  - proxy
```

Only declare a network if at least one stack on that host references it as `external: true`.

### VPN-Tunneled Stacks

For services that must route through a VPN (like the seedbox bittorrent stack), use `network_mode: service:<vpn-container>`:

```yaml
services:
  gluetun:
    image: qmcgaw/gluetun
    cap_add: [NET_ADMIN]
    ports:
      - 8181:8181   # qbittorrent webui (exposed via VPN container)

  qbittorrent:
    network_mode: service:gluetun   # All traffic goes through VPN
    depends_on:
      gluetun:
        condition: service_healthy
```

Ports for tunneled services are declared on the VPN container, not the service itself.

---

## Appdata Conventions

```
stacks/<hostname>/<stack-name>/
├── compose.yaml
├── .env (or .env.j2)
└── appdata/
    ├── <service-name>/          # Persistent config/data
    │   └── .gitkeep             # Empty dirs need this for git
    └── <another-service>/
```

- Mount persistent data as `./appdata/<service>:/config` (or similar) in compose.
- Use `.gitkeep` files so empty directories are tracked in git and created on the target.
- Compose-relative paths (`./appdata/...`) resolve correctly because Ansible deploys the entire stack directory structure.

---

## Complete Worked Example

Adding a `media` stack to a new Docker host:

### 1. Inventory Setup

```yaml
# inventory/hosts.yml — add to tier and capability groups
tier_medium:
  hosts:
    media:

cap_docker:
  hosts:
    media:

cap_gpu:
  hosts:
    media:
```

### 2. Host Variables

```yaml
# inventory/host_vars/media.yml
---
default_domain: admin.faviann.com

media_jellyfin_api_key: "{{ vault_media_jellyfin_api_key }}"

proxmox_lxc_overrides:
  vmid: 303
  hostname: media
  description: "Media server managed via Ansible"
  tags: [ansible, media]
```

### 3. Stack Directory

```
stacks/media/jellyfin/
├── compose.yaml
├── .env.j2
└── appdata/
    └── jellyfin/
        └── .gitkeep
```

### 4. Compose File

```yaml
# stacks/media/jellyfin/compose.yaml
services:
  jellyfin:
    image: lscr.io/linuxserver/jellyfin:latest
    container_name: jellyfin
    restart: unless-stopped
    environment:
      - PUID=${PUID}
      - PGID=${PGID}
      - TZ=${TZ}
      - JELLYFIN_PublishedServerUrl=https://jellyfin.admin.faviann.com
    ports:
      - 8096:8096
    volumes:
      - ./appdata/jellyfin:/config
      - /data/media:/data/media:ro
    labels:
      traefik.enable: "true"
      homepage.group: Media
      homepage.name: Jellyfin
      homepage.href: https://${HOMEPAGE_FQDN}
      homepage.description: Media streaming server
      homepage.icon: jellyfin
```

### 5. Environment Template

```
# stacks/media/jellyfin/.env.j2
PUID=1000
PGID=1000
TZ=America/Montreal
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
JELLYFIN_API_KEY={{ media_jellyfin_api_key }}
```

### 6. Deploy

```bash
source activate-env.sh
ansible-playbook site.yml --limit media
```

The role will:
1. Copy the stack to `/shared/media/stacks/jellyfin/` on the Proxmox host
2. Render `.env.j2` → `.env` with vault values
3. Bind-mount into the container at `/conf/docker/stacks/jellyfin/`
4. Deploy the docker-agents stack (with traefik-kop by default)
5. Run `docker compose up -d` for all stacks
6. Traefik-kop picks up the labels and registers `jellyfin.admin.faviann.com` in portal's Redis
7. Homepage discovers the service via the metadata proxy on port 2375

---

## Notes

- The `docker-agents` stack (docker-metadata-proxy, dockwatch-socket-proxy, dockwatch, and optionally traefik-kop) is managed automatically by the `lxc_docker_environment` role for every `cap_docker` host. See the **Docker Agents** section above for details.
- Hosts with no directory here simply get an empty stacks folder — no error.
- Dockge is deployed separately (from `playbooks/roles/config/lxc_docker_environment/templates/files/dockge/`) and is not part of the stacks directory.
- The role discovers compose files by globbing `compose.yml` and `compose.yaml` — both extensions work.
