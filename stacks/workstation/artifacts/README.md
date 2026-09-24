# Artifacts Stack

`artifacts` is a host-bound static server on the `workstation` Docker host. It serves the
publication root written by the `publish-artifact` skill, read-only, on host port `19082`.
Portal Traefik fronts it at `https://artifacts.public.faviann.com` with no authentication, so
external services can fetch artifacts without logging in. Every published file is readable by
anyone holding its URL; the random generation segment in each URL is the only access control.

The container runs as the workstation user's UID/GID, so publications created under umask
`077` stay readable without loosening their permissions. The publication mount is `:ro`,
directory listings and symlink following are disabled, and no fallback page is configured,
so a missing path returns 404 rather than an unrelated page.

Hidden-file filtering is deliberately off (`SERVER_IGNORE_HIDDEN_FILES=false`). The
publisher groups publications by primary checkout, and a bare-repository worktree layout
produces a leading `.bare/` path component. The mapping promises that a relative path under
the root resolves to the identical relative path under the base URL, so the server must
serve dotted components. Only the publication tree is mounted, so nothing else is exposed
by this.

Markdown is served as `text/plain; charset=utf-8` instead of `text/markdown`, because web
fetchers such as ChatGPT's reject `text/markdown`. `appdata/config.toml` overrides the
`Content-Type` header for any path ending in `.md` in any letter case, and leaves every other
type to the server's own detection. The override also applies to the 404 for a missing `.md`
path. The server reads this file only at startup, and `docker compose up -d` does not recreate
the container when only the file changes, so restart the container after editing it.

## Publishing mapping

| Field | Value |
| --- | --- |
| `directory` | `/ephemeral/workstation/artifacts` |
| `baseUrl` | `https://artifacts.public.faviann.com` |

A relative path under the directory resolves to the identical relative path under the base
URL. This repository owns the directory, its permissions, the server, the origin
restriction, routing, and retention. Retention is indefinite until deliberate cleanup.

The workstation user's `faviann-skills/artifacts.json` is owned by
[faviann/dotfiles](https://github.com/faviann/dotfiles) (see faviann/dotfiles#116) and must
not be written from here. Changing the mapping requires updating both owners; there is no
automatic synchronization.

## Ownership

Stack-owned:

- `compose.yaml`
- `.env.j2`
- `appdata/config.toml`
- this `README.md`
- `/ephemeral/workstation/artifacts` prereq declaration

Host-owned:

- `workstation_origin_firewall_protected_ports` in `inventory/host_vars/workstation.yml`
- the `/ephemeral` mount
- the portal route in
  `stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml`

## Deploy

```bash
./run.sh configure --limit workstation --include-controller --stack artifacts
```
