# Control Node Reference (Agents)

Information-only reference for agents operating this repository from the Proxmox LXC control node.

## Audience and Scope
- Audience: agents with shell access to the controller LXC (typically via VS Code Remote SSH).
- Scope: controller-side usage only (Ansible runs locally on the controller against the Proxmox API and hosts in inventory).
- Out of scope: troubleshooting guides, narrative tutorials, or Proxmox host provisioning details.

## Operating Model
- Run everything on the controller LXC; do not run Ansible from your dev machine.
- Editor context is assumed to be attached to the controller over SSH.
- Host key behavior is relaxed: Ansible `host_key_checking = False`; Proxmox SSH uses `StrictHostKeyChecking=accept-new`.
- Never request or emit secrets (API token secret, vault password, private keys).

## Controller SSH Access
- User/host: `root@ansible.faviann.vms`.
- First-connect trust: `StrictHostKeyChecking=accept-new`.
- Client `~/.ssh/config` example:

```
Host ansible.faviann.vms
    HostName ansible.faviann.vms
    User root
    IdentityFile ~/.ssh/proxmox_lxc
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
```

- Quick verify from client:
  - `ssh ansible.faviann.vms 'hostname && whoami'`
  - Then on controller: `cd ~/ServerManagementScripts`

## Controller Paths and Tooling
- Repo root: cloned on the controller (`ansible.cfg` lives here).
- Virtualenv: `~/.ansible/venv` (created by `bootstrap.yml`).
- Collections install path: `collections/` (see `collections/requirements.yml`).
- Python requirements: `requirements/pip.txt`.
- SSH key for Ansible: `~/.ssh/proxmox_lxc` (private) and `~/.ssh/proxmox_lxc.pub` (public).
- Vault password file (do not commit): `~/.ansible/vault-pass.txt`.
- Ansible config highlights: `host_key_checking = False`, `private_key_file = ~/.ssh/proxmox_lxc`, `vault_password_file = ~/.ansible/vault-pass.txt`, fact cache under `.ansible/cache`.

## Inventory and Naming
- Inventory file: `inventory/hosts.yml`.
- Groups: `proxmox_api` (controller, `ansible_connection: local`), `lxcs` (managed containers), resource tiers (`tier_tiny|small|medium|large`), capability groups (`cap_docker`, `cap_gpu`, `cap_wireguard`, `cap_service_agents`).
- Host naming convention for LXCs: `{{ inventory_hostname }}.faviann.vms` (see `inventory/group_vars/all/proxmox.yml`).

## Configuration Reference (non-secret)
- File: `inventory/group_vars/all/proxmox.yml`.
- Key defaults:
  - `proxmox_api_host`: `proxmox.internal.faviann.com`
  - `proxmox_api_port`: `8006`
  - `proxmox_default_node`: `proxmox`
  - `proxmox_default_pool`: `ansible_pool`
  - `proxmox_default_storage`: `local-zfs`
  - `proxmox_default_ostemplate`: `local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst`
  - SSL verification: `proxmox_verify_ssl: false` (self-signed by default)
  - Shared bind mounts: `mp0` `/rpool/data/subvol-200-disk-1` -> `/shared`; `mp1` `/conf` -> `/conf` (ro); `mp2` `/ephemeral` -> `/ephemeral`; `mp3` `/tank` -> `/data`
  - ID mapping for unprivileged LXCs defined under `proxmox_default_idmap`
  - Host prep toggle: `proxmox_lxc_host_prep_enabled: true`; delegate host/user: `proxmox_api_host`, `root`
- Secrets: `inventory/group_vars/all/vault.yml` (create from `.example` and encrypt with `ansible-vault`). Never commit plaintext secrets or vault password files.

## Playbooks and Tags (reference)
- `bootstrap.yml`: prepares controller venv, collections, and SSH material. Run on `localhost`.
- `site.yml`: orchestration entrypoint.
  - Always: bootstrap prerequisites assertion; host SSH bootstrap (`proxmox_host_bootstrap` role).
  - `validation` tag: Proxmox API connectivity (`playbooks/tasks/proxmox_validation.yml`).
  - `provision` / `host_config`: build LXC spec (`proxmox_lxc_provision`), provision container, host-side config (`proxmox_lxc_host_config`, delegated to Proxmox host).
  - `configure`: in-guest configuration via `lxc_internal_setup`.
- Other plays:
  - `playbooks/lab-connectivity.yml`: SSH ping for hosts, Proxmox API version check.
  - `playbooks/proxmox_api_check.yml`: list LXCs via API.
  - `playbooks/lxc-provision.yml`: provision LXCs with pre/post host prep.

## Command Reference (run on controller, venv-first)
- Activate venv: `source ~/.ansible/venv/bin/activate`
- Bootstrap: `ansible-playbook bootstrap.yml`
- Full orchestration: `ansible-playbook -i inventory/hosts.yml site.yml`
- Validation only: `ansible-playbook -i inventory/hosts.yml site.yml --tags validation`
- Provision only: `ansible-playbook -i inventory/hosts.yml site.yml --tags provision`
- Host config only: `ansible-playbook -i inventory/hosts.yml site.yml --tags host_config`
- Connectivity check: `ansible-playbook playbooks/lab-connectivity.yml`

### Minimal Smoke Test (venv-first)
- Activate venv: `source ~/.ansible/venv/bin/activate`
- Confirm Ansible available: `ansible --version`
- Ping `gatekeeper` from inventory: `ansible -i inventory/hosts.yml gatekeeper -m ping`

## First-time Setup (Controller, venv-only)
If `ansible` is not present, create and seed the controller venv:

```
python3 -m venv ~/.ansible/venv
source ~/.ansible/venv/bin/activate
python3 -m pip install --upgrade pip
pip install ansible
pip install -r ~/ServerManagementScripts/requirements/pip.txt
```

Then bootstrap the repo environment:

```
cd ~/ServerManagementScripts
source ~/.ansible/venv/bin/activate
ansible --version
ansible-playbook bootstrap.yml
```

Venv guard (copy-paste):

```
if [ -x "$HOME/.ansible/venv/bin/ansible" ]; then
  . "$HOME/.ansible/venv/bin/activate"
else
  python3 -m venv "$HOME/.ansible/venv"
  . "$HOME/.ansible/venv/bin/activate"
  python3 -m pip install --upgrade pip
  pip install ansible
  pip install -r "$HOME/ServerManagementScripts/requirements/pip.txt"
fi
ansible --version
```

## Safety Rules
- Do not commit or echo: `~/.ansible/vault-pass.txt`, private keys (`~/.ssh/proxmox_lxc`), token secrets.
- Keep Ansible runs on the controller; do not reset hosts or modify user-provided files outside writable scope.
- Use placeholders like `<REPLACE_ME>` in docs/examples that mention secrets.

## Related Documents
- Setup/how-to: `docs/remote-controller-setup.md`
- Proxmox SSH automation details: `docs/proxmox-host-ssh-automation.md`
- Inventory structure references: `docs/inventory-structure-guide.md`, `docs/inventory-visualization.md`
