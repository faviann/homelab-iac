# Architecture cleanup — handoff plan (2026-07-05)

Five small, independently-committable passes that remove dead code and concentrate
duplicated knowledge. Produced by an architecture review on 2026-07-05; all file/line
claims below were verified by grep on that date against `main`.

**Scope guard:** the provisioning spine (`proxmox_lxc_lifecycle`, `lxc_spec_builder`,
`lxc_stack_sync`) was reviewed and judged deep and well-tested. Do **not** restructure
it. This plan is peripheral cleanup only. Project philosophy applies: code is a
liability — every phase must end with net-less or equal code.

**After every phase:**

```bash
uv run --locked pytest tests/
uv run --locked ansible-playbook site.yml --check   # phases 2, 4, 5
```

One commit per phase. No `Co-Authored-By` trailers (repo convention, see CLAUDE.md).

---

## Phase 1 — Delete dead code (~10 min, zero risk)

1. Delete `playbooks/roles/infrastructure/proxmox_api_adapter/` entirely.
   - It is a placeholder: `tasks/main.yml` only prints a debug message; its
     `defaults/main.yml` aliases reference vars that don't exist.
   - Verified 0 references outside its own directory.
2. Delete `playbooks/lxc-provision.yml` (legacy path, superseded by the
   `proxmox_lxc_lifecycle` facade invoked from `playbooks/lifecycle-lxcs.yml`).
   - Its only reference is the tree listing at `README.md:241` — remove that line.
3. Re-grep to confirm nothing dangles:
   `grep -rn "proxmox_api_adapter\|lxc-provision" . --include="*.yml" --include="*.md"`

## Phase 2 — One seam for Proxmox API credentials (~30 min)

The same credential block (`api_host`, `api_port`, `api_user`, `api_token_id`,
`api_token_secret`, `validate_certs`) for module `community.proxmox.proxmox` is
copy-pasted 4×:

- `playbooks/roles/infrastructure/proxmox_lxc_provision/tasks/main.yml:41` (create)
- `playbooks/roles/infrastructure/proxmox_lxc_provision/tasks/main.yml:84` (update)
- `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/provision.yml:17` (stop)
- `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/provision.yml:35` (destroy)

Steps:

1. Add to the play in `playbooks/lifecycle-lxcs.yml` (after Phase 1 it is the only
   live caller of both roles):

   ```yaml
   module_defaults:
     community.proxmox.proxmox:
       api_host: "{{ proxmox_api_host }}"
       # ... mirror the exact params/values currently in the 4 task blocks
   ```

2. Strip those credential lines from the four tasks, keeping task-specific params
   (vmid, hostname, state, …).
3. Keep the fail-fast `assert` at `proxmox_lxc_provision/tasks/main.yml:22` unchanged.
4. Check `tests/regression/fixtures/*.yml` for any fixture playbook that includes
   these task files; add the same `module_defaults` block to those fixtures.

Out of scope (noted, don't do now): a second duplication family exists — the
`Authorization: "PVEAPIToken=..."` header repeated across `validate-credentials.yml`,
`lab-connectivity.yml`, `proxmox_api_check.yml`, and `playbooks/tasks/proxmox_validation.yml`.
Those are `uri`-based diagnostics plays; leave them.

## Phase 3 — `compose_env` filter absorbs the `$ → $$` escaping (~45 min)

`| replace('$', '$$')` appears **21 times across 7 template files** (verified count):

- `stacks/auth/auth/.env.j2` (5×)
- `stacks/auth/auth/compose.override.yaml.j2` (2×)
- `stacks/auth/auth/appdata/authentik/blueprints/80-oidc-apps.yaml.j2` (7×)
- `stacks/auth/auth/appdata/authentik/blueprints/85-proxmox-oidc.yaml.j2` (1×)
- `stacks/seedbox/bittorrent/.env.j2` (2×)
- `stacks/portal/traefik3/.env.j2` (2×)
- `stacks/portal/dockhand/.env.j2` (1×)
- (find them all: `grep -rnF "replace('\$', '\$\$')" stacks/`)

Steps:

1. Create a filter plugin, e.g. `playbooks/filter_plugins/compose_env.py`, exposing
   `compose_env(value) -> str.replace('$', '$$')`. No `filter_plugins/` dir exists
   yet — confirm Ansible picks it up (adjacent to playbooks is the default; otherwise
   set `filter_plugins` in `ansible.cfg`). Note the templating happens inside
   `lxc_stack_sync/tasks/materialize.yml`, so the plugin must be visible to that
   role's template task — a role-level `filter_plugins/` dir inside
   `playbooks/roles/config/lxc_stack_sync/` also works and keeps locality.
2. Add a unit test in `tests/unit/` (that's the point: the escaping rule becomes
   testable once).
3. Replace occurrences in the Compose-consumed files (`.env.j2`,
   `compose.override.yaml.j2`) with `| compose_env`.
4. **Judgment call before touching the blueprint files**: the occurrences in
   `stacks/auth/auth/appdata/authentik/blueprints/*.yaml.j2` are Authentik
   blueprints, NOT Compose-interpolated files. Verify whether those files pass
   through Docker Compose variable interpolation at all. If they don't, the `$$`
   escaping there may be actively corrupting secrets that contain `$` — that would
   be a latent bug to fix (remove the escaping), not a mechanical rename. Check how
   `appdata/` files are materialized and mounted before deciding. Relevant ADRs:
   `docs/decisions/adr-006-authentik-find-tag-internals.md`,
   `docs/decisions/adr-005-navidrome-authentik-sync.md`.

## Phase 4 — Finish adopting the `ssh_key_shared` seam (~1–2 h)

The control-node pubkey path is derived in 7 places with 4 different idioms
(`playbook_dir + '/...'`, `playbook_dir | dirname`, `playbook_dir + '/../'`,
`control_node_project_root`-based). Root cause: `playbook_dir` differs between
`site.yml` (repo root) and `playbooks/*.yml`. The module built to own this —
`playbooks/roles/infrastructure/ssh_key_shared/tasks/resolve_pubkey.yml`, which does
multi-candidate resolution — has only 2 adopters (`lxc_ssh_key_injector`,
`proxmox_host_bootstrap/tasks/ssh_access.yml`).

Bypassers to convert:

| Site | Current idiom |
|------|---------------|
| `playbooks/add-ssh-keys-to-lxcs.yml:14` | `playbook_dir + '/../'` |
| `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/provision.yml:77` | `playbook_dir \| dirname` |
| `playbooks/roles/provisioning/lxc_spec_builder/defaults/main.yml:34` | `playbook_dir + '/'` |
| `playbooks/roles/infrastructure/proxmox_lxc_provision/defaults/main.yml:17` | `playbook_dir \| dirname` |
| `playbooks/roles/infrastructure/proxmox_host_bootstrap/defaults/main.yml:13` | `playbook_dir + '/../'` (default expr) |
| `playbooks/roles/base/control_node_bootstrap/tasks/main.yml:18` | `control_node_project_root`-based |

Steps:

1. Read `resolve_pubkey.yml` first to learn what fact it publishes.
2. In `proxmox_lxc_lifecycle` (during `compile.yml` or at the top of `provision.yml`),
   include `ssh_key_shared` `tasks_from: resolve_pubkey` once; pass the resolved path
   into `lxc_spec_builder` and `proxmox_lxc_provision`, replacing their hardcoded
   defaults.
3. Convert `add-ssh-keys-to-lxcs.yml`, `proxmox_host_bootstrap/defaults`, and
   `control_node_bootstrap` the same way.
4. Delete the per-role hardcoded defaults, or keep the vars as documented override
   points whose default is the resolved fact.
5. Expect to update regression fixtures for `lxc_spec_builder`
   (`tests/regression/`, spec-merge tests) that relied on the old defaults.
6. Read `docs/ssh-key-management.md` before starting; update it after.

## Phase 5 — One release probe, not two (~1–2 h, fiddliest)

"What Debian release is this container running" is implemented twice:

- `playbooks/tasks/proxmox_validation.yml` (536-line validation play, runs on the
  `proxmox_api` host, publishes `lxc_validation_results[host]` incl. `actual_release`
  / `release_probe_state`)
- `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/inspect.yml` (reads that
  fact when present, but re-implements the probe — `proxmox_pct` exec of
  `. /etc/os-release && printf VERSION_ID` + `regex_findall` — as a fallback when the
  validation play didn't run)

Steps:

1. Extract the probe into one shared task file, e.g.
   `playbooks/tasks/probe_lxc_release.yml`, parameterized by vmid + delegation
   target. It should own both the `pct` exec and the version parsing.
2. Point both callers at it. `inspect.yml` keeps its "use `lxc_validation_results`
   if present" fast path; only its fallback changes to include the shared file.
3. The two callers run in different play contexts (proxmox_api host vs per-LXC
   play with delegation) — this is the fiddly part; test both paths.
4. Add a regression fixture asserting both callers parse probe output identically
   (that drift is the bug this phase prevents).
5. Sanity-check the full chain live: `uv run --locked ansible-playbook site.yml
   --check --limit <one-host>`, and once for real on a low-stakes host.

---

## Not in scope (decided during review)

- **Secret plumbing** (vault.yml → host_vars `lxc_docker_env_stack_vars` → stack_vars
  → .env.j2; each secret named 4×): real friction, but replacing hand mappings with a
  naming convention trades explicitness for magic and is in tension with
  `lxc_stack_sync`'s documented ban on injecting stack metadata into host var scope.
  Needs a design conversation with the owner first. Do not attempt as part of this
  cleanup.
- **Test coverage gaps** (`playbooks/tasks/proxmox_validation.yml`,
  `rotate-vault-passphrase.sh`, `configure-vault.sh`, `setup.sh`): coverage work, not
  refactoring. Track separately.
