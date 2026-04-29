# Workstation Persistent Home Links - Design

**Date:** 2026-04-28  
**Status:** Approved, amended 2026-04-29  
**Scope:** Preserve selected workstation home paths across intentional workstation LXC rebuilds.

---

## Problem

The `workstation` LXC is managed as cattle by Ansible. Rebuilding it keeps the compute environment clean, but currently also removes local agent CLI state such as Claude and Codex session history/config. That is not catastrophic because durable project knowledge belongs in Git, vault-backed secrets, chezmoi-managed dotfiles, and the LLM wiki, but losing CLI continuity during an intentional rebuild is inconvenient.

The goal is to preserve useful continuity without turning the whole workstation home directory into a pet.

---

## Design

Use the existing `/ephemeral` bind mount as local host-persistent storage for selected workstation home paths.

Host/LXC-visible persistent state:

```text
/ephemeral/workstation/home/
  .claude/
  .codex/
  repos/
```

Workstation user home:

```text
/home/<workstation_user>/.claude -> /ephemeral/workstation/home/.claude
/home/<workstation_user>/.codex  -> /ephemeral/workstation/home/.codex
/home/<workstation_user>/repos   -> /ephemeral/workstation/home/repos
```

This state survives intentional LXC deletion/recreation as long as the Proxmox host-side `/ephemeral` storage remains intact. It is not the authoritative memory layer and does not need remote-first sync.

---

## Inventory Contract

Keep this behavior under the existing workstation role instead of creating a new capability group. Persistent home links are currently a workstation-only concern, and a reusable capability group would add abstraction before there is a second consumer.

Add workstation role variables:

```yaml
workstation_persistent_home_enabled: true
workstation_persistent_home_root: /ephemeral/workstation/home
workstation_persistent_home_links:
  - name: claude
    path: "{{ workstation_home }}/.claude"
    target: "{{ workstation_persistent_home_root }}/.claude"
    mode: "0700"
  - name: codex
    path: "{{ workstation_home }}/.codex"
    target: "{{ workstation_persistent_home_root }}/.codex"
    mode: "0700"
  - name: repos
    path: "{{ workstation_home }}/repos"
    target: "{{ workstation_persistent_home_root }}/repos"
    mode: "0755"
```

`workstation_home` is an existing `playbooks/roles/config/lxc_workstation_baseline`
default. `workstation_persistent_home_enabled: false` is the escape hatch for a
deliberately clean rebuild. Disabling it means the role does not create or manage
persistent home directories and links; it does not remove existing symlinks or
persistent state.

---

## Role Behavior

`playbooks/roles/config/lxc_workstation_baseline` should:

1. Create `workstation_persistent_home_root` and each configured target directory.
2. Own those directories with `workstation_uid` and `workstation_gid`, matching the existing workstation user contract.
3. Set `workstation_persistent_home_root` to mode `0700` and each child target to its configured mode.
4. Create symlinks from the workstation user's home into the persistent directories.
5. Avoid persisting the whole home directory.
6. Avoid copying, printing, or managing secrets directly.

If a target home path already exists as a symlink to the desired target, the role should be a no-op.

If a target home path exists as a real file or directory, the role should fail
clearly and instruct the operator to move or migrate it manually before enabling
workstation persistent home links. The role must not silently overwrite, delete, or rename
the existing path because these directories may contain active CLI state.

---

## Memory Boundaries

Durable memory:

- Git repositories
- Git-backed LLM wiki
- committed docs, specs, plans, and ADRs
- secrets restored from Bitwarden, vault, or chezmoi-managed sources

Comfort continuity:

- `~/.claude`
- `~/.codex`
- `~/repos`
- future selected home paths, only when explicitly added

Regenerable state that should not be persisted by default:

- full `/home/<user>`
- `.venv`
- `node_modules`
- build outputs
- package manager caches
- random downloads

---

## Failure Model

This design protects against intentional workstation LXC rebuilds and reprovisioning. It does not protect against loss of the Proxmox host storage backing `/ephemeral`.

That is acceptable for v1 because Claude/Codex local state and checked-out repositories are convenient but not authoritative. If losing this state becomes more than inconvenient, the next design step is a local backup or ZFS replication policy for `/ephemeral/workstation/home`.

---

## Testing

Add focused tests for the workstation baseline role contract:

- defaults include the persistent home variables
- role tasks create persistent home directories when enabled
- role tasks create `~/.claude`, `~/.codex`, and `~/repos` symlinks
- disabling `workstation_persistent_home_enabled` skips the behavior
- an existing real file or directory at a managed home path fails clearly instead of being overwritten
- existing unrelated workstation role responsibilities remain wired once

Live validation after implementation should run:

```bash
uv run --locked ansible-playbook site.yml --limit workstation --check
```

When applying from inside the workstation itself, include the existing self-management override:

```bash
uv run --locked ansible-playbook site.yml -e proxmox_skip_self=false --limit workstation
```

---

## Deferred

- A reusable persistent-home capability group.
- Persisting shell history, MCP state, skills, or caches beyond the configured links.
- Dedicated per-workstation Proxmox bind mount instead of using the existing `/ephemeral` mount.
- Backup or replication policy for the persistent home directory.
- Cleanup behavior when `workstation_persistent_home_enabled` is disabled after symlinks already exist.
- Automated migration or quarantine for pre-existing real `~/.claude` or `~/.codex` paths.
