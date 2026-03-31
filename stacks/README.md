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

## Homepage Labels

Homepage runs on the `portal` host and autodiscovers services from every host in `cap_docker`.
Each Docker host gets a managed read-only Docker socket proxy from the `lxc_docker_environment`
role, and Homepage renders its `docker.yaml` from inventory.

For a service to appear in Homepage, define these labels on the user-facing container:

- `homepage.group` is required.
- `homepage.name` is required.
- `homepage.href` should point to the canonical public Traefik URL unless the service is intentionally internal-only.
- `homepage.description` is recommended.
- `homepage.icon` is recommended.

Do not rely on partial labels or fallback naming. If a service should be visible in Homepage,
label it intentionally.

Widgets are out of scope for the baseline stack contract. Keep `homepage.widget.*` labels opt-in
for later, since they often require extra secrets or internal-only URLs.

Example:

```yaml
services:
	myapp:
		image: ghcr.io/example/myapp:latest
		labels:
			homepage.group: Apps
			homepage.name: My App
			homepage.href: https://myapp.faviann.com
			homepage.description: Example service
			homepage.icon: myapp
```

## Notes

- The `admin/` stack (traefik-kop, socket proxies, dockwatch) is managed separately by the `lxc_docker_environment` role and deployed only to `service_agents_enabled` hosts.
- Hosts with no directory here simply get an empty stacks folder — no error.
