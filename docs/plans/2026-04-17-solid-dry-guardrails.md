# SOLID/DRY Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SOLID/DRY design principles to AGENTS.md and write four ADRs for the roles most frequently re-litigated in this codebase.

**Architecture:** Expand the existing "Role Design Principles" section in AGENTS.md with Ansible-specific SOLID/DRY rules and a refactoring gate. Create `docs/decisions/` with one ADR per hot role, each capturing the design decision that ends the refactoring loop for that role.

**Tech Stack:** Markdown, git

---

## Files

| Action | Path |
|--------|------|
| Modify | `AGENTS.md` — expand "Role Design Principles" with SOLID/DRY block + refactoring gate |
| Create | `docs/decisions/ADR-001-lxc-spec-builder-desired-state.md` |
| Create | `docs/decisions/ADR-002-proxmox-lxc-lifecycle-compile-decide-split.md` |
| Create | `docs/decisions/ADR-003-proxmox-lxc-host-config-config-file-vs-features.md` |
| Create | `docs/decisions/ADR-004-lxc-docker-environment-vs-lxc-stack-sync-boundary.md` |

---

### Task 1: Expand AGENTS.md Role Design Principles

**Files:**
- Modify: `AGENTS.md:68-72`

- [ ] **Step 1: Replace the existing "Role Design Principles" section**

The current section (lines 68–72) reads:

```markdown
## Role Design Principles

- One role = one concern; use `meta/main.yml` for dependencies
- Use feature flags (`docker_enabled`) not group checks (`'cap_docker' in group_names`)
- Avoid hardcoded values; inject via vars. Ensure idempotency; use `assert` to fail fast
```

Replace it entirely with:

```markdown
## Role Design Principles

- One role = one concern; use `meta/main.yml` for dependencies
- Use feature flags (`docker_enabled`) not group checks (`'cap_docker' in group_names`)
- Avoid hardcoded values; inject via vars. Ensure idempotency; use `assert` to fail fast

### SOLID/DRY in Ansible

**Single Responsibility (SRP)**: A role does one thing — provision, configure, or orchestrate. If a role has tasks that both decide AND act, that is a violation.

**Open/Closed (OCP)**: Extend behavior through variables and feature flags, not by editing task logic. Adding a capability = new var + new `when:` block, not modifying existing tasks.

**Interface Segregation (ISP)**: Every role that accepts external input has an `argument_specs.yml`. Roles expose only the vars they need — no catch-all dicts bundling unrelated config.

**Dependency Inversion (DI)**: Roles depend on declared variables (the contract), not on sibling role internals or specific host facts baked into logic.

**DRY**: One place computes a fact; consumers read the registered var. No duplicated task blocks across roles. Defaults live in `defaults/main.yml`, not re-stated in `group_vars`.

### Refactoring Gate

Before starting a refactor, state in the commit message or in conversation which principle it serves and what "done" looks like. If a refactor intentionally breaks a principle, write an ADR in `docs/decisions/` that names the exception explicitly.

→ [docs/decisions/](docs/decisions/) — ADRs for key role design decisions; read before modifying a role that has one.
```

- [ ] **Step 2: Verify the section reads correctly**

```bash
grep -A 30 "^## Role Design Principles" AGENTS.md
```

Expected: the full expanded section with SOLID/DRY block and Refactoring Gate visible.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs(agents): add SOLID/DRY principles and refactoring gate"
```

---

### Task 2: Write ADR-001 — lxc_spec_builder owns desired state

**Files:**
- Create: `docs/decisions/ADR-001-lxc-spec-builder-desired-state.md`

- [ ] **Step 1: Create the ADR**

```markdown
# ADR-001: lxc_spec_builder Owns Desired State, Nothing Else

- **Date**: 2026-04-17
- **Status**: Accepted

## Context

`lxc_spec_builder` has been refactored repeatedly because its boundary kept shifting —
sometimes it validated inputs, sometimes it published facts for downstream roles, sometimes
it merged tier defaults inline. Without a clear statement of ownership, each pass added or
removed responsibilities. It is 298 lines and the single most-touched file across 40 unpushed
commits.

## Decision

`lxc_spec_builder` computes the full desired LXC spec from tier defaults + host vars and
registers it as `lxc_spec`. It does not apply, validate against live state, or provision
anything. All callers consume `lxc_spec`; no caller reads the role's internal vars directly.

## Principle

SRP — one role, one concern: compute the desired state.

## Consequences

**Easier:** Test spec computation in isolation by setting input vars and asserting `lxc_spec`.
Add new spec fields without touching provisioning logic. Reason about the role by reading one
file.

**Harder:** Short-circuit spec computation for a one-off host requires adding a conditional
rather than bypassing the role.

## Deviation Conditions

Spec shape must be computed inline for a one-off host with no generalizable pattern. Requires
a superseding ADR.
```

- [ ] **Step 2: Verify the file exists and renders**

```bash
cat docs/decisions/ADR-001-lxc-spec-builder-desired-state.md
```

Expected: full ADR content with all sections present.

- [ ] **Step 3: Commit**

```bash
git add docs/decisions/ADR-001-lxc-spec-builder-desired-state.md
git commit -m "docs(adr): ADR-001 lxc_spec_builder owns desired state"
```

---

### Task 3: Write ADR-002 — proxmox_lxc_lifecycle compile/decide split

**Files:**
- Create: `docs/decisions/ADR-002-proxmox-lxc-lifecycle-compile-decide-split.md`

- [ ] **Step 1: Create the ADR**

```markdown
# ADR-002: proxmox_lxc_lifecycle compile/decide Split

- **Date**: 2026-04-17
- **Status**: Accepted

## Context

The lifecycle role decides whether to provision, skip, or restart a container. This logic was
repeatedly folded into and extracted from fact-gathering, making the decision hard to test and
the facts hard to reuse. `decide.yml` and `compile.yml` were each touched 5 times across the
branch.

## Decision

`compile.yml` assembles all facts needed to make a lifecycle decision (current container state,
desired spec, diff between them). `decide.yml` reads those facts and sets `lifecycle_action`
to one of: `provision`, `skip`, or `restart`. The two files do not overlap — `compile.yml`
never sets `lifecycle_action`; `decide.yml` never reads live Proxmox state directly.

## Principle

SRP — fact assembly and decision logic are separate concerns with separate testability.

## Consequences

**Easier:** Unit-test the decision matrix by setting compiled facts directly and asserting
`lifecycle_action`. Add new facts to compilation without touching decision logic. Read each
file independently.

**Harder:** Short-circuiting compilation when the decision is obvious requires an explicit
early-exit task rather than collapsing the two steps.

## Deviation Conditions

The decision is trivially derivable from a single fact with no branching. Requires a
superseding ADR.
```

- [ ] **Step 2: Verify the file exists and renders**

```bash
cat docs/decisions/ADR-002-proxmox-lxc-lifecycle-compile-decide-split.md
```

Expected: full ADR content with all sections present.

- [ ] **Step 3: Commit**

```bash
git add docs/decisions/ADR-002-proxmox-lxc-lifecycle-compile-decide-split.md
git commit -m "docs(adr): ADR-002 proxmox_lxc_lifecycle compile/decide split"
```

---

### Task 4: Write ADR-003 — proxmox_lxc_host_config config_file vs features split

**Files:**
- Create: `docs/decisions/ADR-003-proxmox-lxc-host-config-config-file-vs-features.md`

- [ ] **Step 1: Create the ADR**

```markdown
# ADR-003: proxmox_lxc_host_config config_file vs features Split

- **Date**: 2026-04-17
- **Status**: Accepted

## Context

`proxmox_lxc_host_config` applies settings that require running `pct` directly on the Proxmox
host (bypassing the API). Two categories of settings kept getting mixed together: pct config
file entries (bind mounts, idmap, sysctls, nvidia) and privileged capability flags (nesting,
keyctl, wireguard). `main.yml` and `features.yml` were the two hottest files in the repo,
touched 8 and 6 times respectively.

## Decision

`config_file*.yml` files handle pct config file entries — each maps to a line or block in the
container's config file and is idempotent by reading and diffing the file. `features.yml`
handles privileged capability flags applied via `pct set --features` and is idempotent by
reading `pct config`. They are kept in separate task files because they have different
idempotency mechanisms.

## Principle

SRP — different idempotency mechanisms signal different responsibilities.

## Consequences

**Easier:** Add a new config file entry (e.g., a new bind mount type) without risking feature
flag logic. Audit all privileged capabilities granted to containers in one file.

**Harder:** Apply a setting that is simultaneously a config entry and a feature flag requires
touching both files.

## Deviation Conditions

A new capability is both a config entry and a feature flag simultaneously. Requires a
superseding ADR.
```

- [ ] **Step 2: Verify the file exists and renders**

```bash
cat docs/decisions/ADR-003-proxmox-lxc-host-config-config-file-vs-features.md
```

Expected: full ADR content with all sections present.

- [ ] **Step 3: Commit**

```bash
git add docs/decisions/ADR-003-proxmox-lxc-host-config-config-file-vs-features.md
git commit -m "docs(adr): ADR-003 proxmox_lxc_host_config config_file vs features split"
```

---

### Task 5: Write ADR-004 — lxc_docker_environment vs lxc_stack_sync boundary

**Files:**
- Create: `docs/decisions/ADR-004-lxc-docker-environment-vs-lxc-stack-sync-boundary.md`

- [ ] **Step 1: Create the ADR**

```markdown
# ADR-004: lxc_docker_environment vs lxc_stack_sync Boundary

- **Date**: 2026-04-17
- **Status**: Accepted

## Context

The boundary between environment setup and stack lifecycle kept shifting. Tasks for writing env
files, managed assets, and README templates were mixed with tasks for discovering stacks,
starting compose, and quarantining stale containers. `managed_assets.yml` was touched 7 times;
`lxc_stack_sync` tasks collectively 4+ times. A god-role that owns both "what files exist" and
"what containers run" has no clear stopping point for refactoring.

## Decision

`lxc_docker_environment` owns runtime config: managed asset files, env files, and templates
that must exist on disk before containers start. `lxc_stack_sync` owns compose lifecycle:
discover stacks, materialize compose files, start containers, quarantine stale stacks, report
results.

Dividing question:
- "Does this task write a file that a container reads?" → `lxc_docker_environment`
- "Does this task manage a running container?" → `lxc_stack_sync`

## Principle

SRP + DRY — one role answers "what files exist on disk"; the other answers "what containers
are running". Neither duplicates the other's facts or tasks.

## Consequences

**Easier:** Test file materialization independently of container state. Add a new managed file
type without touching compose logic. Reason about container lifecycle without caring about
which files back it.

**Harder:** Write a file that must be created atomically with a `docker compose up` (e.g., a
compose override generated at deploy time) requires coordination between the two roles.

## Deviation Conditions

A managed file must be written as part of the compose lifecycle itself — generated and applied
atomically. Requires a superseding ADR.
```

- [ ] **Step 2: Verify the file exists and renders**

```bash
cat docs/decisions/ADR-004-lxc-docker-environment-vs-lxc-stack-sync-boundary.md
```

Expected: full ADR content with all sections present.

- [ ] **Step 3: Commit**

```bash
git add docs/decisions/ADR-004-lxc-docker-environment-vs-lxc-stack-sync-boundary.md
git commit -m "docs(adr): ADR-004 lxc_docker_environment vs lxc_stack_sync boundary"
```
