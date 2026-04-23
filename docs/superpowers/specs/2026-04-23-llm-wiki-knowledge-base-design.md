# LLM Wiki Knowledge Base — Design

**Date:** 2026-04-23  
**Status:** Approved  
**Pattern:** Andrej Karpathy's LLM Wiki — adapted for infrastructure + multi-project workstation

---

## Problem

Agent sessions working in this repo (and future repos) repeatedly re-derive the same knowledge: service topology, architectural decisions, past mistakes, role conventions. This costs tokens, produces inconsistent results, and loses institutional memory between sessions.

---

## Solution

A persistent, agent-maintained Obsidian vault that compiles knowledge once and keeps it current. Agents read from the vault instead of re-deriving from source files. Knowledge compounds across sessions.

---

## Architecture

### Three Layers

**Layer 1 — Raw Sources (immutable)**  
Git repos treated as read-only input. Code and config only — documentation does not live in source repos. `ServerManagementScripts` is source #1. Future repos (`.NET` projects, etc.) are added as projects inside the vault. The vault never modifies source repos.

**Layer 2 — Wiki (the vault)**  
Single private GitHub repo cloned to the workstation. Plain Obsidian markdown with YAML frontmatter and wikilinks. Project-namespaced internally:

```
vault/
├── index.md                    # Vault map — all projects, scope overview
├── conventions.md              # (added when drift appears) naming, frontmatter norms
├── _meta/
│   └── taxonomy.md             # Controlled tag vocabulary
├── projects/
│   ├── homelab/                # ServerManagementScripts knowledge
│   │   ├── services/           # One page per Docker stack
│   │   ├── hosts/              # One page per LXC
│   │   ├── adr/                # Architectural decisions
│   │   ├── mistakes/           # Incidents and fixes
│   │   └── concepts/           # Ansible roles, patterns, conventions
│   └── dotnet-app-1/           # Future .NET project (same structure)
└── .manifest.json              # Delta tracker — last SHA per project, produced pages
```

**Layer 3 — Schema (emergent)**  
No formal schema for v1. Knowledge structure emerges from sources via obsidian-wiki's ingest skill. A `conventions.md` file is added to the vault root only if inconsistency becomes visible. Page types that will naturally emerge: `service`, `host`, `adr`, `mistake`, `concept`.

---

## Tooling

**obsidian-wiki** (`github.com/Ar9av/obsidian-wiki`) — stock install.  
Installed on the workstation via `npx skills add Ar9av/obsidian-wiki`. Configured via `~/.obsidian-wiki/config` pointing to the vault clone path (set at implementation time). Global skills available from any project directory.

Key skills used:

| Skill | When |
|---|---|
| `/wiki-update` | From any source repo — ingest delta since last SHA |
| `/wiki-query` | From any session — tiered retrieval against vault |
| `/wiki-lint` | After ingest (scoped) + manual full pass |
| `/wiki-status` | Check what's been ingested, what's pending |
| `/cross-linker` | After ingest — auto-discover missing wikilinks |

---

## Three Operations

### Ingest

Triggered manually. Human-in-the-loop throughout.

1. Run `/wiki-update` from the source repo
2. Skill reads `~/.obsidian-wiki/config` → vault path
3. Reads `.manifest.json` → last ingested SHA for this project
4. Computes `git diff <last-sha>..HEAD` → only changed files
5. For each changed file: extracts knowledge, proposes wiki page creates/updates
6. Human reviews inline — approves, rejects, or clarifies per proposed change
7. Approved pages written to `projects/<project-name>/` namespace
8. `.manifest.json` updated with new SHA
9. Vault committed to git

**First ingest of `ServerManagementScripts`:**  
Treats `docs/decisions/` as raw source input — recompiles into proper `adr/` pages under `projects/homelab/`. After human approval, `docs/decisions/` is deleted from the source repo. `docs/superpowers/` is never ingested — it stays in the source repo permanently as a workflow artifact.

**Incremental ingests:**  
Delta-scoped. A commit touching two stack files produces two service page updates. Cost is proportional to what changed, not vault size.

### Query

Triggered by `/wiki-query <question>` from any project session.

Tiered retrieval protocol (obsidian-wiki built-in):
1. Read `index.md` + frontmatter scan — cheap, no page body reads
2. Section grep on candidates — medium cost
3. Full page read — last resort, top 3 candidates only
4. "Quick answer" / "just scan" flags force index-only mode

When a query synthesizes something not explicitly on any single page — a connection, a pattern, a gap — the agent flags it: *"This synthesis isn't captured anywhere — want me to add a concept page?"* The human decides. Nothing files back automatically.

### Lint

Two modes:

**Post-ingest (automatic scope):** After each ingest session, `/wiki-lint` runs on pages touched by that ingest. Checks: broken wikilinks, missing frontmatter fields, pages referencing deleted source files, contradictions with adjacent pages.

**Full vault pass (manual):** `/wiki-lint` run without scope restriction when drift is suspected. Checks: orphaned pages (no inlinks), stale pages (source file deleted or substantially changed), tag inconsistencies, schema violations if `conventions.md` exists.

Output is always a report. No automatic fixes. Human decides what to act on.

---

## Web View

**Quartz** Docker stack on the homelab infra.

- Reads from vault GitHub repo — auto-pulls on rebuild
- Full wikilink, backlink, and graph view support
- Deployed behind Traefik + Authentik (read-only, authenticated)
- Accessible from any device (phone, laptop, etc.)
- Stack lives in `stacks/<host>/homelab-wiki/compose.yaml`

Specific host, port, and domain configured at implementation time.

---

## Agent Access

**On workstation (SSH sessions):**  
Direct file reads + `/wiki-query` global skill. No Obsidian app running on workstation. No MCP server required. The vault is plain markdown — Claude Code reads and writes it as files.

**Discoverability:**  
`/wiki-query` handles discovery. No `@imports` of index pages into `CLAUDE.md` for v1 — agent queries on demand. Index `@import` reconsidered if the agent consistently misses relevant pages.

---

## Scalability

Single vault with project namespacing. Projected ceiling for this workstation:

| Scope | Est. pages |
|---|---|
| `homelab` project | 60–80 |
| Per `.NET` project | 40–60 |
| 3 `.NET` projects | 120–180 |
| **Total realistic ceiling** | **~260 pages** |

Comfortable headroom. Degradation begins around 300–400 pages (lint slowness) and 500+ pages (query quality). Natural upgrade: QMD local semantic search, already wired into obsidian-wiki — add it by setting `QMD_WIKI_COLLECTION` in `.env`. Zero design change required.

---

## Vault Hosting

- GitHub private repo (backup, accessible from any workstation)
- Local clone on workstation (path set at implementation time, convention: `~/wikis/wiki/`)
- Quartz reads from GitHub directly on rebuild

---

## What Stays in Source Repos

- `docs/superpowers/` — workflow artifacts (specs, plans). Never ingested. Permanent.
- `CLAUDE.md` / `AGENTS.md` — agent instructions. Never migrated.
- All code, config, playbooks, stacks — the repo's actual content.

---

## Deferred to v2

- `/log-mistake` skill — inline dialog-based mistake logging (inline-during-session primary, `/log-mistake` fallback)
- Formal schema / `SCHEMA.json` with required frontmatter enforcement
- QMD semantic search (upgrade when vault exceeds ~300 pages)
- Obsidian CLI (requires desktop app — incompatible with headless workstation)

---

## Implementation Notes

- Vault clone path: configured at implementation time
- Quartz host + domain: configured at implementation time
- obsidian-wiki install: `npx skills add Ar9av/obsidian-wiki` on workstation, then `bash setup.sh`
- First action after install: run `/wiki-update` from `ServerManagementScripts` — this is the `docs/decisions/` migration ingest
