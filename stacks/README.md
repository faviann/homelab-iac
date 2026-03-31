# Per-Host Docker Compose Stacks

This directory contains Docker Compose stacks organized by LXC hostname.
Ansible deploys each host's stacks to `/conf/docker/stacks/` on the target container.

## Directory Structure

```
stacks/
├── portal/
│   ├── frontpage/
│   │   ├── compose.yaml          # Static compose file (copied as-is)
│   │   ├── .env                  # Static env file
│   │   └── appdata/homepage/config/
│   │       └── docker.yaml.j2    # Templated Homepage config
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

## Adding a New Stack

1. Create `stacks/<hostname>/<stack-name>/compose.yaml` (or `.yaml.j2` for templating).
2. Optionally add `.env` or `.env.j2` for environment variables.
3. Add `appdata/` subdirectories if the stack needs persistent volume mounts.
4. Run `ansible-playbook site.yml --limit <hostname>` to deploy.

The role discovers all files under `stacks/<hostname>/` automatically — no registration needed.

---

## Traefik Integration

Services on non-portal hosts reach the internet through the **Traefik** reverse proxy running on `portal`. The mechanism is **traefik-kop**: it reads Docker labels on each host and replicates them into the portal's Redis, where Traefik picks them up.

### Exposing a Service via Traefik

Add these labels to the user-facing container:

```yaml
services:
  myapp:
    image: example/myapp:latest
    labels:
      - traefik.enable=true
      - traefik.domain=faviann.com
```

The `traefik-kop` defaultRule auto-generates the hostname from the Docker Compose **project name** (i.e. the stack folder name) and the `traefik.domain` label:

```
Host(`<project-name>.<traefik.domain>`)
```

So a stack in `stacks/seedbox/bittorrent/` with `traefik.domain=admin.faviann.com` becomes reachable at `bittorrent.admin.faviann.com`.

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
| portal | `faviann.com` | `homepage.faviann.com` |
| seedbox | `admin.faviann.com` | `bittorrent.admin.faviann.com` |

Set `default_domain` in each host's `host_vars`. The docker-agents `.env.j2` passes it to traefik-kop as `DOMAIN`.

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

### Dollar-Sign Escaping

Docker Compose interprets `$` as variable interpolation. If a secret value may contain `$`, use the `replace('$', '$$')` Jinja2 filter to escape it in the rendered `.env`.

### Static `.env` vs `.env.j2`

If a stack has **both** a static `.env` and a `.env.j2`, the role renders the `.j2` first, then copies the static `.env` — which **overwrites** the rendered output. Use one or the other, never both for the same purpose. Prefer `.env.j2` when any value comes from vault or inventory.

---

## Homepage Labels

Homepage runs on the `portal` host and autodiscovers services from every host in `cap_docker`.
Each Docker host gets a managed read-only Docker socket proxy (port 2375) from the `lxc_docker_environment`
role, and Homepage renders its `docker.yaml` from inventory.

For a service to appear in Homepage, define these labels on the user-facing container:

| Label | Required | Purpose |
|-------|----------|---------|
| `homepage.group` | **Yes** | Dashboard section (e.g., `Downloads`, `Media`) |
| `homepage.name` | **Yes** | Display name |
| `homepage.href` | Recommended | Canonical public URL (Traefik URL) |
| `homepage.description` | Recommended | Short description |
| `homepage.icon` | Recommended | Icon name (see Homepage icon catalogue) |

Do not rely on partial labels or fallback naming. If a service should be visible in Homepage,
label it intentionally.

Widgets are out of scope for the baseline stack contract. Keep `homepage.widget.*` labels opt-in
for later, since they often require extra secrets or internal-only URLs.

### Example with Traefik + Homepage Labels

```yaml
services:
  myapp:
    image: ghcr.io/example/myapp:latest
    labels:
      # Traefik routing
      traefik.enable: "true"
      traefik.domain: faviann.com
      # Homepage discovery
      homepage.group: Apps
      homepage.name: My App
      homepage.href: https://myapp.faviann.com
      homepage.description: Example service
      homepage.icon: myapp
```

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
      traefik.domain: admin.faviann.com
      homepage.group: Media
      homepage.name: Jellyfin
      homepage.href: https://jellyfin.admin.faviann.com
      homepage.description: Media streaming server
      homepage.icon: jellyfin
```

### 5. Environment Template

```
# stacks/media/jellyfin/.env.j2
PUID=1000
PGID=1000
TZ=America/Montreal
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
