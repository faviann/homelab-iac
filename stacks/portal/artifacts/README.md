# Artifacts Stack

`artifacts` is a host-bound static server on the `portal` Docker host. It serves the
publication root written by the `publish-artifact` skill on the `workstation`, read-only, at
`https://artifacts.public.faviann.com` with no authentication, so external services can
fetch artifacts without logging in. Every published file is readable by anyone holding its
URL; the random generation segment in each URL is the only access control.

The server runs on portal rather than beside its publisher because portal binds the
workstation's publication root from the Proxmox host's `/ephemeral`, read-only and with the
same UID mapping. Portal reads it directly, so artifacts stay available while the workstation
is down, and no origin port or cross-host route is needed.

The container runs as the Docker user's UID/GID, which is the workstation user's UID, so
publications created under umask `077` stay readable without loosening their permissions.
The publication mount is `:ro`, directory listings and symlink following are disabled, and
no fallback page is configured, so a missing path returns 404 rather than an unrelated page.
The container publishes no host port; only Traefik reaches it, over the `shared` network.

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
path.

Files under any `latest/` directory are served with `Cache-Control: no-cache` instead of the
server's default `max-age=86400`, because `publish-artifact` rewrites `latest/` in place on every
republish. A browser revalidates them on each load and gets a cheap `304` when nothing changed.
Both header rules apply to a `.md` file under `latest/`, and the custom `Cache-Control` replaces
the built-in one rather than adding a second.

The server reads `appdata/config.toml` only at startup, and `docker compose up -d` does not
recreate the container when only the file changes. The deploy below handles this. Stack sync
recreates the service because it bind-mounts the file on its own (see
[Restart on Change](../../README.md#restart-on-change)).

## Publishing mapping

| Field | Value |
| --- | --- |
| `directory` | `/ephemeral/workstation/artifacts` |
| `baseUrl` | `https://artifacts.public.faviann.com` |

A relative path under the directory resolves to the identical relative path under the base
URL. This repository owns the directory, its permissions, the server, routing, and
retention. Retention is indefinite until deliberate cleanup.

The workstation user's `faviann-skills/artifacts.json` is owned by
[faviann/dotfiles](https://github.com/faviann/dotfiles) (see faviann/dotfiles#116) and must
not be written from here. Changing the mapping requires updating both owners; there is no
automatic synchronization.

## Ownership

Stack-owned:

- `compose.yaml`, including the Traefik route and its no-leak headers
- `.env.j2`
- `appdata/config.toml`
- this `README.md`
- `/ephemeral/workstation/artifacts` prereq declaration

Host-owned:

- portal's read-only `/ephemeral/workstation/artifacts` bind mount (`inventory/host_vars/portal.yml`)

## Deploy

```bash
./run.sh configure --limit portal --stack artifacts
```
