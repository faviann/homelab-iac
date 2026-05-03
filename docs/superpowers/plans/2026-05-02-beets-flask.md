# Beets-Flask Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy beets-flask on `servarr` for soundtrack imports, prove the path-safe import flow end to end, then add a separate Lidarr post-import enrichment hook.

**Architecture:** Phase 1 adds a vendor-preserving beets-flask stack under `stacks/servarr/beets-flask/` with upstream `pspitzner/beets-flask:stable`, a repo-owned override layer, shared-network access, `/data/media/_ingest/music` as the only new absolute prereq directory, and committed `/config` content under `./appdata`. Phase 2 adds a repo-managed Lidarr helper script inside the existing Lidarr config mount only after the running beets-flask instance exposes a verified enrichment API contract.

**Tech Stack:** Docker Compose, Ansible stack sync, Jinja templates, beets-flask, beets-vgmdb, Traefik, Lidarr custom scripts.

---

## Files

| Action | Path | Notes |
|--------|------|-------|
| Create | `stacks/servarr/beets-flask/compose.yaml` | Vendor-preserving base, structurally close to upstream. |
| Create | `stacks/servarr/beets-flask/compose.override.yaml` | Repo-specific mounts, labels, network, and prereq dirs. |
| Create | `stacks/servarr/beets-flask/.env.j2` | `USER_ID`, `GROUP_ID`, `TZ`, `HOMEPAGE_FQDN`, `ACOUSTID_APIKEY`, `DISCOGS_TOKEN`. |
| Create | `stacks/servarr/beets-flask/appdata/requirements.txt` | Preferred low-code install path for `beets-vgmdb`. |
| Create | `stacks/servarr/beets-flask/appdata/beets/config.yaml.j2` | Templated beets config with routing rules and secret-backed plugin settings. |
| Create | `stacks/servarr/beets-flask/appdata/beets-flask/config.yaml` | GUI inbox config and terminal start path. |
| Create only if runtime plugin install fails | `stacks/servarr/beets-flask/Dockerfile` | Fallback path; extend `pspitzner/beets-flask:stable` and install `beets-vgmdb`. |
| Modify | `inventory/host_vars/servarr.yml` | Add ingest directory with Docker ownership and add `beets-flask` stack vars. |
| Modify | `inventory/group_vars/all/vault.yml` | Add encrypted values for AcoustID and Discogs; never commit plaintext. |
| Create in phase 2 | `stacks/servarr/lidarr/appdata/lidarr/scripts/beets-post-import.sh` | Repo-managed Lidarr hook exposed inside the container as `/config/scripts/beets-post-import.sh`. |

---

### Task 1: Build the Phase 1 Stack Contract

**Files:**
- Create: `stacks/servarr/beets-flask/compose.yaml`
- Create: `stacks/servarr/beets-flask/compose.override.yaml`
- Create: `stacks/servarr/beets-flask/.env.j2`
- Create: `stacks/servarr/beets-flask/appdata/requirements.txt`
- Create only if needed: `stacks/servarr/beets-flask/Dockerfile`

- [ ] **Step 1: Create a vendor-preserving base compose file**

Keep `compose.yaml` structurally close to upstream `docker/docker-compose.yaml`: one `beets-flask` service, published `5001:5001`, upstream image name, restart policy, upstream env names `USER_ID` and `GROUP_ID`, and the same target mount structure for `/config`, inbox, and clean music directories.

- [ ] **Step 2: Put repo-specific behavior in the override layer**

Use `compose.override.yaml` for repo-owned behavior only:

```yaml
x-prereq-dirs:
  - /data/media/_ingest/music

services:
  beets-flask:
    volumes:
      - ./appdata:/config
      - /data/media/music:/data/media/music
      - /data/media/_ingest/music:/data/media/_ingest/music
    labels:
      traefik.enable: true
      traefik.http.routers.beets-flask.middlewares: protected-edge-auth@file
      homepage.instance.admin.group: Arr
      homepage.instance.admin.name: Beets Flask
      homepage.instance.admin.href: https://${HOMEPAGE_FQDN}
      homepage.instance.admin.description: Soundtrack tagging and import UI
      homepage.instance.admin.icon: mdi-music-note-plus
    networks:
      - shared
```

Use the same target mount paths as the upstream file so the override replaces the placeholder sources instead of adding unrelated mount targets.

- [ ] **Step 3: Prefer runtime plugin installation first**

Create `appdata/requirements.txt` with:

```text
beets-vgmdb
```

This is the preferred path because upstream already installs `/config/requirements.txt` on startup, which keeps the repo smaller than carrying a local image build.

- [ ] **Step 4: Keep a Dockerfile only as a fallback**

If `beets-vgmdb` does not install cleanly from `requirements.txt`, add a `Dockerfile` that extends `pspitzner/beets-flask:stable` and installs `beets-vgmdb`, then set `build:` plus a local image tag in `compose.override.yaml`.

- [ ] **Step 5: Render the environment file from inventory**

Create `.env.j2` with:

```jinja2
USER_ID={{ docker_uid }}
GROUP_ID={{ docker_gid }}
TZ=America/Montreal
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
ACOUSTID_APIKEY={{ stack_vars.acoustid_apikey | replace('$', '$$') }}
DISCOGS_TOKEN={{ stack_vars.discogs_token | replace('$', '$$') }}
```

Do not use `default()` on the required `stack_vars` values.

---

### Task 2: Add the Committed Config Tree Under `/config`

**Files:**
- Create: `stacks/servarr/beets-flask/appdata/beets/config.yaml.j2`
- Create: `stacks/servarr/beets-flask/appdata/beets-flask/config.yaml`

- [ ] **Step 1: Template the beets config instead of committing unresolved placeholders**

Create `appdata/beets/config.yaml.j2` so AcoustID and Discogs values are rendered by Ansible instead of relying on shell-style placeholders in a static YAML file.

Required fields:

```yaml
directory: /data/media/music
library: /config/beets/library.db
plugins: vgmdb chroma lastgenre discogs fetchart embedart replaygain scrub
import:
  timid: no
  incremental: yes
  move: yes
  write: yes
chroma:
  apikey: {{ stack_vars.acoustid_apikey }}
discogs:
  user_token: {{ stack_vars.discogs_token }}
```

Path routing must implement the handoff rules in this order:

1. `albumtype:soundtrack albumtype2:game` → `Soundtracks/Game/$album ($year)/$track - $title`
2. `albumtype:soundtrack` → `Soundtracks/Screen/$album ($year)/$track - $title`
3. default → `Music/$albumartist/$album ($year)/$track - $title`

- [ ] **Step 2: Add the beets-flask GUI config**

Create `appdata/beets-flask/config.yaml` with at least:

```yaml
gui:
  terminal:
    start_path: /data/media/_ingest/music
  inbox:
    folders:
      SoundtrackInbox:
        name: Soundtrack Inbox
        path: /data/media/_ingest/music
        autotag: preview
```

If phase 1 proves a different inbox mode is better, amend this file after the canary import. The important contract is that the GUI must know about `/data/media/_ingest/music` before validation starts.

- [ ] **Step 3: Keep host and container paths identical**

Do not remap music or ingest paths inside the container. `beets` stores absolute paths in `library.db`, so `/data/media/music` and `/data/media/_ingest/music` must match on both sides.

---

### Task 3: Wire Inventory and Secrets

**Files:**
- Modify: `inventory/host_vars/servarr.yml`
- Modify: `inventory/group_vars/all/vault.yml`

- [ ] **Step 1: Add the new ingest directory with explicit ownership**

Extend `lxc_docker_env_host_directories` in `inventory/host_vars/servarr.yml` with:

```yaml
  - path: /data/media/_ingest/music
    owner: "{{ docker_uid }}"
    group: "{{ docker_gid }}"
```

This avoids creating a root-owned ingest directory that the non-root beets-flask process cannot clean up.

- [ ] **Step 2: Add stack vars for beets-flask**

Extend `lxc_docker_env_stack_vars` with:

```yaml
  beets-flask:
    acoustid_apikey: "{{ vault_beets_acoustid_apikey }}"
    discogs_token: "{{ vault_beets_discogs_token }}"
```

- [ ] **Step 3: Add the encrypted vault values**

Add `vault_beets_acoustid_apikey` and `vault_beets_discogs_token` to the encrypted `inventory/group_vars/all/vault.yml`. Never place plaintext secrets in the repo or in the plan.

---

### Task 4: Deploy and Validate Phase 1 Before Touching Lidarr

**Files:**
- No new files in this task

- [ ] **Step 1: Run the narrow Ansible dry run**

After the vault values exist, run:

```bash
uv run --locked ansible-playbook site.yml --limit servarr --check -e stack_filter=beets-flask
```

- [ ] **Step 2: Deploy only the beets-flask stack**

Run:

```bash
uv run --locked ansible-playbook site.yml --limit servarr -e stack_filter=beets-flask
```

- [ ] **Step 3: Verify container startup and config layout**

Confirm all of the following before moving on:

1. The stack starts without a broken plugin install.
2. `/config/beets/config.yaml` exists in the container.
3. `/config/beets-flask/config.yaml` exists in the container.
4. The service is reachable on the published host port `5001`.
5. The protected Traefik route works.
6. The admin Homepage card appears.

- [ ] **Step 4: Discover the real enrichment API contract from the running app**

Start with `/api/docs` as the first check because that is what the handoff called out. If the running app does not expose that route, inspect the reachable API surface or upstream source before phase 2. Do not hardcode the Lidarr hook endpoint until the deployed instance proves it.

- [ ] **Step 5: Run one disposable canary import**

Use a single non-library sample folder under `/data/media/_ingest/music` to validate:

1. The GUI sees the inbox.
2. Preview generation works.
3. Import writes to `library.db`.
4. Files land in the expected `Music/` or `Soundtracks/` destination.
5. No host/container path skew appears in the database.

Bulk import stays out of scope.

---

### Task 5: Add the Lidarr Enrichment Hook as a Separate Slice

**Files:**
- Create: `stacks/servarr/lidarr/appdata/lidarr/scripts/beets-post-import.sh`

- [ ] **Step 1: Create a repo-managed Lidarr script at a stable path**

Place the helper script at `stacks/servarr/lidarr/appdata/lidarr/scripts/beets-post-import.sh` so it appears inside the Lidarr container as `/config/scripts/beets-post-import.sh` without needing container-local edits.

- [ ] **Step 2: Use the verified beets-flask API contract**

The script should call the endpoint confirmed in phase 1 over the same-LXC Docker network using the service name:

```text
http://beets-flask:5001/...
```

Do not assume the path until phase 1 validation captures it.

- [ ] **Step 3: Keep ownership boundaries intact**

The Lidarr hook must trigger metadata enrichment only. It must not ask beets to move or reorganize Lidarr-managed albums under `Music/`.

- [ ] **Step 4: Treat Lidarr UI wiring as operator configuration**

Deploy the script from the repo, but keep Lidarr UI configuration out of the repo. Document the final container script path and expected arguments for the operator.

- [ ] **Step 5: Validate with one disposable import event**

Confirm that:

1. Lidarr can execute the script.
2. The script reaches beets-flask over `shared`.
3. Failure output is visible enough to debug.
4. The hook enriches metadata without moving files.

---

## Acceptance Criteria

- [ ] The beets-flask UI is protected by `protected-edge-auth@file` and visible in the admin Homepage instance.
- [ ] `/data/media/_ingest/music` is writable by the beets-flask container user.
- [ ] One canary import proves that `library.db` stores valid absolute paths and routes files to the expected destination.
- [ ] Soundtrack routing follows the agreed rules for game soundtrack, screen soundtrack, and default music paths.
- [ ] Lidarr keeps ownership of the regular `Music/` library layout; beets only enriches metadata after import.
- [ ] Initial bulk migration remains explicitly out of scope.

## Stop Conditions

- Stop and switch to the Dockerfile fallback if `beets-vgmdb` does not install reliably from `/config/requirements.txt`.
- Stop before phase 2 if the running app does not expose a clear enrichment API contract.
- Stop and revisit ownership or `EXTRA_GROUPS` only if the canary import proves the container cannot read, delete, or move ingest files with the current UID/GID mapping.