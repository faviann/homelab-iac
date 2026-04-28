# Authentik RBAC & Group Architecture — Design Spec

**Date:** 2026-04-27
**Status:** Approved

---

## Context

The current authentik setup has four flat groups (`admins`, `content-editors`, `ldapsearch`, `media`) with direct group bindings per application. The goal is to formalise this into a coherent RBAC architecture that:

- Supports ~15 users of varying trust levels with room for granularity
- Uses domain bundle groups for automatic bundle access and per-app groups for surgical access
- Uses authentik 2026.02 Roles for internal permission delegation (not application access)
- Avoids deprecated `ak_groups` — all expression policies use `user.groups.filter()` or blueprint `!Find` references

---

## Group Architecture

### Domain Bundle Groups

Being in one of these groups grants access to **all apps in that domain** automatically.

| Group | Domain | Apps covered |
|-------|--------|--------------|
| `admins` | All | Every application — bound to every app at order 2 |
| `media` | Media | Navidrome, Plex, RomM, and any future media apps |
| `reading` | Reading | Audiobookshelf, Komga, Calibre-Web Automated, ReadMeABook |
| `storage` | Storage/Files | Homepage admin, Immich, Paperless, Filebrowser, and future file/document apps |

### Special Groups

| Group | Purpose |
|-------|---------|
| `ldapsearch` | Internal LDAP access — service accounts only. Not a domain bundle; not assigned to human users. |

### Per-App Groups

Created **on demand only** — only when a user needs access to a single app without joining its parent domain bundle. Not pre-created in blueprints. When created, they are added to `10-groups.yaml` following the existing pattern.

Example: a user who should see only Navidrome gets added to a `navidrome` group, which is bound at order 0 on the Navidrome application alongside the `media` and `admins` bindings.

### Roles (authentik 2026.02 internal permissions)

| Role | Permissions | Assigned to |
|------|-------------|-------------|
| `registration-approver` | `authentik_core.view_user`, `authentik_core.change_user` | Named user directly |

Roles grant authentik admin UI access only — they do not grant application access. The role holder can see the user list and activate/deactivate pending registrations. They cannot manage groups, flows, providers, or system config.

---

## Binding Convention

Every forward-auth and OIDC application follows the same three-binding pattern:

```
order 0 — per-app group      (omit if group does not exist yet)
order 1 — domain bundle group (e.g. media, reading, storage)
order 2 — admins              (always present on every app)

policy_engine_mode: any       (any single match grants access)
```

Blueprint YAML pattern:

```yaml
- model: authentik_policies.policybinding
  state: present
  identifiers:
    target: !KeyOf 'app-<slug>'
    order: 1
  attrs:
    target: !KeyOf 'app-<slug>'
    order: 1
    enabled: true
    negate: false
    failure_result: false
    timeout: 30
    group: !Find [authentik_core.group, [name, <domain-group>]]
```

All group lookups use `!Find [authentik_core.group, [name, <name>]]`. No hardcoded UUIDs. No `ak_groups` anywhere.

---

## Blueprint File Changes

### `10-groups.yaml` — modify

- `admins`: keep unchanged
- `media`: keep unchanged
- `ldapsearch`: keep unchanged
- `content-editors`: **remove** (`state: absent`)
- `storage`: **add** (replaces `content-editors`)
- `reading`: **add** (new domain bundle)

### `15-roles.yaml` — new file

```yaml
version: 1
metadata:
  name: repo-auth-roles
  labels:
    blueprints.goauthentik.io/instantiate: 'false'
    blueprints.goauthentik.io/description: Managed from ServerManagementScripts
entries:
- model: authentik_rbac.role
  state: present
  identifiers:
    name: registration-approver
  attrs:
    name: registration-approver
    permissions:
    - authentik_core.view_user
    - authentik_core.change_user
```

Role assignment to a named user is done in a separate blueprint entry (e.g. `50-service-accounts.yaml` or a new `55-user-roles.yaml`) once the sub-admin username is known:

```yaml
- model: authentik_core.user
  state: present
  identifiers:
    username: <sub-admin-username>
  attrs:
    roles:
    - !Find [authentik_rbac.role, [name, registration-approver]]
```

### `40-applications.yaml` — modify

| Application | Change |
|-------------|--------|
| `home-wildcard` | Set existing `content-editors` binding `state: absent`; add `storage` binding |
| `media-wildcard` | Set existing `content-editors` binding `state: absent`; keep `media` + `admins` |
| `ldap` | Add `ldapsearch` group binding (hygiene — prevents app appearing in all users' portal) |
| `admin-wildcard` | No change — `admins` only |
| `authentik-ui` | No change — `always-allow` (passthrough, auth.faviann.com) |
| `faviann-domain` | No change — catch-all forward-auth |

### `80-oidc-apps.yaml.j2` — modify

Replace `always-allow` policy binding with group bindings on all OIDC apps. Standard 3-binding pattern applies.

| App | Domain group (order 1) |
|-----|----------------------|
| RomM | `media` |
| Audiobookshelf | `reading` |
| Komga | `reading` |
| Calibre-Web Automated | `reading` |
| ReadMeABook | `reading` |

Each also gets `admins` at order 2.

### Unchanged files

`20-flows/`, `24-brand-flows.yaml`, `25-default-auth-policies.yaml`, `26-registration-approval-flow.yaml`, `27-navidrome-password-change-sync.yaml`, `30-providers.yaml`, `50-service-accounts.yaml`, `60-outposts.yaml`, `70-notifications.yaml.j2`

---

## Future-Proofing Notes

- Adding a new app: create app entry in the appropriate blueprint, add bindings following the 3-binding pattern, create a per-app group in `10-groups.yaml` only if surgical access is needed immediately.
- Adding a new domain: add a group to `10-groups.yaml`, add bindings for all apps in that domain.
- Restricting an existing user to one app: create their per-app group, remove them from the domain bundle, add them to the per-app group only.
- 2026.x compatibility: no deprecated variables used. Policy bindings are attached to applications (not providers), consistent with the current and future authentik model.
