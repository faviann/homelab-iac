# Multilingual Media Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Seerr → Radarr/Sonarr → Jellyfin stack to support automatic language-based routing, multilingual subtitles (EN/FR/ES), separate Jellyfin libraries per content category, and dedicated anime *arr instances.

**Architecture:** Single Seerr instance with override rules routing requests by TMDB `original_language` + genre to the correct root folder. Two Radarr instances (main + anime) and two Sonarr instances (main + anime). Bazarr downloads EN/FR/ES subtitles proactively. Jellyfin has one library per content category.

**Tech Stack:** Docker Compose (linuxserver images), Seerr v3, Radarr v6, Sonarr v4, Bazarr, Notifiarr, Jellyfin. All stacks deployed via `ansible-playbook site.yml`. SSH target: `servarr.faviann.vms`.

**Spec:** `docs/superpowers/specs/2026-04-19-multilingual-media-stack-design.md`

---

## File Map

| Action | Path |
|---|---|
| Create | `stacks/servarr/radarr-anime/compose.yaml` |
| Create | `stacks/servarr/radarr-anime/.env.j2` |
| Create | `stacks/servarr/sonarr-anime/compose.yaml` |
| Create | `stacks/servarr/sonarr-anime/.env.j2` |

All other changes are in-app UI configuration (Radarr, Sonarr, Seerr, Bazarr, Jellyfin, Notifiarr).

---

## Phase 1 — Foundation

### Task 1: Create disk folder structure on servarr

**Files:** none (remote shell commands)

- [ ] **Step 1: SSH into servarr**

```bash
ssh -l root -i .ansible/ssh/proxmox_lxc servarr.faviann.vms
```

- [ ] **Step 2: Verify current /data layout**

```bash
find /data/media -maxdepth 2 -type d 2>/dev/null || ls /data/
```

Note the current paths — you need to know where existing movies and TV content lives before migrating it in Phase 6.

- [ ] **Step 3: Create new folder structure**

```bash
mkdir -p /data/media/movies/{en,fr,foreign,anime}
mkdir -p /data/media/tv/{en,fr,asian,foreign,anime}
```

- [ ] **Step 4: Verify structure**

```bash
find /data/media -maxdepth 3 -type d
```

Expected output includes all 9 leaf directories (`movies/en`, `movies/fr`, `movies/foreign`, `movies/anime`, `tv/en`, `tv/fr`, `tv/asian`, `tv/foreign`, `tv/anime`).

- [ ] **Step 5: Exit SSH**

```bash
exit
```

---

### Task 2: Scaffold Radarr anime stack

**Files:**
- Create: `stacks/servarr/radarr-anime/compose.yaml`
- Create: `stacks/servarr/radarr-anime/.env.j2`

- [ ] **Step 1: Create compose.yaml**

```yaml
x-prereq-dirs:
  - ./appdata/radarr-anime

services:
  radarr-anime:
    image: lscr.io/linuxserver/radarr:6.1.1
    container_name: radarr-anime
    hostname: radarr-anime
    restart: unless-stopped
    environment:
      - PUID=${PUID}
      - PGID=${PGID}
      - TZ=${TZ}
    volumes:
      - ./appdata/radarr-anime:/config
      - /data:/data
    ports:
      - 7879:7878
    labels:
      traefik.enable: true
      homepage.instance.admin.group: Arr
      homepage.instance.admin.name: Radarr Anime
      homepage.instance.admin.href: https://${HOMEPAGE_FQDN}
      homepage.instance.admin.description: Anime movie management
      homepage.instance.admin.icon: radarr
    networks:
      - shared

networks:
  shared:
    name: shared
    external: true
```

- [ ] **Step 2: Create .env.j2**

```
PUID=1000
PGID=1000
TZ=America/Montreal
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
```

- [ ] **Step 3: Deploy**

```bash
ansible-playbook site.yml --limit servarr -e stack_filter=radarr-anime
```

Expected: task `Start Docker stacks` shows `changed` for `radarr-anime`.

- [ ] **Step 4: Verify container is running**

```bash
ssh -l root -i .ansible/ssh/proxmox_lxc servarr.faviann.vms "docker ps --filter name=radarr-anime --format '{{.Status}}'"
```

Expected: `Up X seconds` or similar.

- [ ] **Step 5: Commit**

```bash
git add stacks/servarr/radarr-anime/
git commit -m "feat(stacks): add radarr-anime stack"
```

---

### Task 3: Scaffold Sonarr anime stack

**Files:**
- Create: `stacks/servarr/sonarr-anime/compose.yaml`
- Create: `stacks/servarr/sonarr-anime/.env.j2`

- [ ] **Step 1: Create compose.yaml**

```yaml
x-prereq-dirs:
  - ./appdata/sonarr-anime

services:
  sonarr-anime:
    image: lscr.io/linuxserver/sonarr:4.0.17
    container_name: sonarr-anime
    hostname: sonarr-anime
    restart: unless-stopped
    environment:
      - PUID=${PUID}
      - PGID=${PGID}
      - TZ=${TZ}
    volumes:
      - ./appdata/sonarr-anime:/config
      - /data:/data
    ports:
      - 8990:8989
    labels:
      traefik.enable: true
      homepage.instance.admin.group: Arr
      homepage.instance.admin.name: Sonarr Anime
      homepage.instance.admin.href: https://${HOMEPAGE_FQDN}
      homepage.instance.admin.description: Anime series management
      homepage.instance.admin.icon: sonarr
    networks:
      - shared

networks:
  shared:
    name: shared
    external: true
```

- [ ] **Step 2: Create .env.j2**

```
PUID=1000
PGID=1000
TZ=America/Montreal
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
```

- [ ] **Step 3: Deploy**

```bash
ansible-playbook site.yml --limit servarr -e stack_filter=sonarr-anime
```

Expected: `changed` for `sonarr-anime`.

- [ ] **Step 4: Verify container is running**

```bash
ssh -l root -i .ansible/ssh/proxmox_lxc servarr.faviann.vms "docker ps --filter name=sonarr-anime --format '{{.Status}}'"
```

Expected: `Up X seconds` or similar.

- [ ] **Step 5: Commit**

```bash
git add stacks/servarr/sonarr-anime/
git commit -m "feat(stacks): add sonarr-anime stack"
```

---

## Phase 2 — *arr Configuration

> All steps in this phase are done via the web UI. Access each app via its Traefik subdomain or `http://servarr.faviann.vms:<port>`. Radarr main: 7878, Radarr anime: 7879, Sonarr main: 8989, Sonarr anime: 8990.

### Task 4: Configure Radarr main — root folders

- [ ] **Step 1: Open Radarr main → Settings → Media Management → Root Folders**

Verify the existing root folder. Note the path (e.g. `/data/media/movies` or `/data/movies`).

- [ ] **Step 2: Add root folder `/data/media/movies/en`**

Click `Add Root Folder` → path `/data/media/movies/en` → Save.

- [ ] **Step 3: Add root folder `/data/media/movies/fr`**

Click `Add Root Folder` → path `/data/media/movies/fr` → Save.

- [ ] **Step 4: Add root folder `/data/media/movies/foreign`**

Click `Add Root Folder` → path `/data/media/movies/foreign` → Save.

- [ ] **Step 5: Verify**

Settings → Media Management → Root Folders should now show at minimum: `movies/en`, `movies/fr`, `movies/foreign`. The old root folder (pre-migration) can remain until Phase 6.

---

### Task 5: Configure Sonarr main — root folders

- [ ] **Step 1: Open Sonarr main → Settings → Media Management → Root Folders**

Note the existing root folder path.

- [ ] **Step 2: Add root folder `/data/media/tv/en`**

Click `Add Root Folder` → `/data/media/tv/en` → Save.

- [ ] **Step 3: Add root folder `/data/media/tv/fr`**

Click `Add Root Folder` → `/data/media/tv/fr` → Save.

- [ ] **Step 4: Add root folder `/data/media/tv/asian`**

Click `Add Root Folder` → `/data/media/tv/asian` → Save.

- [ ] **Step 5: Add root folder `/data/media/tv/foreign`**

Click `Add Root Folder` → `/data/media/tv/foreign` → Save.

- [ ] **Step 6: Verify**

Root Folders should show: `tv/en`, `tv/fr`, `tv/asian`, `tv/foreign`.

---

### Task 6: Configure Sonarr main — Asian Drama quality profile

- [ ] **Step 1: Open Sonarr main → Settings → Profiles**

- [ ] **Step 2: Create a new profile named `Asian Drama`**

Click `Add Profile` → Name: `Asian Drama`.

- [ ] **Step 3: Set quality tiers**

Enable: `WEBDL-1080p`, `WEBRip-1080p`, `WEBDL-720p`, `WEBRip-720p`.
Disable: `Bluray-1080p`, `Remux-1080p`, `Bluray-2160p`, `Remux-2160p` (lower bitrate is acceptable).
Set cutoff to `WEBDL-1080p`.

- [ ] **Step 4: Save the profile**

- [ ] **Step 5: Verify**

Profile `Asian Drama` appears in the profiles list.

---

### Task 7: Configure Radarr anime — initial setup

> Access via `http://servarr.faviann.vms:7879`. First launch will show a setup wizard.

- [ ] **Step 1: Complete initial setup wizard**

Set authentication (use same credentials as Radarr main). Set port if asked (7878 is internal, 7879 is the host port — the app still runs on 7878 internally).

- [ ] **Step 2: Settings → Media Management → Add Root Folder**

Path: `/data/media/movies/anime` → Save.

- [ ] **Step 3: Settings → Download Clients**

Add the same download client(s) configured in Radarr main (qBittorrent, SABnzbd, etc.). Mirror the main Radarr download client config exactly.

- [ ] **Step 4: Settings → Indexers**

Add Prowlarr as indexer sync source. In Prowlarr → Settings → Apps, add Radarr anime (`http://radarr-anime:7878`, API key from Radarr anime Settings → General).

- [ ] **Step 5: Verify Prowlarr sync**

In Radarr anime → Settings → Indexers, confirm indexers appear after Prowlarr sync.

---

### Task 8: Configure Sonarr anime — initial setup

> Access via `http://servarr.faviann.vms:8990`.

- [ ] **Step 1: Complete initial setup wizard**

Set authentication matching Sonarr main.

- [ ] **Step 2: Settings → Media Management → Add Root Folder**

Path: `/data/media/tv/anime` → Save.

- [ ] **Step 3: Settings → Download Clients**

Mirror download client config from Sonarr main.

- [ ] **Step 4: Settings → Indexers — add Prowlarr sync**

In Prowlarr → Settings → Apps, add Sonarr anime (`http://sonarr-anime:8989`, API key from Sonarr anime Settings → General).

- [ ] **Step 5: Verify Prowlarr sync**

Sonarr anime → Settings → Indexers shows synced indexers.

---

### Task 9: Configure Notifiarr — extend to new instances

- [ ] **Step 1: Open Notifiarr web UI → Starr Apps**

- [ ] **Step 2: Add Radarr anime**

Click `Add Radarr` → URL: `http://radarr-anime:7878` → API key from Radarr anime Settings → General → Save.

- [ ] **Step 3: Add Sonarr anime**

Click `Add Sonarr` → URL: `http://sonarr-anime:8989` → API key from Sonarr anime Settings → General → Save.

- [ ] **Step 4: Configure TRaSH anime profile sync for Radarr anime**

In Notifiarr → TRaSH → Radarr anime: enable `Anime` profile sync. This pulls anime-specific custom formats and quality definitions.

- [ ] **Step 5: Configure TRaSH anime profile sync for Sonarr anime**

In Notifiarr → TRaSH → Sonarr anime: enable `Anime` profile sync.

- [ ] **Step 6: Trigger manual sync and verify**

Click `Sync Now` for both anime instances. In Radarr anime → Settings → Custom Formats, confirm anime-specific formats appear (e.g. `Anime Dual Audio`, `v0`, `v1`, etc.).

---

## Phase 3 — Seerr Routing

### Task 10: Configure Seerr — service profiles

> Seerr → Settings → Services. You will add multiple Radarr and Sonarr entries, each pointing to the same instance but with a different default root folder and quality profile.

- [ ] **Step 1: Update existing Radarr service entry**

Edit the current Radarr entry → set Default Root Folder to `/data/media/movies/en` → rename to `Movies – English` → Save.

- [ ] **Step 2: Add Radarr service profile for French movies**

`Add Radarr` → same URL + API key as main Radarr → Name: `Movies – French` → Default Root Folder: `/data/media/movies/fr` → Save.

- [ ] **Step 3: Add Radarr service profile for foreign movies**

`Add Radarr` → same URL + API key → Name: `Movies – Foreign` → Default Root Folder: `/data/media/movies/foreign` → Save.

- [ ] **Step 4: Add Radarr service profile for anime movies**

`Add Radarr` → Radarr anime URL + API key → Name: `Movies – Anime` → Default Root Folder: `/data/media/movies/anime` → Save.

- [ ] **Step 5: Update existing Sonarr service entry**

Edit current Sonarr entry → Default Root Folder: `/data/media/tv/en` → rename to `TV – English` → Save.

- [ ] **Step 6: Add Sonarr service profile for French TV**

`Add Sonarr` → same URL + API key as main Sonarr → Name: `TV – French` → Default Root Folder: `/data/media/tv/fr` → Save.

- [ ] **Step 7: Add Sonarr service profile for Asian Drama**

`Add Sonarr` → same URL + API key → Name: `TV – Asian Drama` → Default Root Folder: `/data/media/tv/asian` → Quality Profile: `Asian Drama` → Save.

- [ ] **Step 8: Add Sonarr service profile for foreign TV**

`Add Sonarr` → same URL + API key → Name: `TV – Foreign` → Default Root Folder: `/data/media/tv/foreign` → Save.

- [ ] **Step 9: Add Sonarr service profile for anime**

`Add Sonarr` → Sonarr anime URL + API key → Name: `TV – Anime` → Default Root Folder: `/data/media/tv/anime` → Save.

---

### Task 11: Configure Seerr — override rules

> Seerr → Settings → Services → Override Rules (or per-service override rules depending on UI version). Rules are evaluated most-specific-first. More conditions = higher priority.

- [ ] **Step 1: Add rule — Anime movies**

Conditions: Language = `ja|ko|zh`, Genre = `Animation`
Action: Use service `Movies – Anime`

- [ ] **Step 2: Add rule — Anime TV**

Conditions: Language = `ja|ko|zh`, Genre = `Animation`
Action: Use service `TV – Anime`

- [ ] **Step 3: Add rule — French movies**

Conditions: Language = `fr`
Action: Use service `Movies – French`

- [ ] **Step 4: Add rule — French TV**

Conditions: Language = `fr`
Action: Use service `TV – French`

- [ ] **Step 5: Add rule — Asian Drama TV**

Conditions: Language = `ko|ja|zh`
Action: Use service `TV – Asian Drama`

- [ ] **Step 6: Add rule — Foreign movies**

Conditions: Language = `ko|ja|zh`
Action: Use service `Movies – Foreign`

Note: This rule only applies to Radarr (movie requests). The anime rule (Step 1) has higher priority because it has two conditions (language + genre). A non-animated Korean/Japanese/Chinese movie matches this rule and lands in `movies/foreign`.

- [ ] **Step 7: Add rule — Foreign TV**

Conditions: Language = `ko|ja|zh`
Action: Use service `TV – Foreign`

Note: This rule only applies to Sonarr (TV requests). Asian Drama rule (Step 5) also matches `ko|ja|zh` for TV — both rules have one condition, so Seerr may apply either. If Seerr doesn't deduplicate automatically, remove this step and accept that non-animated Asian TV goes to `TV – Asian Drama` (an acceptable simplification).

- [ ] **Step 8: Add rule — English content**

Conditions: Language = `en`
Action: Use service `Movies – English` / `TV – English`

- [ ] **Step 9: Set default service to Foreign**

Seerr → Settings → Services → Default Movie Service: `Movies – Foreign`
Seerr → Settings → Services → Default TV Service: `TV – Foreign`

This is the catch-all: anything not matched by rules above (Italian, German, Portuguese, etc.) automatically routes to Foreign. No manual admin intervention needed for obscure languages.

- [ ] **Step 10: Verify rule priority**

Confirm the anime rules (2 conditions: language + genre) sit above single-condition rules. Seerr applies most-specific first — if manual ordering is needed, drag anime rules to the top.

Final rule evaluation order (for reference):
1. `ko|ja|zh` + Animation → Anime *(2 conditions, highest priority)*
2. `fr` → French
3. `ko|ja|zh` → Asian Drama (TV) / Foreign Movies (Movies)
4. `en` → English
5. Default service → Foreign *(catch-all)*

---

### Task 12: Configure Seerr — restrict sister's account

- [ ] **Step 1: Open Seerr → Users → find sister's account**

- [ ] **Step 2: Edit user → Services tab**

Set default Movie service to `Movies – French`.
Set default TV service to `TV – French`.

- [ ] **Step 3: Restrict visible services**

If Seerr allows hiding services per user: uncheck all non-French service profiles from her view. She should only see `Movies – French` and `TV – French`.

- [ ] **Step 4: Verify**

Log in as sister (or use "View as user" if available) → attempt a request → confirm it routes to French root folder without any service selection step.

---

## Phase 4 — Subtitles

### Task 13: Configure Bazarr — providers

> Bazarr → Settings → Providers.

- [ ] **Step 1: Add OpenSubtitles.com provider**

Click `+` → select `OpenSubtitles.com` → enter your free account username + password → Save.

Note: OpenSubtitles.com (`.com`) is the newer API-based service. Do not confuse with `OpenSubtitles.org` (the older provider).

- [ ] **Step 2: Add Subdl provider**

Click `+` → select `Subdl` → enter your Subdl API key (free at subdl.com) → Save.

- [ ] **Step 3: Verify providers are enabled and green**

Both providers should show a green status indicator. If red, recheck credentials.

---

### Task 14: Configure Bazarr — languages

> Bazarr → Settings → Languages.

- [ ] **Step 1: Set language profile for Movies**

Settings → Languages → Add profile named `All Languages`:
- Add: English (en)
- Add: French (fr)
- Add: Spanish (es)
Set each to `required: false` (download when available, don't block).

- [ ] **Step 2: Apply profile to Movies**

Settings → Languages → Default settings for Movies → select `All Languages` profile → Save.

- [ ] **Step 3: Apply profile to TV Series**

Settings → Languages → Default settings for Series → select `All Languages` profile → Save.

- [ ] **Step 4: Verify on a known item**

Pick any recently added movie in Bazarr → click `Search` manually → confirm it attempts to download EN, FR, and ES subtitles from both providers.

---

## Phase 5 — Jellyfin Libraries

### Task 15: Create new Jellyfin libraries

> Jellyfin → Dashboard → Libraries. Access via the Jellyfin Traefik subdomain.

- [ ] **Step 1: Note existing libraries**

Dashboard → Libraries → note all current library names and paths. You will be replacing/supplementing these.

- [ ] **Step 2: Add library — Movies (English)**

`Add Media Library` → Type: Movies → Name: `Movies` → Folder: `/data/media/movies/en` → Metadata language: English → Save.

- [ ] **Step 3: Add library — French Films**

`Add Media Library` → Type: Movies → Name: `French Films` → Folder: `/data/media/movies/fr` → Metadata language: **French** → Save.

- [ ] **Step 4: Add library — Foreign Films**

`Add Media Library` → Type: Movies → Name: `Foreign Films` → Folder: `/data/media/movies/foreign` → Metadata language: English → Save.

- [ ] **Step 5: Add library — Anime Movies**

`Add Media Library` → Type: Movies → Name: `Anime Movies` → Folder: `/data/media/movies/anime` → Metadata language: English → Save.

- [ ] **Step 6: Add library — TV Shows**

`Add Media Library` → Type: Shows → Name: `TV Shows` → Folder: `/data/media/tv/en` → Metadata language: English → Save.

- [ ] **Step 7: Add library — French TV**

`Add Media Library` → Type: Shows → Name: `French TV` → Folder: `/data/media/tv/fr` → Metadata language: **French** → Save.

- [ ] **Step 8: Add library — Asian Drama**

`Add Media Library` → Type: Shows → Name: `Asian Drama` → Folder: `/data/media/tv/asian` → Metadata language: English → Save.

- [ ] **Step 9: Add library — Foreign TV**

`Add Media Library` → Type: Shows → Name: `Foreign TV` → Folder: `/data/media/tv/foreign` → Metadata language: English → Save.

- [ ] **Step 10: Add library — Anime**

`Add Media Library` → Type: Shows → Name: `Anime` → Folder: `/data/media/tv/anime` → Metadata language: English → Save.

- [ ] **Step 11: Trigger library scan**

Dashboard → Libraries → `Scan All Libraries`. Confirm new libraries appear in the sidebar (they will be empty until Phase 6).

---

## Phase 6 — Media Migration

> This phase moves existing content to the new folder structure and updates *arr to track the new paths. Do this during low-usage hours. Radarr and Sonarr will briefly show items as "missing" during the move.

### Task 16: Migrate existing media files

- [ ] **Step 1: SSH into servarr**

```bash
ssh -l root -i .ansible/ssh/proxmox_lxc servarr.faviann.vms
```

- [ ] **Step 2: Identify current media paths**

```bash
ls /data/media/
```

Note the exact current folder names (e.g. `movies`, `tv`, or similar).

- [ ] **Step 3: Move English movies to new path**

```bash
mv /data/media/movies/* /data/media/movies/en/
```

If your current movies folder is at a different path (e.g. `/data/movies`), adjust accordingly.

- [ ] **Step 4: Move English TV to new path**

```bash
mv /data/media/tv/* /data/media/tv/en/
```

- [ ] **Step 5: Verify file counts match**

```bash
find /data/media/movies/en -maxdepth 1 -type d | wc -l
find /data/media/tv/en -maxdepth 1 -type d | wc -l
```

Compare against original counts (you noted these in Task 1 Step 2).

- [ ] **Step 6: Exit SSH**

```bash
exit
```

---

### Task 17: Update *arr library paths post-migration

- [ ] **Step 1: Radarr main — remove old root folder**

Settings → Media Management → Root Folders → delete the old root folder (the pre-migration path).

- [ ] **Step 2: Radarr main — trigger rescan**

Movies → select all → `Edit` → set Root Folder to `/data/media/movies/en` → Apply. Radarr will rescan and re-match all files.

Alternatively: Radarr → System → Tasks → `Rescan Movie Folders`.

- [ ] **Step 3: Verify Radarr main shows all movies as available**

Movies list → filter by `Missing` → should show 0 (or same as before migration — items that were already missing).

- [ ] **Step 4: Sonarr main — remove old root folder**

Settings → Media Management → Root Folders → delete old path.

- [ ] **Step 5: Sonarr main — trigger rescan**

Series → select all → `Edit` → set Root Folder to `/data/media/tv/en` → Apply.

- [ ] **Step 6: Verify Sonarr main shows all series as available**

Series list → filter by `Missing` → compare against pre-migration baseline.

- [ ] **Step 7: Trigger Jellyfin rescan**

Jellyfin → Dashboard → `Scan All Libraries`. Confirm `Movies` and `TV Shows` libraries now show content.

---

## End-to-End Verification

- [ ] Request a French film as sister's account in Seerr → confirm it downloads to `/data/media/movies/fr` and appears in Jellyfin `French Films` library with French title/description
- [ ] Request a Korean drama series as admin with `TV – Asian Drama` profile → lands in `/data/media/tv/asian`, appears in Jellyfin `Asian Drama` library
- [ ] Request a known anime series → routes to Sonarr anime → lands in `/data/media/tv/anime`, appears in Jellyfin `Anime` library
- [ ] Confirm Bazarr downloads EN + FR subtitles for a newly added English movie (ES may have lower availability — EN + FR is sufficient to confirm the profile is working)
- [ ] Confirm sister cannot see non-French service profiles in Seerr request UI
- [ ] Request a non-EN/FR/ES/Asian film (e.g. Italian) → lands in `/data/media/movies/foreign`, appears in `Foreign Films`
