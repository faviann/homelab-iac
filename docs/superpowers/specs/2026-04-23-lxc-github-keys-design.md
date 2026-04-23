# LXC GitHub SSH Keys — Design Spec

**Date**: 2026-04-23  
**Status**: approved  
**Backlog**: DES-009

## Problem

All LXCs should allow non-root SSH access using the owner's GitHub public keys. Currently only the `workstation` LXC has this — its `lxc_workstation_baseline` role fetches keys from GitHub and writes `authorized_keys` for `docker_user`. No other LXC has equivalent access, and the logic is not reusable.

## Design

### Architecture

```
group_vars/lxcs/vars.yml
  lxc_ssh_user: faviann        ← fallback identity for non-cap_docker hosts
  lxc_ssh_uid: 1000
  lxc_ssh_gid: 1000
  lxc_github_users: [faviann]  ← shared GitHub users list, all LXCs

[new] config/lxc_github_keys   ← single concern: fetch keys, write authorized_keys
  target user: docker_user | default(lxc_ssh_user)
  called by lxc_workstation_baseline (replaces its inline fetch tasks)
  called by proxmox_lxc_lifecycle configure play for all lxcs

lxc_workstation_baseline        ← keeps package installs; drops key fetch logic
  calls config/lxc_github_keys via include_role
```

### New role: `config/lxc_github_keys`

**Default vars:**
```yaml
lxc_github_keys_user:         "{{ docker_user | default(lxc_ssh_user) }}"
lxc_github_keys_uid:          "{{ docker_uid  | default(lxc_ssh_uid)  }}"
lxc_github_keys_gid:          "{{ docker_gid  | default(lxc_ssh_gid)  }}"
lxc_github_keys_github_users: "{{ lxc_github_users }}"
lxc_github_keys_base_url:     "https://github.com"
```

**Tasks:**
1. Assert `lxc_github_keys_github_users` is non-empty
2. Ensure `~{{ lxc_github_keys_user }}/.ssh/` exists — mode `0700`, correct owner/group
3. Curl `{{ lxc_github_keys_base_url }}/{{ item }}.keys` per user — skipped in check mode
4. Merge stdout lines, trim, dedup; fail if result is empty
5. Write `authorized_keys` — mode `0600`, correct owner/group — skipped in check mode

Check-mode safety mirrors `lxc_workstation_baseline`: steps 3–5 are gated on `not ansible_check_mode`.

### Refactor: `lxc_workstation_baseline`

Remove tasks that:
- Fetch GitHub keys (the `ansible.builtin.command` curl loop)
- Build `workstation_authorized_keys` set_fact
- Fail if zero keys
- Write `authorized_keys`
- Ensure `.ssh/` directory (now owned by `lxc_github_keys`)

Replace with:
```yaml
- name: Configure GitHub SSH keys
  ansible.builtin.include_role:
    name: config/lxc_github_keys
```

The assert block in `lxc_workstation_baseline` that checks `workstation_github_users | length > 0` is superseded by the assert inside `lxc_github_keys`. Remove it.

### Wiring: `proxmox_lxc_lifecycle/tasks/configure.yml`

Add after `Configure base system`, before `Configure workstation baseline`:

```yaml
- name: Configure GitHub SSH keys
  ansible.builtin.include_role:
    name: config/lxc_github_keys
```

No `when` guard — runs on all LXCs. The role's internal assert fails fast if `lxc_github_users` is empty, which is the right behaviour.

### Inventory changes

**`inventory/group_vars/lxcs/vars.yml`** — append:
```yaml
lxc_ssh_user: faviann
lxc_ssh_uid: 1000
lxc_ssh_gid: 1000
lxc_github_users:
  - faviann
```

**`inventory/host_vars/workstation.yml`** — remove `workstation_github_users`. The `docker_user: faviann` / `docker_uid` / `docker_gid` overrides were also removed (now redundant — group default matches).

**`inventory/group_vars/cap_docker/vars.yml`** — `docker_user` changed from `dockeruser` to `faviann` to standardize the login username across all LXCs.

### User identity resolution

| Host | `docker_user` | `lxc_ssh_user` | Resolved target |
|------|--------------|----------------|-----------------|
| workstation | faviann (from group) | faviann | faviann |
| auth, portal, servarr, etc. | faviann | faviann | faviann |
| future non-docker LXC | _(undefined)_ | faviann | faviann |

## Testing

Follow the fixture pattern in `tests/regression/fixtures/workstation_baseline_*`.

New fixtures for `config/lxc_github_keys`:

| Fixture | Asserts |
|---------|---------|
| `lxc_github_keys_empty_users_test.yml` | Role fails fast when `lxc_github_keys_github_users` is empty |
| `lxc_github_keys_single_user_test.yml` | `.ssh/` dir created, `authorized_keys` written, correct owner/mode |
| `lxc_github_keys_multi_user_dedup_test.yml` | Keys from multiple users merged and deduplicated |

Existing `workstation_baseline_github_keys_test.yml` and `workstation_baseline_empty_github_keys_test.yml` remain valid — they now cover the workstation path through to `lxc_github_keys`, providing regression coverage for the refactor.

## Out of scope

- Adding `sudo` rights or shell provisioning for the SSH user — separate concern
- Rotating or revoking keys — GitHub is the source of truth; re-running the role updates keys
- Non-GitHub key sources
