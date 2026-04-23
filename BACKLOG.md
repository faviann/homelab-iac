# Backlog

## Open

### [TEST-001] Add sandbox-safe Ansible guardrail test tier
- **Category**: missing-test
- **Location**: `tests/`, `tests/regression/`, `playbooks/roles/config/lxc_docker_environment/`
- **Context**: Codex sandbox blocks Python multiprocessing semaphores used by `ansible-playbook`, so subagents need static/in-process tests for key Ansible guardrails while full playbook regressions remain integration tests. This was discovered while investigating `tests/regression/test_missing_cap_docker_fails_clearly.py` after project-local Ansible temp files were fixed.
- **Research summary**:
  - Host `/dev/shm` works outside the sandbox; the failure is sandbox-specific.
  - Inside the sandbox, Python `multiprocessing.Queue`, `SimpleQueue`, `Lock`, and `Semaphore` fail with `PermissionError(13)`.
  - Ansible 2.20.1 normal task execution always constructs `TaskQueueManager`, which creates a multiprocessing `FinalQueue()` before forks, strategy, callbacks, or task logic matter.
  - Tested knobs did not avoid the failure: `-f 1`, `ANSIBLE_FORKS=1`, strategy changes, callback disabling, `TMPDIR`, `ANSIBLE_LOCAL_TEMP`, and multiprocessing start-method changes.
  - `ansible-playbook --syntax-check` and `--list-tasks` avoid task execution and can run, but they are not behavior regressions.
  - The missing-cap Docker regression also has a separate fidelity issue: `include_role` runs `config/lxc_docker_environment` role dependencies, including `config/lxc_base_system`, before the role's first task assertion can fail.
- **Desired direction**:
  - Keep full `ansible-playbook` regression wrappers as integration tests that may require unsandboxed/escalated execution.
  - Add a sandbox-safe static or in-process test subset that subagents can run in worktrees without `/dev/shm`.
  - Start with the missing-cap Docker guardrail: parse `playbooks/roles/config/lxc_docker_environment/tasks/main.yml`, `meta/argument_specs.yml`, and `inventory/group_vars/cap_docker/vars.yml`.
  - Assert the Docker capability guard is first, checks `docker_user`, `docker_uid`, and `docker_gid`, mentions `cap_docker`, and precedes package/fact tasks.
  - Assert the role argument spec rejects missing Docker identity inputs and `cap_docker` group vars define the required values.
  - Document the two-tier test policy: sandbox-safe static/in-process tests for subagents by default; full Ansible playbook regressions for integration verification.
- **Added**: 2026-04-22
- **Status**: open

### [DES-003] Add Hardcover metadata provider to CWA
- **Category**: design
- **Location**: `stacks/` (CWA stack)
- **Context**: User wants to use Hardcover as a metadata source in Comic Wrapper App (CWA); requires configuring the provider integration.
- **Added**: 2026-04-18
- **Status**: open

### [DES-004] Add Komf stack for Komga/Kavita metadata fetching
- **Category**: design
- **Location**: `stacks/` (new stack)
- **Context**: Komf (https://github.com/Snd-R/komf) is a metadata fetcher/updater for Komga and Kavita; user wants it deployed as a stack.
- **Added**: 2026-04-18
- **Status**: open

### [DES-006] Configure OIDC for Storyteller
- **Category**: design
- **Location**: `stacks/public/storyteller/`
- **Context**: Storyteller stack was deployed without OIDC; needs Authentik provider and application wired up like other SSO-enabled stacks.
- **Added**: 2026-04-19
- **Status**: open

### [DES-009] Deploy GitHub public keys to all LXCs for non-root SSH access
- **Category**: design
- **Location**: `playbooks/roles/config/lxc_github_keys/`, `inventory/group_vars/lxcs/vars.yml`, `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml`
- **Context**: User wants to SSH into any LXC as a non-root user using their GitHub SSH keys.
- **Added**: 2026-04-23
- **Status**: done
- **Completed**: 2026-04-23
- **Resolution**: New `config/lxc_github_keys` role extracts key-fetch logic from `lxc_workstation_baseline` and is wired unconditionally into the configure play. `lxc_github_users: [faviann]` set in `group_vars/lxcs/`. Target user resolves as `docker_user | default(lxc_ssh_user)` — `faviann` on all LXCs (cap_docker group updated from `dockeruser`).

## In Progress

### [DES-008] Normalize legacy cross-stack Docker network names to shared
- **Category**: design
- **Location**: `inventory/host_vars/portal.yml`, `inventory/host_vars/servarr.yml`, `inventory/host_vars/auth.yml`, `inventory/host_vars/public.yml`, `stacks/portal/`, `stacks/servarr/`, `stacks/auth/auth/`, `stacks/public/storyteller/`, `stacks/public/romm/`, `stacks/public/readmeabook/`
- **Context**: Host-local cross-stack Docker networks use inconsistent legacy names on portal/auth/public and servarr. They represent the same LXC-local shared-network pattern and should be normalized to `shared` where the network is actually needed.
- **Rework checklist**:
  - `portal`: rename `lxc_docker_env_external_networks`, `stacks/portal/traefik3`, `portal-entry`, `dockhand`, and homepage stacks from `proxy` to `shared`.
  - `servarr`: rename `inventory/host_vars/servarr.yml` and all stacks currently using the legacy Servarr network name to `shared`.
  - `auth`: verify `stacks/auth/auth/compose.override.yaml.j2` needs a shared network; if yes, rename `proxy` to `shared`, otherwise drop the network and `traefik.docker.network`.
  - `public`: verify `storyteller`, `romm`, and `readmeabook` need a shared network; if yes, rename `proxy` to `shared`, otherwise drop the network and rely on published ports for label-exported routing.
  - Update stack READMEs after compose/host-var changes so ownership sections match the actual network contract.
- **Added**: 2026-04-23
- **Status**: in-progress

### [SEC-001] Harden portal Traefik Docker socket access
- **Category**: security
- **Location**: `stacks/portal/traefik3/compose.yaml`, `stacks/portal/traefik3/appdata/traefik3/config/traefik.yaml`, `docs/stacks-docker-agents.md`
- **Context**: `portal/traefik3` currently gives Traefik direct read-only access to the host Docker socket with `/run/docker.sock:/run/docker.sock:ro`, and Traefik's Docker provider points at `unix:///run/docker.sock`. This works, but direct Docker socket access is broader than ideal. A socket proxy could restrict Traefik to the Docker API capabilities it actually needs for provider discovery.
- **Why out of scope for stack normalization**: This is a security hardening/design task, not a normalization task. If permissions are too narrow, Traefik may start but fail to discover Docker labels, breaking routes local to the reverse-proxy host. It should be designed, tested, and deployed separately.
- **Initial direction**: Prefer a dedicated Traefik socket proxy over reusing the managed `docker-metadata-proxy`. The existing managed proxy is primarily for Homepage and `traefik-kop`, and may not expose the Docker event stream Traefik needs for `watch: true`. A dedicated proxy keeps the permission set and network dependency local to the Traefik stack.
- **Investigation checklist**:
  - Confirm Traefik Docker provider's minimum Docker API permissions for `watch: true`, container label discovery, and network inspection.
  - Confirm whether `tecnativa/docker-socket-proxy` can expose only those capabilities, including Docker events if required.
  - Decide whether Traefik can use an internal stack network such as `traefik`, or whether a new internal network name would be clearer.
  - Add a `traefik-docker-socket-proxy` service that mounts `/run/docker.sock` and exposes only the required API subset.
  - Change Traefik's Docker provider endpoint from `unix:///run/docker.sock` to `tcp://traefik-docker-socket-proxy:2375`.
  - Remove the direct Docker socket mount from the Traefik container after the proxy path is verified.
- **Verification checklist**:
  - `docker compose -f stacks/portal/traefik3/compose.yaml config --no-interpolate`
  - `ansible-playbook site.yml --limit portal -e stack_filter=traefik3 --check`
  - Deploy in a focused change window, then verify portal-local Docker-label routes are still discovered.
  - Verify Redis/traefik-kop discovered routes from label-source hosts still work.
  - Verify HTTP to HTTPS redirect, HTTPS routes, Authentik forwardAuth middleware, dashboard access, and ACME certificate renewal/storage still work.
  - Check Traefik logs for Docker provider watch/list/inspect errors after deployment.
- **Added**: 2026-04-21
- **Status**: in-progress

## Done

### [TD-001] Rename vault_portal_diun_discord_webhook in vault
- **Category**: tech-debt
- **Location**: `inventory/group_vars/all/vault.yml`
- **Context**: Vault key retained its Diun-era name after Diun was removed; now backs `dockhand_discord_webhook_url`. Rename to `vault_dockhand_discord_webhook_url` for clarity.
- **Added**: 2026-04-17
- **Status**: done
- **Completed**: 2026-04-23

### [DES-005] Move stack-specific lxc_docker_env_* vars from inventory into stacks
- **Category**: design
- **Location**: `inventory/host_vars/auth.yml`, `inventory/host_vars/public.yml`, `inventory/host_vars/servarr.yml`, `inventory/host_vars/portal.yml`, `playbooks/roles/config/lxc_docker_environment/`
- **Context**: `lxc_docker_env_path_ownership_overrides` and `lxc_docker_env_external_networks` are both host-level lists that aggregate stack-specific needs; co-locating them with the stacks they belong to would improve cohesion and reduce inventory bloat.
- **Added**: 2026-04-19
- **Status**: done
- **Completed**: 2026-04-23
- **Resolution**: Closed as no longer pertinent.

### [DES-007] create-stack skill omits Traefik port label for non-standard ports
- **Category**: design
- **Location**: `stacks/README.md`, `docs/stacks-networking.md`, `.agents/skills/create-stack/SKILL.md`
- **Context**: `stacks/servarr/radarr-anime/compose.yaml` and `stacks/servarr/sonarr-anime/compose.yaml` now include `traefik.http.services.<name>.loadbalancer.server.port` labels using the host ports `7879` and `8990`. Documentation now states that label-exported routes, such as routes copied by `traefik-kop`, must use the reachable host port in this label when the published host port differs from the container port.
- **Checked**: 2026-04-23
- **Added**: 2026-04-19
- **Status**: done
- **Completed**: 2026-04-23
