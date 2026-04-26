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

### [DES-010] Navidrome blueprint PolicyBinding target is environment-specific — breaks on fresh Authentik deploy
- **Category**: design
- **Location**: `stacks/auth/auth/appdata/authentik/blueprints/27-navidrome-password-change-sync.yaml`
- **Context**: Discovered while debugging `authentik_blueprint_sync.py apply` which failed with `repo-auth-navidrome-password-change-sync entered error state` every run since the blueprint was added.
- **Added**: 2026-04-26
- **Status**: open

#### What the blueprint does
It creates a `PolicyBinding` that attaches the `navidrome-registration-sync-policy` expression policy to the `default-password-change-prompt` stage within the `default-password-change` flow. This ensures the navidrome password sync policy fires whenever a user changes their password via Authentik.

#### The root cause (deep)
`FlowStageBinding` in Authentik has **two different UUIDs** that serve different roles:

| field | value (this instance) | role |
|---|---|---|
| `fsb_uuid` | `e910a6ca-b41a-4cc3-bb07-685845f982d6` | PK of the FlowStageBinding row (child table) |
| `policybindingmodel_ptr_id` | `19fc00cb-14e2-4aed-a686-1e05d15e84e8` | PK of the PolicyBindingModel row (parent table) |

`PolicyBinding.target_id` stores `policybindingmodel_ptr_id` (`19fc00cb`), **not** `fsb_uuid`.

Authentik's `!Find` tag resolves via `Find.resolve()` in `/authentik/blueprints/v1/common.py`:
```python
def resolve(self, entry, blueprint) -> Any:
    instance = self._get_instance(entry, blueprint)
    if instance:
        return instance.pk   # ← always returns instance.pk
    return None
```
For `FlowStageBinding`, `instance.pk = fsb_uuid = e910a6ca`. So `!Find [authentik_flows.flowstagebinding, [pk, e910a6ca]]` returns `e910a6ca` — the **wrong** UUID for use as `PolicyBinding.target_id`. This causes the importer to miss the existing binding and try to create a duplicate, which hits the FK constraint (`e910a6ca` is not a valid `PolicyBindingModel.pbm_uuid`) and sets the blueprint to error state.

#### The current workaround (fragile)
The blueprint now uses:
```yaml
target: !Find [authentik_policies.policybindingmodel, [pbm_uuid, 19fc00cb-14e2-4aed-a686-1e05d15e84e8]]
```
`PolicyBindingModel.pk = pbm_uuid = 19fc00cb`, which IS the correct value for `target_id`. This resolves correctly **on this specific Authentik instance** because `19fc00cb` is hardcoded. On a fresh Authentik deploy, `default-password-change-prompt`'s FlowStageBinding would be recreated with a new `policybindingmodel_ptr_id`, and the `!Find` would return `None`.

#### Why `PolicyBindingModel` is not "allowed" but still works
`is_model_allowed(PolicyBindingModel)` returns `False` — it cannot be an *entry* model (you can't use it as the `model:` field in a blueprint entry). However, `Find._get_instance()` never calls `is_model_allowed`, so it is safe to use as a `!Find` lookup target. This was verified in the running container.

#### Key UUIDs (only valid on this instance)
- `FlowStageBinding.fsb_uuid` (wrong for FK): `e910a6ca-b41a-4cc3-bb07-685845f982d6`
- `FlowStageBinding.policybindingmodel_ptr_id` (correct for FK, hardcoded in blueprint): `19fc00cb-14e2-4aed-a686-1e05d15e84e8`
- `PolicyBinding.pk` (the binding itself): `b6d535d8-0368-4efb-a07c-fcb67ad7818b`
- `ExpressionPolicy.pk` (navidrome-registration-sync-policy): `e0800a3a-93f6-4c1e-a9eb-29f69a295132`

#### Options for a proper fix

**Option A — Remove the blueprint entry, manage binding manually**
The binding is set-and-forget. On a fresh deploy, a human creates it once via the Authentik UI (Policy Bindings on the `default-password-change` flow → bind `navidrome-registration-sync-policy` to the `default-password-change-prompt` stage binding at order 0). Document the step in the ADR. Zero brittleness once done; no blueprint footgun.

**Option B — Accept the limitation, document it**
Keep the blueprint but add a comment block with both UUIDs and the "run `authentik_blueprint_sync.py export` then update pbm_uuid after fresh deploy" instruction. Acceptable if fresh deploys are very rare.

**Option C — File upstream with Authentik**
`Find.resolve()` returning `fsb_uuid` instead of `policybindingmodel_ptr_id` when the result is used as a `PolicyBinding.target` is arguably a bug. A fix in Authentik would make `!Find [flowstagebinding, ...]` return the correct PK for FK use. Upside: proper fix. Downside: external dependency, uncertain timeline.

**Option D — Derive pbm_uuid dynamically via the blueprint context or a custom script**
The sync script (`authentik_blueprint_sync.py`) already talks to the Authentik API. It could resolve the FSB's `pbm_uuid` at render time and bake it into the blueprint YAML. This would make the blueprint portable but adds complexity to the script and requires re-running the script on fresh deploys before any Authentik restart.

**Recommended direction**: Option A if the navidrome setup is considered stable infrastructure; Option D if portability is a hard requirement.

- **Added**: 2026-04-26
- **Status**: open

## In Progress

## Done
