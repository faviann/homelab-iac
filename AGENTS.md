# Agent Operating Instructions (SSH-only Control Node)

This repository is designed to be operated from a dedicated **Proxmox LXC control node** (the “controller”).

## Non-negotiables

- **SSH into the controller LXC and work there.** Do not run Ansible from the dev machine.
- Assume the editor is attached via **VS Code Remote - SSH** to the controller.
- Do not ask for or output secrets (API token secret, vault passphrase, private keys).

## Standard locations (controller)

- Repo workspace: this repository cloned on the controller.
- Ansible config: `ansible.cfg` (repo root)
- SSH key used by Ansible: `~/.ssh/proxmox_lxc` (private) and `~/.ssh/proxmox_lxc.pub` (public)
- Vault password file (required/standardized): `~/.ansible/vault-pass.txt`
- Vaulted secrets file (encrypted in repo): `inventory/group_vars/all/vault.yml`
- Vault template (safe to commit): `inventory/group_vars/all/vault.yml.example`

## SSH / host key behavior (intentionally relaxed)

- Ansible disables strict host key checking (`host_key_checking = False`) in `ansible.cfg`.
- Proxmox-host SSH uses `StrictHostKeyChecking=accept-new` via `inventory/group_vars/all/proxmox.yml`.

## Host naming convention

- LXC hosts are addressed as: `{{ inventory_hostname }}.faviann.vms` for the `lxcs` group.
- Proxmox API host is configured in `inventory/group_vars/all/proxmox.yml` (`proxmox_api_host`).

## Controller quickstart (run on the controller)

0) Prerequisite: `ansible-playbook` must exist on the controller.

Bootstrap is an Ansible playbook, so the controller needs a system-level Ansible installed (for the very first run only). After bootstrap completes, use the venv for day-to-day runs.

1) Bootstrap the controller environment:

```bash
ansible-playbook bootstrap.yml
```

2) Activate the controller virtual environment for this shell:

```bash
source ~/.ansible/venv/bin/activate
```

3) Create the vault file from the example, then encrypt it:

```bash
cp inventory/group_vars/all/vault.yml.example inventory/group_vars/all/vault.yml
$EDITOR inventory/group_vars/all/vault.yml
ansible-vault encrypt inventory/group_vars/all/vault.yml
```

4) Ensure the standardized vault password file exists (do not commit it):

```bash
install -d -m 700 ~/.ansible
$EDITOR ~/.ansible/vault-pass.txt
chmod 600 ~/.ansible/vault-pass.txt
```

5) Validate:

```bash
ansible-playbook -i inventory/hosts.yml site.yml --tags validation
```

6) Full run:

```bash
ansible-playbook -i inventory/hosts.yml site.yml
```

## Security rules

- Never commit or paste:
  - `~/.ansible/vault-pass.txt`
  - Any private key (`~/.ssh/proxmox_lxc`)
  - API token secret values (must remain in `vault.yml` and encrypted)
- When adding docs or examples, use placeholders like `"<REPLACE_ME>"`.
