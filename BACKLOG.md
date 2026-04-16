# Backlog

## Open

### [BUG-001] Feature reconciliation cannot remove stale pct features
- **Category**: bug
- **Location**: `playbooks/roles/infrastructure/proxmox_lxc_host_config/tasks/features.yml`
- **Context**: Discovered while migrating host config to `proxmox_lxc_contract.host_config`; the role unions current and desired features, so removing a feature from inventory does not remove it from the container.
- **Added**: 2026-04-16
- **Status**: open

### [BUG-002] Host config file edits do not surface restart requirements
- **Category**: bug
- **Location**: `playbooks/roles/infrastructure/proxmox_lxc_host_config/tasks/config_file.yml`
- **Context**: Discovered while reviewing the contract refactor; bind mount and idmap updates rewrite `/etc/pve/lxc/*.conf` without warning or coordinating restart behavior for running containers.
- **Added**: 2026-04-16
- **Status**: open

## In Progress

## Done

### [DES-001] Remove dead public-wildcard-forwardauth provider
- **Category**: design
- **Location**: `stacks/auth/auth/appdata/authentik/blueprints/30-providers.yaml`, `stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml`, `stacks/auth/auth/appdata/authentik/blueprints/60-outposts.yaml`
- **Context**: Discovered while planning RomM OIDC — the provider's `skip_path_regex` matches every path on `public.faviann.com`, making it a no-op; none of the public services (RomM, Mealie, it-tools) reference the Authentik middleware in their Traefik labels anyway. Dead weight in blueprints and outpost enrollment.
- **Added**: 2026-04-13
- **Completed**: 2026-04-13
- **Status**: done
