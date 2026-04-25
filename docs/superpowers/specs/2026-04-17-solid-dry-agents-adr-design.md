# Design: SOLID/DRY Guardrails via AGENTS.md Principles + Targeted ADRs

- **Date**: 2026-04-17
- **Status**: Approved

## Problem

Refactoring is never-ending because there is no written record of why roles are shaped the way they are. Without a stated design intent, each pass re-discovers the same decisions and "centralize", "deepen", "consolidate" have no definition of done. The five hottest roles have each been touched 5–8 times across 40 unpushed commits.

## Approach

Two complementary artifacts:

1. **AGENTS.md design principles block** — Ansible-specific definitions of SOLID and DRY, always loaded into Claude's context. Acts as a live guardrail: before suggesting or accepting a refactor, the principle it serves must be identifiable.

2. **Targeted ADRs** (`docs/decisions/`) — One per hot role, capturing the decision that has been repeatedly re-litigated. Deviations from a decision require a superseding ADR, keeping the "why" documented regardless of direction.

## Section 1: AGENTS.md Additions

A "Design Principles" section added to AGENTS.md with the following rules:

**Single Responsibility**: A role does one thing — provision, configure, or orchestrate. If a role has tasks that both decide AND act, that is a violation.

**Open/Closed**: Extend behavior through variables and feature flags, not by editing task logic. Adding a capability = new var + new `when:` block, not modifying existing tasks.

**Interface Segregation**: Every role that accepts external input has an `argument_specs.yml`. Roles expose only the vars they need — no catch-all dicts bundling unrelated config.

**Dependency Inversion**: Roles depend on declared variables (the contract), not on sibling role internals or specific host facts baked into logic.

**DRY**: One place computes a fact; consumers read the registered var. No duplicated task blocks across roles. Defaults live in `defaults/main.yml`, not re-stated in group_vars.

**The refactoring gate**: Before starting a refactor, state which principle it serves and what "done" looks like in the commit message or in conversation. If a refactor intentionally breaks a principle, it requires an ADR.

## Section 2: ADR Format

**Location**: `docs/decisions/ADR-NNN-short-title.md`

```markdown
# ADR-NNN: <Title>

- **Date**: YYYY-MM-DD
- **Status**: Accepted | Superseded by ADR-NNN

## Context
What problem or tension prompted this decision.

## Decision
What we chose and why.

## Principle
Which rule(s) this satisfies (SRP, OCP, ISP, DI, DRY).

## Consequences
What this makes easy. What it makes harder.

## Deviation Conditions
When it is acceptable to break this decision. Requires a superseding ADR.
```

## Section 3: Initial ADR Coverage

Four ADRs covering the roles touched most frequently across the branch.

### ADR-001 — `lxc_spec_builder` owns desired state, nothing else
- **Principle**: SRP
- **Decision**: This role computes the full desired LXC spec from tier defaults + host vars. It does not apply, validate, or provision anything.
- **Deviation condition**: Spec shape must be computed inline for a one-off host with no generalizable pattern.

### ADR-002 — `proxmox_lxc_lifecycle` compile/decide split
- **Principle**: SRP
- **Decision**: `compile.yml` assembles facts; `decide.yml` makes the provision/skip/restart decision. Kept separate so decision logic is testable independently of fact gathering.
- **Deviation condition**: The decision is trivially derivable from a single fact with no branching.

### ADR-003 — `proxmox_lxc_host_config` config_file vs features split
- **Principle**: SRP
- **Decision**: `config_file*.yml` handle pct config entries; `features.yml` handles privileged capabilities (nesting, keyctl). Separate because they have different idempotency mechanisms.
- **Deviation condition**: A new capability is both a config entry and a feature flag simultaneously.

### ADR-004 — `lxc_docker_environment` vs `lxc_stack_sync` boundary
- **Principle**: SRP + DRY
- **Decision**: `lxc_docker_environment` owns runtime config (managed assets, env files). `lxc_stack_sync` owns compose lifecycle (discover, materialize, start, quarantine). One role answers "what files exist"; the other answers "what containers run".
- **Deviation condition**: A managed file must be written as part of the compose lifecycle itself.

## Implementation Order

1. Add design principles block to AGENTS.md
2. Create `docs/decisions/` and write ADR-001 through ADR-004
