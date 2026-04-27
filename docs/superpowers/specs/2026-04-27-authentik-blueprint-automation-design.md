# Authentik Blueprint Apply Automation

**Date**: 2026-04-27  
**Status**: Approved

## Problem

Running `ansible-playbook site.yml` deploys blueprint YAML files to the auth LXC but does not apply them. A manual follow-up step — `python scripts/authentik_blueprint_sync.py apply` — is required to push the repo state into authentik. This creates deployment gap: the live authentik config can silently lag behind the repo, and any UI-level drift is invisible until the script is run by hand.

## Decision

Automate the `apply` step inside Ansible. Every `site.yml` run on the `auth` host will deploy blueprint files and then apply them in one atomic sequence, making the repo the enforced source of truth for authentik config.

## Out of Scope

- The `export` command (`authentik_blueprint_sync.py export`) remains a developer workflow tool — it is not automated. Running it on every deploy would overwrite the repo.
- Blueprint completeness (whether all authentik state is captured in blueprints) is tracked separately as DES-011.

## Architecture

```
site.yml
  └── configure.yml
        └── config/lxc_docker_environment   (existing — deploys blueprint files to LXC)
        └── config/authentik_blueprint_sync (NEW — applies blueprints via API, auth host only)
```

The new role runs entirely on the controller (`delegate_to: localhost`, `become: false`). It calls the existing `scripts/authentik_blueprint_sync.py apply` which hits the authentik API. Authentik reads blueprint files from its already-mounted `/blueprints/custom` volume.

Because the script is called on every run, every `site.yml` acts as a drift correction: UI-level changes made outside the repo are reverted. The repo is authoritative.

## Token Bootstrap

The apply script needs an API token. On a fresh deploy, no token exists yet — this is resolved with `AUTHENTIK_BOOTSTRAP_TOKEN`:

1. Generate a token value once: `openssl rand -hex 32`
2. Store in vault as `vault_auth_blueprint_api_token`
3. Inject into `.env.j2` as `AUTHENTIK_BOOTSTRAP_TOKEN` — authentik creates this token on first startup
4. Inject into the role via `authentik_blueprint_api_token` host var — Ansible uses it to call the script

On subsequent deploys the bootstrap env var is a no-op (token already exists). No manual token creation step, ever.

The token is admin-scoped. A scoped service account is not warranted for this scale.

## New Role: `config/authentik_blueprint_sync`

**Defaults:**
```yaml
authentik_blueprint_sync_enabled: false
authentik_blueprint_sync_url: "http://auth.faviann.vms:9000"
authentik_blueprint_api_token: ""
```

**Tasks (block/always for tempfile cleanup):**

```
block:
  1. Wait for authentik API
       uri GET {{ authentik_blueprint_sync_url }}/api/v3/-/healthcheck/
       retries: 30, delay: 10  (up to 5 minutes)

  2. Write token to tempfile
       ansible.builtin.tempfile  → tmpfile
       ansible.builtin.copy content={{ authentik_blueprint_api_token }} mode=0600

  3. Run apply script
       ansible.builtin.command
         python3 {{ playbook_dir }}/scripts/authentik_blueprint_sync.py apply
           --token-file {{ tmpfile.path }}
       delegate_to: localhost
       become: false
       changed_when: true

always:
  4. Remove tempfile
       ansible.builtin.file state=absent path={{ tmpfile.path }}
```

The script exits non-zero on any blueprint error, which fails the play. No additional error handling is needed in the role.

## configure.yml Addition

```yaml
- name: Apply Authentik blueprints
  ansible.builtin.include_role:
    name: config/authentik_blueprint_sync
  when: authentik_blueprint_sync_enabled | default(false)
```

Added immediately after the `Configure Docker environment` step.

## Inventory Changes

**`inventory/host_vars/auth.yml`** — add to host vars:
```yaml
authentik_blueprint_sync_enabled: true
authentik_blueprint_api_token: "{{ vault_auth_blueprint_api_token }}"
```

Add to `lxc_docker_env_stack_vars.auth`:
```yaml
blueprint_api_token: "{{ vault_auth_blueprint_api_token }}"
```

**`stacks/auth/auth/.env.j2`** — add:
```
AUTHENTIK_BOOTSTRAP_TOKEN={{ stack_vars.blueprint_api_token | replace('$', '$$') }}
```

**`inventory/group_vars/all/vault.yml`** — add encrypted entry:
```yaml
vault_auth_blueprint_api_token: <REPLACE_ME>
```

## Known Limitations

**Renames create orphans.** Authentik blueprints use identifiers (flow slug, provider name, group name, application slug) to find existing objects. Changing an identifier in the blueprint creates a new object — the old one remains in the database. To rename cleanly, add a `state: absent` entry for the old identifier in the same blueprint alongside the new `state: present` entry.

**Blueprint completeness is unverified.** Objects created manually in the authentik UI and never captured in a blueprint are invisible to this automation. They will not drift-correct and will not survive a fresh deploy. See DES-011.

**`export` remains manual.** When UI state needs to be pulled back into the repo (e.g. after iterating on a flow in the UI), the developer must run `python scripts/authentik_blueprint_sync.py export` locally and commit the result.
