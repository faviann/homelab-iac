# group_vars layout

This directory organizes inventory variables by purpose:

- `all/` holds shared defaults (Proxmox API settings, host prep settings).
- `lxcs/` holds defaults for every managed LXC.
- `tier_*` describe each LXC's baseline CPU, RAM, and disk.
- `cap_*` set capability flags (Docker, GPU, WireGuard, browser device).
- `proxmox_api/` configures the control node, which drives API calls.

A tier overrides a capability where both set the same variable.
[docs/inventory-structure-guide.md](../../docs/inventory-structure-guide.md#variable-precedence)
gives the full precedence order.

Each group directory contains a `vars.yml`, so the directory name matches the
Ansible group it configures. Add `files/` or `vault/` subfolders alongside
`vars.yml` if a group later needs templates or vaulted data.
