# beets-flask Implementation Handoff

Execution plan: [docs/superpowers/plans/2026-05-02-beets-flask.md](docs/superpowers/plans/2026-05-02-beets-flask.md)

PRD: https://github.com/faviann/ServerManagementScripts/issues/6

## What to build

Deploy beets-flask (music tagger UI) on the `servarr` host with VGMdb plugin support. Lidarr owns regular music; beets owns soundtracks and enriches Lidarr imports.

## Architecture

Split ownership:
- **Lidarr** → `Music/` (download, organize, track regular albums — tag writing disabled)
- **beets** → `Soundtracks/` (full import/tag/organize via beets-flask UI)
- **beets** → enriches `Music/` post-import via Lidarr custom script (HTTP call, no file move)

Pipeline:
```
/data/download/{usenet,torrents}/music/  ← download clients
         ↓ manual / future automation
/data/media/_ingest/music/               ← beets-flask import source
         ↓ beets tags + moves
/data/media/music/                       ← Navidrome reads (read-only)
```

Path structure:
```
Music/$albumartist/$album ($year)/$track - $title
Soundtracks/Game/$album ($year)/$track - $title      ← OSTs + all game arrangements
Soundtracks/Screen/$album ($year)/$track - $title    ← movies + TV merged
```

Routing rules (first match wins):
1. `genre:=Game` → `Soundtracks/Game/` (VGMdb/VGMplug category `Game`)
2. `albumtype:soundtrack` → `Soundtracks/Screen/`
3. default → `Music/`

## Files to create

### `stacks/servarr/beets-flask/Dockerfile`
```dockerfile
FROM pspitzner/beets-flask:stable
RUN pip install --no-cache-dir beets-vgmdb
```

### `stacks/servarr/beets-flask/compose.yaml`
Vendor-preserving base — keep close to upstream https://github.com/pSpitzner/beets-flask/blob/main/docker/docker-compose.yaml.
Use `pspitzner/beets-flask:stable` as the image.

### `stacks/servarr/beets-flask/compose.override.yaml`
All repo additions:
- `build: context: .` + `image: beets-flask-vgmdb:local` (overrides vendor image, builds locally)
- Volumes: `./appdata/beets:/config`, `/data/media/music:/data/media/music`, `/data/media/_ingest/music:/data/media/_ingest/music`
  - **CRITICAL**: music paths must match inside/outside container — beets stores absolute paths in library.db
- `x-prereq-dirs: [/data/media/_ingest/music]`
- Traefik labels: `traefik.enable: true`, `traefik.http.routers.beets-flask.middlewares: protected-edge-auth@file`
- Homepage labels: `homepage.instance.admin.*`, group `Arr`
- Network: `shared` (external, already declared in host vars)

### `stacks/servarr/beets-flask/.env.j2`
```
USER_ID={{ docker_uid }}
GROUP_ID={{ docker_gid }}
TZ=America/Montreal
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
ACOUSTID_APIKEY={{ stack_vars.acoustid_apikey }}
DISCOGS_TOKEN={{ stack_vars.discogs_token }}
```

### `stacks/servarr/beets-flask/appdata/beets/config.yaml`
Key fields:
- `directory: /data/media/music`
- `library: /config/beets/library.db`
- plugins: `vgmdb chroma lastgenre discogs fetchart embedart replaygain scrub`
- path templates: see routing rules above
- `chroma.apikey: ${ACOUSTID_APIKEY}`
- `discogs.user_token: ${DISCOGS_TOKEN}`
- `import: timid: no, incremental: yes, move: yes, write: yes`

## Inventory changes (`inventory/host_vars/servarr.yml`)

1. Add to `lxc_docker_env_host_directories`:
   ```yaml
   - path: /data/media/_ingest/music
   ```

2. Add to `lxc_docker_env_stack_vars`:
   ```yaml
   beets-flask:
     acoustid_apikey: "{{ vault_beets_acoustid_apikey }}"
     discogs_token: "{{ vault_beets_discogs_token }}"
   ```

3. Add vault keys to `inventory/group_vars/all/vault.yml`:
   - `vault_beets_acoustid_apikey`
   - `vault_beets_discogs_token`

## Lidarr post-import script

Lidarr (same `shared` network) calls a custom script on import. Script POSTs to beets-flask API:
```
http://beets-flask:5001/api/...
```
Verify exact endpoint at `/api/docs` on the running instance. The call triggers tag enrichment only — no file moving. Script lives somewhere Lidarr can execute it (mounted volume or inline custom script connection).

## Key gotchas

- **Not a Linuxserver image** — use `USER_ID`/`GROUP_ID`, not `PUID`/`PGID`
- **Path matching** — mount music volumes with identical host:container paths
- **VGMdb game routing** — VGMplug maps VGMdb `category` to Beets `genre`; use exact `genre:=Game`. Do not use `albumtype2`; it is not emitted by VGMplug in this runtime.
- **beets config location** — vendor sets `BEETSDIR=/config/beets`; config is at `/config/beets/config.yaml` inside container → committed at `./appdata/beets/config.yaml`
- **`./appdata/beets/` needs no `x-prereq-dirs`** — Ansible auto-creates dirs with committed files

## Out of scope

- Initial bulk import (operator runs manually post-deploy: move existing library → `_ingest/`, process via beets-flask UI)
- Lidarr configuration (indexers, download client, root folder)
- Usenet/torrent client setup
