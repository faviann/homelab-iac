# Backlog

## [BUG-004] Workstation regression fixtures need sudo-free role boundaries
- **Category**: bug
- **Location**: `tests/regression/fixtures/workstation_*` and `playbooks/roles/config/lxc_workstation_baseline/`
- **Context**: Some workstation regression tests include the full baseline role and can hit system-level tasks such as locale files, systemd cleanup, or Bitwarden CLI installation that require root/sudo permissions. The fixtures should either include only the contract-relevant task files or redirect/mock privileged paths so they run reliably as an unprivileged developer.
- **Added**: 2026-05-13
- **Status**: open

## [DES-003] Add Hardcover metadata provider to CWA
- **Category**: design
- **Location**: `stacks/` (CWA stack)
- **Context**: User wants to use Hardcover as a metadata source in Comic Wrapper App (CWA); requires configuring the provider integration.
- **Added**: 2026-04-18

## [DES-006] Configure OIDC for Storyteller
- **Category**: design
- **Location**: `stacks/public/storyteller/`
- **Context**: Storyteller stack was deployed without OIDC; needs Authentik provider and application wired up like other SSO-enabled stacks.
- **Added**: 2026-04-19

## [BUG-003] dockhand Ansible health check fails with 401 after DISABLE_LOCAL_LOGIN is set
- **Category**: bug
- **Location**: `playbooks/roles/` (dockhand lifecycle/health check task)
- **Context**: Post-deploy task hits `http://127.0.0.1:3004/api/environments` without credentials; returns 401 once local login is disabled. Deploy still applies the change but exits non-zero.
- **Added**: 2026-05-06
- **Status**: open

## [BUG-002] authentik_blueprint_sync role deploys stale 80-oidc-apps.yaml on first run after manifest change
- **Category**: bug
- **Location**: `playbooks/roles/config/authentik_blueprint_sync`
- **Context**: Ansible syncs the rendered `80-oidc-apps.yaml` to the container before the apply script regenerates `80-oidc-apps.yaml.j2` from `oidc-apps.yaml` — so committing only `oidc-apps.yaml` pushes stale blueprint content on the first deploy and Authentik never sees the new entries. Fix: run the generate step before the file sync task in the role, or run a second deploy as workaround.
- **Added**: 2026-05-06
- **Status**: open

## [BUG-001] ansible-inventory host view exposes vaulted values
- **Category**: bug
- **Location**: `inventory/` verification workflow
- **Context**: While verifying workstation bootstrap, `uv run --locked ansible-inventory -i inventory/hosts.yml --host workstation --yaml` emitted decrypted unrelated secret vars, making that verification step unsafe to paste or relay verbatim.
- **Added**: 2026-04-29

### [OTH-002] Create Hermes stack on workstation
- **Category**: other
- **Location**: `stacks/workstation/hermes/`
- **Context**: Cortex v1 requires Hermes as the on-demand reasoning agent. Depends on n8n stack (OTH-001) being up and MCP configured first.
- **Added**: 2026-05-03
- **Status**: open
