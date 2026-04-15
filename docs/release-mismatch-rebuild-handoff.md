# Release Mismatch Rebuild Handoff

Date: 2026-04-15

## Goal

Implement automatic LXC destroy-and-recreate when the running guest Debian major release does not match the desired release derived from the configured `ostemplate`.

## What Changed

- Added `proxmox_lxc_rebuild_on_release_mismatch: false` to:
  - `inventory/group_vars/all/proxmox.yml`
  - `playbooks/roles/infrastructure/proxmox_lxc_provision/defaults/main.yml`
- Extended `playbooks/tasks/proxmox_validation.yml` to:
  - derive desired Debian release from each host's effective `ostemplate`
  - probe current CT runtime state with `pct status`
  - probe running guest release with `pct exec ... /etc/os-release`
  - enrich `lxc_validation_results` with:
    - `desired_release`
    - `actual_release`
    - `runtime_state`
    - `release_probe_state`
    - `release_mismatch`
    - `rebuild_eligible`
  - report release mismatches separately from VMID/name conflicts
  - propagate release summary facts to LXC hosts
- Reworked `playbooks/roles/infrastructure/proxmox_lxc_provision/tasks/main.yml` to:
  - derive desired Debian release from `proxmox_lxc_spec.ostemplate`
  - reuse validation results when available
  - fall back to local `pct` probing when `playbooks/provision-lxcs.yml` is run directly
  - stop and destroy a mismatched running CT when `proxmox_lxc_rebuild_on_release_mismatch` is `true`
  - leave stopped CTs report-only
  - leave mismatches report-only when the flag is `false`

## Intended Behavior

- Running CT on matching Debian major version:
  - no destroy/recreate
- Running CT on mismatched Debian major version:
  - report only by default
  - destroy/recreate when `proxmox_lxc_rebuild_on_release_mismatch: true`
- Stopped CT:
  - never auto-destroyed
  - reported as `release_probe_state: skipped_stopped`
- Missing CT:
  - treated as normal create path

## Review Focus

- Confirm the validation task file is syntactically valid Ansible/YAML after the new `set_fact`/Jinja additions.
- Confirm the `selectattr('value.release_mismatch')` and `selectattr('value.rebuild_eligible')` usage behaves correctly with Ansible's Jinja filters.
- Confirm the `pct exec` probe command is acceptable on your Proxmox host and returns the expected `VERSION_ID`.
- Confirm `community.proxmox.proxmox state: absent` behaves as expected for LXC deletion in your installed collection version.
- Confirm the direct-run fallback in `proxmox_lxc_provision` is sufficient for `ansible-playbook playbooks/provision-lxcs.yml`.

## Known Constraints

- Desired release is parsed from template naming, so this currently assumes Debian templates named like `debian-13-...`.
- Patch-level template changes within the same Debian major release do not trigger rebuilds.
- No backup step is enforced.
- Stopped containers are intentionally excluded from automatic destruction.
