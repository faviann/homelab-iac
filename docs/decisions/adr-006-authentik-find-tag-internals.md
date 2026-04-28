# ADR-006: Authentik Blueprint `!Find` Tag Internals

**Date**: 2026-04-27  
**Status**: Informational

## Context

When writing Authentik blueprints that need to reference objects without hardcoding instance-specific UUIDs, understanding the `!Find` tag's resolution behaviour is critical. This document records confirmed behaviour so future agents do not re-investigate.

## `!Find` Implementation

Source: `authentik/blueprints/v1/common.py`

```python
query = Q()
for cond in self.conditions:
    query_key = cond[0].resolve(...) if isinstance(cond[0], YAMLTag) else cond[0]
    query_value = cond[1].resolve(...) if isinstance(cond[1], YAMLTag) else cond[1]
    query &= Q(**{query_key: query_value})

return model_class.objects.filter(query).first()
```

**Confirmed behaviours:**

1. **Django `__` traversals work.** The field name is passed directly and unmodified to the `Q()` constructor. `stage__name`, `flow__slug`, `target__slug` and similar FK traversals all work natively.

2. **Multiple conditions are supported.** The YAML list alternates `[field1, value1, field2, value2, ...]`. All conditions are ANDed.

3. **`.first()` is used, not `.get()`.** If multiple objects match, the first is returned silently — no error. Design your lookup to be unambiguous.

4. **Model name is `app_label.model_name`.** Use the Django app label, not the Python module path. Confirmed examples from exported blueprints: `authentik_flows.flowstagebinding`, `authentik_flows.flow`, `authentik_policies_expression.expressionpolicy`, `authentik_policies.policybindingmodel`.

## What Has `managed` Fields (Stable Across Fresh Deploys)

Authentik sets `managed` values on these object types, making them addressable by `!Find [model, [managed, goauthentik.io/...]]`:

| Object type | Example managed value |
|---|---|
| `Flow` | `goauthentik.io/flows/default-password-change` |
| `Stage` subclasses | `goauthentik.io/stages/prompt/default-password-change-prompt` |
| `PropertyMapping` | `goauthentik.io/providers/oauth2/scope-openid` |
| `Policy` (some) | varies |

## What Does NOT Have `managed` Fields

- **`FlowStageBinding`** — confirmed by inspection of exported flow blueprints in `20-flows/`. Authentik identifies them only by `pk` (UUID). On a fresh deploy the UUID changes.
- **`PolicyBinding`** — no managed field. UUID changes on fresh deploy.
- **`Application`** — no managed field; addressable by `slug` which IS stable.

## Stable Reference Patterns for Common Cases

### Reference a FlowStageBinding without UUID

Use a `__` traversal on the stage name (stable because Stage has a managed field and a stable name):

```yaml
!Find [authentik_flows.flowstagebinding, [stage__name, default-password-change-prompt]]
```

If uniqueness is a concern (same stage bound to multiple flows), add a second condition:

```yaml
!Find [authentik_flows.flowstagebinding, [stage__name, default-password-change-prompt, target__slug, default-password-change]]
```

### Reference a Flow

Flows have stable slugs:

```yaml
!Find [authentik_flows.flow, [slug, default-password-change]]
```

### Reference a PolicyBinding target that is a Flow (not a FlowStageBinding)

Flows are also PolicyBindingModels. Find by slug via traversal:

```yaml
!Find [authentik_flows.flow, [slug, default-password-change]]
```

(This works because `Flow` extends `PolicyBindingModel`.)

## Instance-Specific UUIDs to Avoid Hardcoding

These are regenerated on every fresh Authentik deploy:

- `FlowStageBinding.pk` / `pbm_uuid` — use `stage__name` traversal instead
- `PolicyBinding.pk` / `pbm_uuid` — use object-specific stable fields instead
- Auto-created `Application`, `Provider`, `Group` PKs — use `slug` or `name` instead

## Confirmed In

- DES-010 investigation (2026-04-27): `stage__name` traversal validated against Authentik source
- Exported flow blueprints in `stacks/auth/auth/appdata/authentik/blueprints/20-flows/` confirm FlowStageBinding has no managed field
