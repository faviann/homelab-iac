# Pin fleet host keys through Proxmox

Ansible has run with `host_key_checking = False`, because a rebuild gives an
LXC new host keys and only the control node that rebuilt it cleared its stale
entry. That let any container on the bridge impersonate another host and
receive what the lifecycle pushes there, nightly and unattended. Control nodes
now check every fleet host key strictly. Before a run first connects to a
container, it reads the container's host public keys through Proxmox
(`pct exec` by VMID) and writes them to a fleet `known_hosts`. It reads them
again after a create or rebuild. Specified in #552.

## Why

- The read never crosses the fleet network. Proxmox finds a container by
  VMID, not by name or address, so a container that claims another's name
  cannot answer it. The one remaining trust is the connection to Proxmox.
- Keys are read again on every run, never remembered, so a rebuild heals on
  both control nodes with no cleanup and no stale entry to clear.
- It adds no secret. The Proxmox connection already exists and is already
  trusted.

## The Proxmox anchor

Proxmox cannot vouch for itself. Its host key is recorded when a control node
first trusts it, through the trust check or `./recover.sh proxmox-host-ssh`,
and checked strictly afterward. The workstation copies its record to the
bootstrap node with the other control-node secrets
([ADR-0020](0020-copy-control-node-secrets-from-the-workstation.md)). A
reinstalled Proxmox already needs that human-only enrollment, which records
its new key, so a reinstall adds no step. A brand-new control node's first
contact with Proxmox is the one trust-on-first-use left.

## Considered options

- **`accept-new`.** A rebuild on one control node leaves the other with a
  stale key. The planning barrier then stops the nightly deploy, and an agent
  that clears the entry to get unstuck undoes the protection.
- **An SSH host CA.** It would need no lookup, but its signing key would be a
  new vault secret that can mint any host's identity, plus a signing step and
  a trust line on each control node.
- **Committing Proxmox's key to the repository.** A reinstall would block
  every deploy until someone commits the new key.
