# SSH Access and Key Injection Report

Date: 2026-04-16
Plan: 2026-04-16-05-ssh-access-and-key-injection

## Process

1. Asked a planning subagent for the smallest genuinely shared SSH-readiness boundary.
2. Narrowed that to one shared control-node public-key resolver, while keeping host bootstrap and guest injection as separate transport adapters.
3. Asked a second subagent for a constrained implementation outline focused on shared resolution, contract-assisted guest bootstrap pubkey use, and low-cost validation.
4. Implemented the shared resolver, rewired both adapters to use it, and standardized the host bootstrap’s key existence/verification checks to exact-line matching.
5. Added a resolver regression that validates explicit-path precedence and fallback-to-first-existing behavior.

## What Changed

- Added `playbooks/roles/infrastructure/ssh_key_shared/tasks/resolve_pubkey.yml` to centralize control-node SSH public-key candidate resolution and content loading.
- `proxmox_host_bootstrap/tasks/ssh_access.yml` now uses the shared resolver for public-key discovery, fingerprints the resolved path, and verifies authorized_keys membership with exact-line checks.
- `lxc_ssh_key_injector/tasks/main.yml` now uses `proxmox_lxc_contract.guest_bootstrap.pubkey` when available and falls back to the shared resolver otherwise.
- Added `tests/regression/test_ssh_pubkey_resolver.py` and its fixture to cover the shared resolver’s precedence rules.

## Debugging Notes

- This slice stayed intentionally narrow: only public-key resolution was moved into the shared boundary, while interactive `sshpass` bootstrap and `pct exec` guest injection remained separate adapters.
- Host bootstrap verification was tightened from literal substring search to exact-line checks so pre-existing partial matches in `authorized_keys` do not count as success.
- The injector now consumes the compiled guest-bootstrap pubkey from `proxmox_lxc_contract` when available, which reduces redundant local file resolution during the normal lifecycle path.

## Validation

Focused regression passed:

- `tests/regression/test_ssh_pubkey_resolver.py`

Structural validation also passed for the shared resolver, host bootstrap SSH access task, and guest injector task via editor diagnostics.

## Remaining Gaps

- This slice does not try to unify the interactive host bootstrap transport with the guest injector’s runtime gating; those remain separate by design.
- The new regression exercises the shared resolver boundary only. The interactive bootstrap and `pct exec` flows still rely on their existing in-task smoke verification rather than additional fixture coverage.