# DES-010 Navidrome PolicyBinding Sustainability Premise Lock

Status: Draft
Date: 2026-04-27
Owner: Fav

## Stated Request

Address DES-010 in a more sustainable way.

## Underlying Need

Ensure the navidrome sync `PolicyBinding` can be reliably provisioned without hardcoded
environment-specific UUIDs that break on a fresh Authentik deploy.

## Problem

`27-navidrome-password-change-sync.yaml` hardcodes `pbm_uuid = 19fc00cb-14e2-4aed-a686-1e05d15e84e8`
— the `policybindingmodel_ptr_id` of the `default-password-change-prompt` FlowStageBinding on
this specific instance. On a fresh Authentik deploy, that object is recreated with a new random
UUID, causing the blueprint to enter error state.

## Goals

- Eliminate the hardcoded instance-specific UUID from the blueprint
- Ensure `authentik_blueprint_sync.py export` captures the correct UUID from live state
- `authentik_blueprint_sync.py apply` continues to work idempotently
- Fresh deploy has a clear, documented recovery path (manual once → export → done)

## Non-Goals

- Eliminating the one-time manual step on fresh deploy (the bootstrap case)
- Upstreaming a fix to Authentik's `!Find` / `Find.resolve()` behavior
- Making blueprint 27 apply correctly with zero prior state (no binding in live Authentik)

## Constraints

- Fresh Authentik deploy is a realistic scenario (confirmed)
- Must not add a new API endpoint dependency not already used
- Solution must fit the existing export/apply workflow

## Confirmed Premises

- Fresh deploy is a realistic scenario (user confirmed)
- `state["bindings"]` (from `/api/v3/policies/bindings/`) already fetched in `collect_state()`;
  each binding has `policy` (policy pk) and `target` (pbm_uuid)
- `state["policies"]` (from `/api/v3/policies/all/`) already fetched; each policy has `pk` and `name`
- Lookup chain (policy name → pk → binding → target) is already used in `build_applications_blueprint`
- Blueprint 27 stays in `CUSTOM_BLUEPRINT_FILES` for apply — only the generation changes

## Assumptions If Unanswered

- The navidrome PolicyBinding exists on the current instance before export runs
- On fresh deploy: admin creates the binding once via UI, then runs export

## Unresolved Risky Premises

None remaining.

## Option Investigation Results (2026-04-27)

Before implementing Option D, two better options were investigated:

**Option A: Use `managed` field on FlowStageBinding** — Eliminated. Confirmed by inspecting
exported flow blueprints in `stacks/auth/auth/appdata/authentik/blueprints/20-flows/`. Authentik
does NOT set a `managed` field on FlowStageBindings. Exported blueprints identify them by `pk`
(UUID) only.

**Option B: `!Find` with Django `__` traversal** — Confirmed working. Authentik's `!Find` tag
implementation (in `authentik/blueprints/v1/common.py`) passes the field name directly to
`Q(**{query_key: query_value})` with no normalisation or sanitisation. Django `__` traversals
work natively. The stable reference is:

```yaml
!Find [authentik_flows.flowstagebinding, [stage__name, default-password-change-prompt]]
```

`authentik_flows.flowstagebinding` is the correct model (confirmed from 20-flows/ exports).
`default-password-change-prompt` is a managed Authentik stage — stable name on every instance.
This eliminates the UUID entirely. No dynamic generation, no manual step on fresh deploy.

**Selected: Option B.** Plan updated accordingly. See `docs/decisions/adr-006-authentik-find-tag-internals.md`.

## Not Locked Yet

All resolved. Option B implementation is a single YAML file edit.

## Verification Expectations

- After implementation: `apply` on the updated YAML succeeds (no blueprint error state)
- After implementation: fresh Authentik deploy applies blueprint 27 without any manual step

## Recommended Next Mode

Start implementation (plan is ready).

## Premise Change Log

- 2026-04-27: Initial lock created. Option A eliminated (fresh deploy is realistic).
  Option D selected: dynamic generation in export command.
- 2026-04-27: Option A eliminated (no managed field on FlowStageBinding, confirmed by
  inspection of exported flow blueprints). Option B confirmed (Authentik !Find supports
  Django __ traversals, confirmed from source). Option D superseded. Option B selected.
