# Phase 1: Hawser Standard Pilot On `servarr`

## Goal

Prove the end-to-end `Hawser Standard` design on one remote Docker LXC before changing the fleet baseline. This phase must leave the rest of the homelab unchanged.

Pilot target: `servarr`

Success criteria:

- `servarr` runs Hawser in `docker-agents`
- Hawser listens on `http://servarr.faviann.vms:2376`
- Dockhand on `portal` connects to `servarr` as a `Hawser Standard` environment
- Basic remote operations work from Dockhand
- No Dockge changes are made in this phase

## Current State To Change

The repo currently has a partial `Hawser Edge` implementation:

- `inventory/group_vars/cap_docker/vars.yml` still defines `dockhand_hawser_server_url`
- `playbooks/roles/config/lxc_docker_environment/templates/files/docker-agents/compose.yml.j2` renders Hawser with `DOCKHAND_SERVER_URL`
- `playbooks/roles/config/lxc_docker_environment/templates/files/docker-agents/.env.j2` renders Edge-only variables
- `playbooks/roles/config/lxc_docker_environment/meta/argument_specs.yml` describes Hawser as Edge-specific
- the pilot gate already exists as `dockhand_hawser_enabled`

This phase repurposes that temporary boolean gate for `servarr` only.

## Required Repo Changes

### Inventory and Vault

- Replace the per-host `dockhand_hawser_token` concept with one shared token variable for the pilot.
- Add one shared vault-backed variable reference in `inventory/group_vars/cap_docker/vars.yml`:
  - `dockhand_hawser_token: "{{ vault_dockhand_hawser_token }}"`
- Keep `dockhand_hawser_enabled: false` in `cap_docker` as the temporary pilot gate.
- Set `dockhand_hawser_enabled: true` only in `inventory/host_vars/servarr.yml`.
- Remove `dockhand_hawser_token` from host vars where it was added earlier:
  - `inventory/host_vars/auth.yml`
  - `inventory/host_vars/jellyfin.yml`
  - `inventory/host_vars/public.yml`
  - `inventory/host_vars/seedbox.yml`
  - `inventory/host_vars/servarr.yml`
- Update `inventory/group_vars/all/vault.yml.example` to replace the five host-specific Hawser token examples with one:
  - `vault_dockhand_hawser_token: "REPLACE_ME"`

### Docker-Agent Templates

- Convert Hawser from Edge mode to Standard mode in `playbooks/roles/config/lxc_docker_environment/templates/files/docker-agents/compose.yml.j2`.
- Hawser service definition must:
  - expose host port `2376:2376`
  - keep `/var/run/docker.sock:/var/run/docker.sock`
  - keep `{{ dockhand_hawser_stacks_dir }}:{{ dockhand_hawser_stacks_dir }}`
  - remove `DOCKHAND_SERVER_URL`
  - set:
    - `PORT=2376`
    - `BIND_ADDRESS=0.0.0.0`
    - `TOKEN=${TOKEN}`
    - `DOCKER_SOCKET=/var/run/docker.sock`
    - `STACKS_DIR={{ dockhand_hawser_stacks_dir }}`
    - `AGENT_NAME={{ inventory_hostname }}`
    - `LOG_LEVEL=info`
- Update `playbooks/roles/config/lxc_docker_environment/templates/files/docker-agents/.env.j2`:
  - keep `REDISURL` and `DOMAIN` only for `traefik_kop_enabled`
  - remove `DOCKHAND_SERVER_URL`
  - render only `TOKEN={{ dockhand_hawser_token | replace('$', '$$') }}` for Hawser

### Role Defaults and Validation

- Remove the now-unused `dockhand_hawser_server_url` from:
  - `inventory/group_vars/cap_docker/vars.yml`
  - `playbooks/roles/config/lxc_docker_environment/meta/argument_specs.yml`
  - `playbooks/roles/config/lxc_docker_environment/tasks/managed_assets.yml`
- Rewrite the Hawser validation in `managed_assets.yml` so the pilot fails closed when:
  - `dockhand_hawser_enabled` is true
  - `dockhand_hawser_token` is undefined or empty
- Keep `lxc_docker_env_dockhand_hawser_stacks_source_dir` and the directory creation logic unchanged.

### Docs

- Update `docs/stacks-docker-agents.md` so Hawser is described as a Standard-mode remote agent, not Edge.
- Update any wording in `playbooks/roles/config/lxc_docker_environment/templates/files/README.md` that still suggests `DOCKHAND_SERVER_URL` is part of the steady-state design.

## Manual Dockhand Setup

On the Dockhand UI running on `portal`:

1. Go to `Settings > Environments`.
2. Create one new environment for `servarr`.
3. Connection type: `Hawser Standard`.
4. Host: `servarr.faviann.vms`
5. Port: `2376`
6. Protocol: `http`
7. Token: use the shared Hawser token value that will also be stored in vault.

This phase does not create UI state automatically. The human operator must do this before deployment if the test harness expects a healthy end-to-end connection on first boot.

## Commands To Run

Implementation verification:

```bash
ansible-playbook site.yml --syntax-check
ansible-inventory -i inventory/hosts.yml --host servarr --yaml
ansible-playbook site.yml --limit servarr --check
ansible-playbook site.yml --limit servarr
```

Runtime verification after deploy:

```bash
ansible -i inventory/hosts.yml servarr -m shell -a 'cd /conf/docker/stacks/docker-agents && docker compose ps'
ansible -i inventory/hosts.yml servarr -m shell -a 'ss -ltnp | grep 2376'
ansible -i inventory/hosts.yml servarr -m shell -a 'docker ps --filter name=hawser'
```

## Acceptance Criteria

- `docker-agents` on `servarr` contains a running `hawser` service
- `servarr` listens on port `2376`
- Dockhand shows the `servarr` environment as connected
- At least one remote action from Dockhand works against `servarr`:
  - view containers
  - view logs
  - restart a safe container
- `portal`, `auth`, `public`, `seedbox`, and `jellyfin` are unchanged by this phase
- Dockge is still present and functional

## Out Of Scope

- Making Hawser the fleet default
- Removing Dockge
- Changing `portal` to run Hawser
- Adding TLS to Hawser Standard

## Handoff Notes

- Do not delete the temporary `dockhand_hawser_enabled` boolean in this phase.
- Do not change Dockge behavior in this phase.
- If the pilot fails, fix the Standard-mode implementation first; do not fall back to Edge.
