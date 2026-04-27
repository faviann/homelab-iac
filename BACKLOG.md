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

## Done

### [DES-010] Navidrome blueprint PolicyBinding target is environment-specific — breaks on fresh Authentik deploy
- **Category**: design
- **Location**: `stacks/auth/auth/appdata/authentik/blueprints/27-navidrome-password-change-sync.yaml`
- **Context**: Discovered while debugging `authentik_blueprint_sync.py apply` which failed with `repo-auth-navidrome-password-change-sync entered error state` every run since the blueprint was added.
- **Added**: 2026-04-26
- **Status**: done
- **Completed**: 2026-04-27
- **Resolution**: Replaced hardcoded pbm_uuid with stable !Find via stage__name Django traversal — no dynamic generation, no bootstrap step
