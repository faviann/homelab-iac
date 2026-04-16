# Compiled LXC Spec Contract Report

Date: 2026-04-16
Plan: 2026-04-16-02-compiled-lxc-spec-contract

## Process

1. Asked a planning subagent for the smallest viable contract shape and migration order.
2. Reviewed that proposal against the local code and narrowed the change to one explicit `proxmox_lxc_contract` with three slices: `api_spec`, `host_config`, and `guest_bootstrap`.
3. Migrated the direct consumers first: the Proxmox API provisioner, the host-config role, and lifecycle release derivation.
4. Added a standalone regression fixture to validate precedence layering, tier-derived defaults, host-config ownership, password stripping, and compatibility aliases.

## What Changed

- `playbooks/roles/provisioning/lxc_spec_builder/tasks/main.yml` now compiles `proxmox_lxc_contract` and refreshes the legacy aliases from that contract.
- The API slice no longer carries host-only `features`; those now live in `proxmox_lxc_contract.host_config.features`.
- `proxmox_lxc_provision` now consumes the API slice through `proxmox_lxc_api_spec`.
- `proxmox_lxc_host_config` now resolves `proxmox_lxc_host_config_spec` from the contract and uses it for VMID, bind mounts, idmap, and features.
- `proxmox_lxc_lifecycle/tasks/compile.yml` now derives the desired Debian release from the contract API slice.
- Added `tests/regression/test_lxc_spec_contract.py` and its fixture for contract-focused validation.

## Debugging Notes

- The first consumer migration left a stray `start_on_create` override before the API slice was resolved in `proxmox_lxc_provision`; that was removed immediately after a focused source review.
- Implementation review identified two adjacent host-config issues worth tracking but not mixing into this refactor: additive-only feature reconciliation and missing restart signaling for config-file edits. Both were logged in `BACKLOG.md`.
- The same review also highlighted insertion-order drift in bind-mount and idmap rewrites, which was fixed by sorting the applied loops to match the existing sorted comparisons.

## Validation

Focused contract regression passed:

- `tests/regression/test_lxc_spec_contract.py`

Structural validation also passed for the touched task files via the editor diagnostics.

## Remaining Gaps

- `lxc_ssh_key_injector` did not need a contract migration in this slice; it still owns its own key-resolution path and runtime gating.
- The backward-compat fallback path inside `proxmox_lxc_host_config` is intentionally still present, but the new regression primarily validates the contract-first path.