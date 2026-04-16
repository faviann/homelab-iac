# Proxmox Host Reconciliation Report

Date: 2026-04-16
Plan: 2026-04-16-03-proxmox-host-reconciliation

## Process

1. Asked a planning subagent for the smallest host-reconciliation boundary.
2. Narrowed that proposal to a pragmatic slice: keep the existing task-file split, but make the role own one public result fact and one explicit restart outcome.
3. Asked a second subagent for an implementation outline focused on a result boundary and local regression strategy.
4. Implemented the boundary manually, validated early, and iterated on the first failing regression until the role passed end to end against a temp config root and mock `pct` binary.

## What Changed

- Added `proxmox_lxc_host_config_path_root` and `proxmox_lxc_host_config_become` defaults so the role can be exercised locally without a live Proxmox host.
- `playbooks/roles/infrastructure/proxmox_lxc_host_config/tasks/main.yml` now initializes and finalizes `proxmox_lxc_host_config_result` with component-level outcomes plus aggregate `overall_changed`, `restart_required`, and `restart_applied` fields.
- Each config-file adapter and `features.yml` now publishes its own changed/restart semantics into that boundary.
- `config_file.yml` now validates input types and actually includes `config_file_sysctls.yml`.
- Added `tests/regression/test_proxmox_lxc_host_config_result.py` and its fixture to validate config-file edits, feature reconciliation, and restart reporting using a temp config root and mock `pct` script.

## Debugging Notes

- The first executable regression exposed a real role bug: `config_file_sysctls.yml` existed but was not wired into `config_file.yml`, so sysctls never reconciled.
- The second regression failure exposed an incomplete testability seam: one `become: true` remained hardcoded in `config_file_sysctls.yml`, which broke the localhost fixture until it was replaced with the new role-level toggle.
- Aggregate restart semantics were adjusted so a reboot already applied by the feature adapter clears the final `restart_required` flag even when earlier config-file changes also require a restart.

## Validation

Focused regression passed:

- `tests/regression/test_proxmox_lxc_host_config_result.py`

Structural validation also passed for the touched task files via editor diagnostics.

## Remaining Gaps

- The role still preserves the existing internal task-file split; this slice deepened the ownership boundary and result reporting without yet collapsing repeated config-file mutation patterns.
- Feature reconciliation remains additive-only and config-file-only changes still rely on the reported restart state rather than performing a restart directly. Those adjacent issues are tracked separately in `BACKLOG.md`.