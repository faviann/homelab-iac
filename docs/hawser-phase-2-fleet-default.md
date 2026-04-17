# Phase 2: Promote Hawser Standard To The Remote Default

## Goal

Remove the pilot-only shape and make `Hawser Standard` part of the default contract for all non-`portal` Docker LXCs.

Remote fleet:

- `auth`
- `public`
- `seedbox`
- `servarr`
- `jellyfin`

Success criteria:

- all five remote Docker LXCs run Hawser by default
- `portal` does not run Hawser
- all five Dockhand remote environments connect successfully
- the temporary pilot toggle is deleted from the steady-state design

## Preconditions

Do not start this phase until Phase 1 is complete and verified on `servarr`.

Required preconditions:

- Phase 1 implementation merged or available in the harness
- shared Hawser token stored in vault
- a working Dockhand Standard environment exists for `servarr`
- Standard-mode remote operations from Dockhand have already been proven on `servarr`

## Required Repo Changes

### Inventory and Variable Model

- Remove `dockhand_hawser_enabled` from the long-term `cap_docker` contract.
- Replace the pilot-specific behavior with an implicit rule:
  - if host is in `cap_docker`
  - and host is not `portal`
  - then Hawser is included automatically
- Implement the exclusion using existing inventory truth:
  - prefer `portal_instance: true` as the `portal` marker
  - do not add a new long-term per-host Hawser flag
- Update `playbooks/roles/config/lxc_docker_environment/meta/argument_specs.yml` to remove the temporary boolean from the public interface once the pilot is complete.
- Update `inventory/README.md` and `docs/inventory-structure-guide.md` to describe Hawser as part of the remote Docker host baseline, with `portal` as the only exception.

### Role Logic

- Update `playbooks/roles/config/lxc_docker_environment/tasks/managed_assets.yml` so Hawser inclusion is computed automatically for non-`portal` Docker hosts.
- The condition should be decision-complete:
  - `docker_agents_enabled` must still govern whether the overall managed stack exists
  - Hawser must render on all Docker hosts except `portal`
  - Hawser must fail closed if `dockhand_hawser_token` is missing or empty on any remote Docker host
- Keep the Hawser stack directory creation for remote hosts.
- Ensure `portal` never renders Hawser even though it remains in `cap_docker`.

### Docs

- Update `docs/stacks-docker-agents.md`:
  - Hawser is part of the default remote Docker baseline
  - `portal` is the exception
- Update `playbooks/roles/config/lxc_docker_environment/templates/files/README.md` to describe the steady-state Standard-mode behavior.
- If any docs still refer to Hawser as optional or pilot-gated, remove that wording.

## Manual Dockhand Setup

Before deployment, create the remaining four Dockhand environments on `portal`.

Each environment is `Hawser Standard`, `http`, port `2376`, and uses the same shared token:

- `auth` → `auth.faviann.vms`
- `public` → `public.faviann.vms`
- `seedbox` → `seedbox.faviann.vms`
- `jellyfin` → `jellyfin.faviann.vms`

Keep the existing `servarr` environment from Phase 1.

## Commands To Run

Repo and inventory checks:

```bash
ansible-playbook site.yml --syntax-check
ansible-inventory -i inventory/hosts.yml --host auth --yaml
ansible-inventory -i inventory/hosts.yml --host public --yaml
ansible-inventory -i inventory/hosts.yml --host seedbox --yaml
ansible-inventory -i inventory/hosts.yml --host jellyfin --yaml
ansible-inventory -i inventory/hosts.yml --host portal --yaml
```

Dry run and deploy:

```bash
ansible-playbook site.yml --limit auth,public,seedbox,jellyfin --check
ansible-playbook site.yml --limit auth,public,seedbox,jellyfin
```

Runtime spot checks:

```bash
ansible -i inventory/hosts.yml auth,public,seedbox,jellyfin -m shell -a 'cd /conf/docker/stacks/docker-agents && docker compose ps'
ansible -i inventory/hosts.yml auth,public,seedbox,jellyfin -m shell -a 'ss -ltnp | grep 2376'
```

## Acceptance Criteria

- `auth`, `public`, `seedbox`, `servarr`, and `jellyfin` all run Hawser automatically
- `portal` does not run Hawser
- all five remote environments connect in Dockhand
- no host requires a long-term Hawser feature flag
- no port conflicts appear on `2376`
- existing repo-managed stacks remain owned by Ansible
- Dockge remains untouched and functional

## Out Of Scope

- Removing Dockge
- Adding TLS to Hawser Standard
- Moving stack authority from Ansible to Dockhand

## Handoff Notes

- Preserve the hidden `/conf/docker/dockhand-stacks` escape hatch, but do not document it as a normal workflow.
- If the implementer needs a transition step, it is acceptable to keep the old boolean only long enough to perform the code change, but the merged steady-state design must not depend on it.
