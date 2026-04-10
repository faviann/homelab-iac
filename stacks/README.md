# Per-Host Docker Compose Stacks

This directory defines repo-managed Docker Compose stacks, grouped by `inventory_hostname`. The role deploys `stacks/<host>/` to `/conf/docker/stacks/` inside the target container and starts every discovered `compose.yml` / `compose.yaml`.

Manual Dockge stacks are separate and are not managed here.

## Stack Contract

```text
stacks/
  <inventory_hostname>/
    <stack_name>/
      compose.yaml
      .env | .env.j2
      appdata/
```

- Host folder must match `inventory_hostname`.
- Stack folder name becomes the Compose project name. During `.j2` rendering, the role also injects `stack_name`.
- `.j2` files are rendered with inventory, host, group, and vault variables, then deployed without the `.j2` suffix.
- Other files are copied verbatim.
- Compose-relative persistent data should live under `./appdata/...`.
- Pre-create any `./appdata/...` directories referenced by bind mounts. If they do not exist, Docker will create them on first start with the wrong ownership.
- Use `.gitkeep` for empty directories that must exist in git.
- If both `.env` and `.env.j2` exist for the same output path, the templated output wins.
- Hosts with no folder here are valid; they just get no repo-managed stacks.

## Build a Stack

1. Create `stacks/<host>/<stack>/compose.yaml`.
2. Add `.env` or `.env.j2` if the stack needs environment variables.
3. Add `appdata/` subdirectories for any compose-relative bind mounts before first start.
4. Add Traefik and Homepage labels only to the user-facing service.
5. Deploy with:

```bash
source .ansible/venv/bin/activate
ansible-playbook site.yml --limit <host>
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
- Auth is automatic on `websecure` via `forwardAuth-authentik@file`.

So you normally should not add `entrypoints=websecure` or `tls=true`.

### Common Patterns

| Situation | Labels |
| --- | --- |
| Standard routed service | `traefik.enable=true` |
| Different domain than host default | above + `traefik.domain=<domain>` |
| Custom hostname | above + `traefik.http.routers.<name>.rule=Host(...)` |
| Ambiguous service port | above + `traefik.http.services.<name>.loadbalancer.server.port=<port>` |
| Self-auth public service | host uses `public.faviann.com`, plus public outpost routers and `public-wildcard-forwardauth` |

### Usually Leave Unlabeled

- internal databases and caches
- workers/background jobs
- internal helper APIs
- VPN support containers

### `proxy` Network

Only portal-hosted stacks that Traefik routes need the external `proxy` network:

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

### Domains

Set `default_domain` per host in `inventory/host_vars/<host>.yml`. The docker-agents `.env.j2` passes it to traefik-kop as `DOMAIN`.

| Host | `default_domain` | Example |
| --- | --- | --- |
| `portal` | `faviann.com` | `media.faviann.com` |
| `seedbox` | `admin.faviann.com` | `bittorrent.admin.faviann.com` |
| `jellyfin` | `public.faviann.com` | `jellyfin.public.faviann.com` |

When adding a new tier subdomain, also add its wildcard SAN in `stacks/portal/traefik3/appdata/traefik3/config/traefik.yaml` or TLS will fail.

## Secrets and `.env`

Use `.env.j2` whenever values come from inventory or vault.

Example:

```yaml
# inventory/host_vars/seedbox.yml
seedbox_qbit_username: "{{ vault_seedbox_qbit_username }}"
seedbox_qbit_password: "{{ vault_seedbox_qbit_password }}"
```

```jinja2
# stacks/seedbox/bittorrent/.env.j2
QBIT_USERNAME={{ seedbox_qbit_username }}
QBIT_PASSWORD={{ seedbox_qbit_password | replace('$', '$$') }}
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
```

Rules:
- never commit real secrets to static `.env`
- escape `$` as `$$` in rendered `.env` values
- prefer one source of truth: `.env` or `.env.j2`, not both

## Homepage Labels

Homepage runs three protected instances on `portal`: media, editors, and admin. Services are autodiscovered from `cap_docker` hosts through the Docker socket proxies.

| Tier | Label pattern |
| --- | --- |
| Media / visible to all signed-in users | `homepage.*` |
| Admin only | `homepage.instance.admin.*` |
| Editors + admin | `homepage.instance.editors.*` and `homepage.instance.admin.*` |

Recommended baseline labels:

| Label | Purpose |
| --- | --- |
| `homepage.group` | section |
| `homepage.name` | display name |
| `homepage.href` | canonical URL |
| `homepage.description` | short description |
| `homepage.icon` | icon |

Example:

```yaml
labels:
  - homepage.group=Media
  - homepage.name=${COMPOSE_PROJECT_NAME}
  - homepage.href=https://${HOMEPAGE_FQDN}
```

For admin-only visibility, switch the prefix to `homepage.instance.admin.`.

Keep widget labels opt-in; they often need extra secrets or internal-only URLs.

## Authentik

The catch-all provider covers `faviann.com` and its subdomains, so most routed services need no per-app Authentik object just to require login.

Create a dedicated Proxy Provider + Application when:
- access is group-restricted
- the hostname needs a non-catch-all provider
- the service is self-auth and should bypass Traefik login

Repo-specific rules:
- admin uses shared `admin-wildcard-forwardauth`
- home uses shared `home-wildcard-forwardauth`
- public self-auth services use `public.faviann.com` plus shared `public-wildcard-forwardauth`
- shared callback tiers rely on global `AUTHENTIK_COOKIE_DOMAIN=.faviann.com`

Important: auth runs at the Traefik `websecure` entrypoint. Any pre-login URL must be allowlisted in the matching provider's `Unauthenticated URLs / Paths`, including `https://<domain>/outpost.goauthentik.io/...`. Router-level empty middleware chains do not bypass entrypoint auth.

| Need | Action |
| --- | --- |
| Basic login only | none; catch-all handles it |
| Shared admin-tier login | keep `admin-wildcard-forwardauth` synced |
| Group restriction | create provider + application and bind groups |
| Self-auth public app | use `public.faviann.com` and `public-wildcard-forwardauth` |

Current non-catch-all providers: `admin-wildcard-forwardauth`, `home-wildcard-forwardauth`, and `homepage-media`.

## Docker Agents

Every `cap_docker` host gets the managed `docker-agents` stack from the role. Do not define it under `stacks/`.

Base services:
- `docker-metadata-proxy`: read-only Docker API for Homepage and discovery
- `dockwatch-socket-proxy`: write-capable proxy for Dockwatch
- `dockwatch`: container monitoring UI

Optional when `traefik_kop_enabled: true`:
- `traefik-kop`: copies Docker labels into portal's Redis for Traefik routing

Set `traefik_kop_enabled: false` on `portal`, because portal runs Traefik itself.

## Networking

| Pattern | Use |
| --- | --- |
| `proxy` external bridge | portal-hosted Traefik-routed services |
| `admin` internal bridge | docker-agents |
| `network_mode: service:<vpn>` | stacks that must share a VPN container's network namespace |

External networks must be declared in host vars before deploy:

```yaml
lxc_docker_env_external_networks:
  - proxy
```

For VPN-tunneled stacks, publish ports on the VPN container, not on the tunneled service.

## Minimal Example

```text
stacks/media/jellyfin/
├── compose.yaml
├── .env.j2
└── appdata/jellyfin/.gitkeep
```

```yaml
services:
  jellyfin:
    image: lscr.io/linuxserver/jellyfin:latest
    restart: unless-stopped
    volumes:
      - ./appdata/jellyfin:/config
      - /data/media:/data/media:ro
    labels:
      - traefik.enable=true
      - homepage.group=Media
      - homepage.name=Jellyfin
      - homepage.href=https://${HOMEPAGE_FQDN}
      - homepage.description=Media streaming server
      - homepage.icon=jellyfin
```

```jinja2
PUID=1000
PGID=1000
TZ=America/Montreal
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
```

## Review Checklist

1. Exposure intent is explicit.
2. Only user-facing services carry Traefik labels.
3. Homepage labels match the intended access tier.
4. Persistent bind-mounted data lives under `./appdata/...`, and referenced directories exist in git before first deploy.
5. Any new subdomain tier also updates Traefik SANs.
6. Secrets live in vault-backed `.env.j2`, not static `.env`.

## Notes

- Dockge is deployed separately and is not part of this directory.
- The role discovers both `compose.yml` and `compose.yaml`.
- A host with no folder here is not an error.
