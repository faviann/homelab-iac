# Agent Operating Instructions (Controller LXC)

Operate this repository **only** from the Proxmox LXC control node. Reference: `docs/reference/agent-control-node-reference.md`.

## Non-negotiables
- SSH into the controller LXC and run Ansible there (not from your dev machine).
- Connect to the controller at `ansible.faviann.vms` over SSH (VS Code Remote SSH or plain shell).
- Never request, paste, or print secrets (API token secret, vault passphrase, private keys).

## Standard locations (controller)
- Repo workspace and `ansible.cfg`: repository root.
- SSH key: `~/.ssh/proxmox_lxc` (private) and `~/.ssh/proxmox_lxc.pub` (public).
- Vault password file (do not commit): `~/.ansible/vault-pass.txt`.
- Vaulted secrets file (encrypted): `inventory/group_vars/all/vault.yml` (template: `.example`).

## Host key behavior
- Ansible disables strict host key checking (`host_key_checking = False` in `ansible.cfg`).
- Proxmox SSH uses `StrictHostKeyChecking=accept-new` (see `inventory/group_vars/all/proxmox.yml`).

## Host naming convention
- LXCs resolve as `{{ inventory_hostname }}.faviann.vms` in the `lxcs` group.
- Proxmox API host is set in `inventory/group_vars/all/proxmox.yml` (`proxmox_api_host`).

## Quick reference commands (run on controller)
- Bootstrap dependencies: `ansible-playbook bootstrap.yml`
- Validate only: `ansible-playbook -i inventory/hosts.yml site.yml --tags validation`
- Full run: `ansible-playbook -i inventory/hosts.yml site.yml`

## Security rules
- Do not commit or paste: `~/.ansible/vault-pass.txt`, any private key (`~/.ssh/proxmox_lxc`), or token secrets (keep them in encrypted `vault.yml` only).
- Use placeholders like `<REPLACE_ME>` in docs or examples that mention secrets.
