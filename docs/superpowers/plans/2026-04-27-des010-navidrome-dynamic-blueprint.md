# DES-010 Navidrome Dynamic Blueprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Premise source:** `docs/superpowers/premises/2026-04-27-des010-navidrome-policy-binding-premise-lock.md`

**Goal:** Fix `27-navidrome-password-change-sync.yaml` so it survives a fresh Authentik deploy without a manual step. The hardcoded `pbm_uuid` is replaced with a stable `!Find` reference using a Django `__` traversal.

**Architecture:** Update blueprint 27 to use `!Find [authentik_flows.flowstagebinding, [stage__name, default-password-change-prompt]]` instead of `!Find [authentik_policies.policybindingmodel, [pbm_uuid, <hardcoded-uuid>]]`. The `default-password-change-prompt` stage is an Authentik managed object — it exists with a stable name on every instance from first startup. No dynamic generation, no `build_navidrome_blueprint` function, no export wiring. The file stays static.

**Why this works:** Authentik's `!Find` tag passes the field name directly into Django ORM's `Q(**{field: value})`, so `__` traversals work natively. `authentik_flows.flowstagebinding` is the correct model (confirmed from exported flow blueprints in `20-flows/`). The stage name `default-password-change-prompt` is stable across fresh deploys because it is a managed Authentik system object. See `docs/decisions/adr-006-authentik-find-tag-internals.md`.

**Tech Stack:** YAML edit only. No Python changes.

---

## File Map

| File | Change |
|---|---|
| `stacks/auth/auth/appdata/authentik/blueprints/27-navidrome-password-change-sync.yaml` | Replace hardcoded `pbm_uuid` with stable `!Find` via `stage__name` traversal |
| `docs/decisions/adr-005-navidrome-authentik-sync.md` | Add resolution note — no bootstrap procedure required |
| `BACKLOG.md` | Close DES-010 |

---

## Task 1: Update blueprint 27

**Files:**
- Modify: `stacks/auth/auth/appdata/authentik/blueprints/27-navidrome-password-change-sync.yaml`

- [ ] **Step 1: Replace the file content**

The current file uses:
```yaml
target: !Find [authentik_policies.policybindingmodel, [pbm_uuid, 19fc00cb-14e2-4aed-a686-1e05d15e84e8]]
```

Replace the entire file with:

```yaml
version: 1
metadata:
  name: repo-auth-navidrome-password-change-sync
  labels:
    blueprints.goauthentik.io/instantiate: 'false'
    blueprints.goauthentik.io/description: Managed from ServerManagementScripts
entries:
- model: authentik_policies.policybinding
  state: present
  identifiers:
    target: !Find [authentik_flows.flowstagebinding, [stage__name, default-password-change-prompt]]
    policy: !Find [authentik_policies_expression.expressionpolicy, [name, navidrome-registration-sync-policy]]
    order: 0
  attrs:
    target: !Find [authentik_flows.flowstagebinding, [stage__name, default-password-change-prompt]]
    policy: !Find [authentik_policies_expression.expressionpolicy, [name, navidrome-registration-sync-policy]]
    order: 0
    enabled: true
    negate: false
    timeout: 10
```

- [ ] **Step 2: Verify the hardcoded UUID is gone**

```bash
grep -c "19fc00cb" stacks/auth/auth/appdata/authentik/blueprints/27-navidrome-password-change-sync.yaml
```

Expected: `0`

- [ ] **Step 3: Commit**

```bash
git add stacks/auth/auth/appdata/authentik/blueprints/27-navidrome-password-change-sync.yaml
git commit -m "fix(auth): replace hardcoded pbm_uuid in blueprint 27 with stable stage__name !Find"
```

---

## Task 2: Update ADR-005

**Files:**
- Modify: `docs/decisions/adr-005-navidrome-authentik-sync.md`

- [ ] **Step 1: Append resolution note**

At the end of the file append:

```markdown

## DES-010 Resolution

The hardcoded `pbm_uuid` in blueprint 27 was replaced with a stable `!Find` reference:

```yaml
target: !Find [authentik_flows.flowstagebinding, [stage__name, default-password-change-prompt]]
```

`default-password-change-prompt` is an Authentik managed stage — it exists with a stable name on every instance from first startup. No manual bootstrap step is required. See `docs/decisions/adr-006-authentik-find-tag-internals.md` for the `!Find` `__` traversal reference.
```

- [ ] **Step 2: Commit**

```bash
git add docs/decisions/adr-005-navidrome-authentik-sync.md
git commit -m "docs(auth): document DES-010 resolution in ADR-005"
```

---

## Task 3: Close DES-010 in the backlog

**Files:**
- Modify: `BACKLOG.md`

- [ ] **Step 1: Move DES-010 to Done**

In `BACKLOG.md`:
1. Move the `### [DES-010]` entry from `## Open` to `## Done`
2. Add `- **Completed**: 2026-04-27`
3. Add `- **Resolution**: Replaced hardcoded pbm_uuid with stable !Find via stage__name Django traversal — no dynamic generation, no bootstrap step`

- [ ] **Step 2: Commit**

```bash
git add BACKLOG.md
git commit -m "chore: close DES-010 — blueprint 27 now uses stable !Find stage__name reference"
```

---

## Self-Review Checklist

- [x] Hardcoded UUID removed from blueprint 27
- [x] Stable reference survives fresh Authentik deploy (no manual step)
- [x] `CUSTOM_BLUEPRINT_FILES` untouched — apply flow unaffected
- [x] No Python changes — no new functions, no export wiring
- [x] ADR-005 updated with resolution
- [x] Backlog closed
