# Template Files for LXC Internal Setup

This directory contains template files and folders that the `lxc_docker_environment` role copies or renders into LXC containers.

## Directory Structure

```
files/
├── dockge/               # Dockge Docker Compose configuration
│   └── compose.yml       # Copied to /shared/<hostname>/dockge/
├── docker-agents/        # Universal managed helper stack templates
│   ├── compose.yml.j2    # Base: metadata-proxy, dockwatch-socket-proxy, dockwatch
│   ├── compose.override.yaml.j2  # Override: traefik-kop (only when traefik_kop_enabled)
│   └── .env.j2           # Override env: REDISURL/DOMAIN and optional Hawser values
└── stacks/
    └── docker-agents/    # Static assets copied into the managed helper stack
        └── appdata/
            └── dockwatch/    # Persistent dockwatch config directory
```

## How It Works

### Dockge

The `dockge/` folder is copied to `/shared/<hostname>/dockge/` and started separately. Dockge provides a web UI for managing stacks and discovers all compose files under `/conf/docker/stacks/`.

### Docker Agents (Managed Stack)

The `docker-agents/` templates are rendered to `/shared/<hostname>/stacks/docker-agents/`:

- `compose.yml.j2` → `compose.yml` — **always** rendered when `docker_agents_enabled` is true.
- `compose.override.yaml.j2` → `compose.override.yaml` — rendered **only** when `traefik_kop_enabled` is true. Docker Compose automatically merges `compose.override.yaml` with `compose.yml`.
- `.env.j2` → `.env` — rendered when `traefik_kop_enabled` or `dockhand_hawser_enabled` is true. Contains the Redis URL/domain for traefik-kop and the Dockhand endpoint/token for Hawser when enabled.

Static assets from `stacks/docker-agents/` (like the dockwatch appdata directory) are copied alongside the rendered templates.

### Per-Host Stacks

Per-host stacks live in `stacks/` at the repo root (not in this directory). See `stacks/README.md` for the full guide on adding new stacks.

## File Ownership

All files copied to `/shared/<hostname>/` will be owned by the Docker user UID:GID by default.
This can be customized via the `lxc_docker_env_shared_owner` and `lxc_docker_env_shared_group` variables.

## Template Variables

Files ending in `.j2` are rendered with Jinja2. Available variables include:
- `{{ inventory_hostname }}` — Container hostname
- `{{ ansible_host }}` — Container IP/DNS
- `{{ default_domain }}` — Host's domain (from host_vars)
- `{{ homepage_docker_proxy_port }}` — Port for docker-metadata-proxy (default: 2375)
- `{{ lxc_dns_domain }}` — DNS suffix for LXC resolution
- Any other Ansible variables from inventory, group_vars, host_vars, or vault
