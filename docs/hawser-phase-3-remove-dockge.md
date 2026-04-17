# Phase 3: Remove Dockge From The Docker Host Baseline

## Goal

Delete Dockge completely after Hawser Standard is stable across the remote fleet, so the supported interactive Docker control plane is:

- Dockhand on `portal`
- Hawser Standard on remote Docker LXCs

Success criteria:

- Docker hosts no longer provision or start Dockge
- `dockge.local.faviann.com` no longer routes
- Dockge files and host data are removed
- repo docs no longer present Dockge as part of the baseline

## Preconditions

Do not start this phase until Phase 2 is complete and stable.

Required preconditions:

- Hawser Standard is running successfully on all remote Docker LXCs
- Dockhand is the accepted operational UI
- nobody still depends on Dockge as a break-glass interface

## Required Repo Changes

### Remove Dockge Provisioning

- Delete the Dockge copy/start path from `playbooks/roles/config/lxc_docker_environment/tasks/main.yml`.
- Remove:
  - copy of `templates/files/dockge/`
  - Dockge stat check
  - Dockge running check
  - Dockge startup task
  - Dockge status debug output
- Remove the `dockge_compose_dir` internal contract field if nothing else uses it.
- Update `playbooks/roles/config/lxc_docker_environment/defaults/main.yml` to remove `lxc_docker_env_dockge_compose_dir`.
- Remove the `Restart Dockge` handler from `playbooks/roles/config/lxc_docker_environment/handlers/main.yml`.

### Remove Dockge Assets

- Remove the Dockge template payload under:
  - `playbooks/roles/config/lxc_docker_environment/templates/files/dockge/compose.yml`
  - any committed Dockge data files in that same template directory if they are no longer used
- Add explicit cleanup logic so existing Dockge directories are removed from hosts:
  - `/conf/docker/dockge`
  - corresponding bind-mounted shared path under `/shared/<host>/dockge`
- Stop Dockge cleanly before deleting its directory:
  - `docker compose down --remove-orphans`
  - then remove the directory

### Remove Dockge References From Reporting

- Update `playbooks/roles/config/lxc_docker_environment/tasks/managed_assets.yml` so `lxc_stack_sync_managed_assets` no longer publishes `dockge_copy`.
- Update `playbooks/roles/config/lxc_stack_sync/tasks/report.yml` to remove `managed_assets.dockge_copy` from the deployment-report aggregation.

### Remove Dockge Exposure

- Delete the `dockge` router and service from:
  - `stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml`
- After deployment, `dockge.local.faviann.com` must no longer resolve through Traefik.

### Remove Dockge Docs

- Update `playbooks/roles/config/lxc_docker_environment/templates/files/README.md` to remove the `Dockge` section and directory tree entries.
- Update any repo docs that still describe Dockge as a deployed baseline.
- `stacks/README.md` currently says Dockge is separate from repo-managed stacks; revise this wording so it no longer implies Dockge is part of the supported model.

## Commands To Run

Static checks:

```bash
ansible-playbook site.yml --syntax-check
rg -n "dockge|Dockge" docs playbooks stacks inventory
```

Dry run and deploy:

```bash
ansible-playbook site.yml --limit auth,public,seedbox,servarr,jellyfin,portal --check
ansible-playbook site.yml --limit auth,public,seedbox,servarr,jellyfin,portal
```

Runtime verification:

```bash
ansible -i inventory/hosts.yml auth,public,seedbox,servarr,jellyfin,portal -m shell -a 'docker ps --filter name=dockge'
ansible -i inventory/hosts.yml auth,public,seedbox,servarr,jellyfin,portal -m shell -a 'test ! -d /conf/docker/dockge && echo absent'
```

## Acceptance Criteria

- no host runs a `dockge` container
- no host retains `/conf/docker/dockge`
- no managed shared directory retains Dockge data
- `dockge.local.faviann.com` no longer routes
- no active role tasks, handlers, defaults, or docs still reference Dockge as part of the baseline
- Hawser and Dockhand remain fully functional after Dockge removal

## Out Of Scope

- Changing the Hawser design
- Changing Dockhand exposure on `portal`
- Replacing Dockge with another host-local fallback UI

## Handoff Notes

- This phase is destructive by design; do not implement it until the operator confirms the fallback UI is no longer needed.
- Remove everything, not just the running container. The goal is a clean baseline with no dormant Dockge payload left behind.
