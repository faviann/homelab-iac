# Workstation Agent State Persistence - Design

**Date:** 2026-04-28  
**Status:** Approved  
**Scope:** Preserve selected Claude/Codex CLI comfort state across intentional workstation LXC rebuilds.

---

## Problem

The `workstation` LXC is managed as cattle by Ansible. Rebuilding it keeps the compute environment clean, but currently also removes local agent CLI state such as Claude and Codex session history/config. That is not catastrophic because durable project knowledge belongs in Git, vault-backed secrets, chezmoi-managed dotfiles, and the LLM wiki, but losing CLI continuity during an intentional rebuild is inconvenient.

The goal is to preserve useful agent continuity without turning the whole workstation home directory into a pet.

---

## Design

Use the existing `/ephemeral` bind mount as local host-persistent comfort-state storage for selected agent dotdirs.

Host/LXC-visible persistent state:

```text
/ephemeral/workstation/agent-state/
  claude/
  codex/
```

Workstation user home:

```text
/home/<workstation_user>/.claude -> /ephemeral/workstation/agent-state/claude
/home/<workstation_user>/.codex  -> /ephemeral/workstation/agent-state/codex
```

This state survives intentional LXC deletion/recreation as long as the Proxmox host-side `/ephemeral` storage remains intact. It is not the authoritative memory layer and does not need remote-first sync.

---

## Inventory Contract

Keep this behavior under the existing workstation role instead of creating a new capability group. Agent CLI continuity is currently a workstation-only concern, and a reusable `cap_agent_state` group would add abstraction before there is a second consumer.

Add workstation role variables:

```yaml
workstation_agent_state_enabled: true
workstation_agent_state_root: /ephemeral/workstation/agent-state
workstation_agent_state_links:
  - name: claude
    path: "{{ workstation_home }}/.claude"
    target: "{{ workstation_agent_state_root }}/claude"
  - name: codex
    path: "{{ workstation_home }}/.codex"
    target: "{{ workstation_agent_state_root }}/codex"
```

`workstation_agent_state_enabled: false` is the escape hatch for a deliberately clean rebuild.

---

## Role Behavior

`config/lxc_workstation_baseline` should:

1. Create `workstation_agent_state_root` and each agent state target directory.
2. Own those directories with `workstation_uid` and `workstation_gid`, matching the existing workstation user contract.
3. Set restrictive permissions, preferably `0700`.
4. Create symlinks from the workstation user's home into the persistent state directories.
5. Avoid persisting the whole home directory.
6. Avoid copying, printing, or managing secrets directly.

If a target home path already exists as a symlink to the desired target, the role should be a no-op.

If a target home path exists as a real file or directory, the implementation should fail clearly or move it aside in a conservative, deterministic way. Silent overwrite is not acceptable because these directories may contain active CLI state.

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
- future selected agent-local state, only when explicitly added

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

That is acceptable for v1 because Claude/Codex local state is convenient but not authoritative. If losing this state becomes more than inconvenient, the next design step is a local backup or ZFS replication policy for `/ephemeral/workstation/agent-state`.

---

## Testing

Add focused tests for the workstation baseline role contract:

- defaults include the agent state variables
- role tasks create agent-state directories when enabled
- role tasks create `~/.claude` and `~/.codex` symlinks
- disabling `workstation_agent_state_enabled` skips the behavior
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

- A reusable `cap_agent_state` capability group.
- Persisting shell history, MCP state, or skills beyond Claude/Codex.
- Dedicated per-workstation Proxmox bind mount instead of using the existing `/ephemeral` mount.
- Backup or replication policy for the agent-state directory.
