# Per-Host Docker Compose Stacks

This directory contains Docker Compose stacks organized by LXC hostname.
Ansible deploys each host's stacks to `/conf/docker/stacks/` on the target container.

## Directory Structure

```
stacks/
├── portal/
│   ├── myapp/
│   │   ├── compose.yml       # Static compose file (copied as-is)
│   │   └── .env              # Static env file (copied as-is)
│   └── another-app/
│       ├── compose.yml.j2    # Templated compose (rendered with inventory vars)
│       └── .env.j2           # Templated env (rendered with inventory vars)
├── seedbox/
│   └── download-app/
│       └── compose.yml
└── README.md
```

## Conventions

- **One folder per host**: The folder name must match the `inventory_hostname`.
- **One subfolder per stack**: Each stack gets its own directory with a `compose.yml`.
- **Templating**: Files ending in `.j2` are rendered via Jinja2 (the `.j2` suffix is stripped on deploy). All inventory variables, host_vars, and vault vars are available.
- **Static files**: All other files are copied verbatim.
- **Hybrid-safe**: Stacks created manually via Dockge are never touched by Ansible. Only stacks defined here are managed.
- **Auto-started**: Every deployed `compose.yml` is automatically started with `docker compose up -d`.

## Adding a New Stack

1. Create `stacks/<hostname>/<stack-name>/compose.yml` (or `.j2` for templating).
2. Optionally add `.env` or `.env.j2` for environment variables.
3. Run `ansible-playbook site.yml --limit <hostname>` to deploy.

## Notes

- The `admin/` stack (traefik-kop, socket proxies, dockwatch) is managed separately by the `lxc_docker_environment` role and deployed only to `service_agents_enabled` hosts.
- Hosts with no directory here simply get an empty stacks folder — no error.
