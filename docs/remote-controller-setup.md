# Remote Controller Setup and Usage (LXC-only)

Run these playbooks from an Ubuntu LTS LXC (unprivileged) or your dev machine.

## Quick Start with Bootstrap

### 1) Install system prerequisites
```bash
sudo apt update
sudo apt install -y python3-venv python3-pip
```

### 2) Run the bootstrap playbook
```bash
# Run bootstrap to set up the Ansible environment
ansible-playbook bootstrap.yml
```

The bootstrap playbook will:
- Create a Python virtual environment at `~/.ansible-venv`
- Install Ansible and required Python packages
- Install Ansible collections

### 3) Activate the virtual environment
```bash
source ~/.ansible-venv/bin/activate
```

> **Note**: You'll need to activate this environment every time you start a new session.

### 4) Configure Proxmox API credentials with Ansible Vault
```bash
cp group_vars/all/vault.example.yml group_vars/all/vault.yml
$EDITOR group_vars/all/vault.yml   # put your token secret
ansible-vault encrypt group_vars/all/vault.yml
```
Optional local vault password file (do NOT commit):
```bash
echo "your-strong-passphrase" > ~/.ansible/vault-pass.txt
chmod 600 ~/.ansible/vault-pass.txt
```

Set non-secret vars in `inventory/group_vars/all/proxmox.yml`:
- `proxmox_api_host` (default set to proxmox.vms)
- `proxmox_api_token_id`
- `proxmox_verify_ssl` (false for now)
- `proxmox_default_node` (default proxmox.vms)

### 5) Inventory
Edit `inventory/hosts.yml` as needed. The `proxmox_api` group is for API tasks (runs locally on the controller). Add your containers to `lxcs` for post-provision SSH config if you want to manage them after creation.

### 6) Run validation checks
Use the site playbook to validate connectivity:
```bash
ansible-playbook site.yml --tags validation
```

Or run individual playbooks:
```bash
# Test connectivity and LXC discovery
ansible-playbook playbooks/proxmox_api_check.yml

# Test SSH and API connectivity
ansible-playbook playbooks/lab-connectivity.yml
```

### 7) Provision an example LXC
Adjust variables in `playbooks/provision_lxc_example.yml` (node name, template, storage, VMID, network), then:
```bash
ansible-playbook playbooks/provision_lxc_example.yml
```

## Manual Setup (Alternative to Bootstrap)

If you prefer to set up the environment manually instead of using `bootstrap.yml`:

### 1) Install Ansible on Ubuntu LTS
```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository --yes --update ppa:ansible/ansible
sudo apt install -y ansible
ansible --version   # ansible-core 2.19.x
```

### 2) Install Python deps and collections
```bash
python3 -m pip install --user -r requirements/pip.txt
ansible-galaxy collection install -r collections/requirements.yml
```

Then proceed with steps 4-7 above.

## TLS verification (TODO/future hardening)
- Current default: `proxmox_verify_ssl: false` for self-signed certs.
- Future steps:
  - Install a trusted certificate on Proxmox or distribute a CA bundle.
  - Set `proxmox_verify_ssl: true` and configure CA path if needed.

## Notes
- API tokens are preferred. Create a least-privilege token with only the permissions required for LXC lifecycle on relevant nodes.
- If module names differ in your installed `community.proxmox`, use:
  - `ansible-doc -l | grep proxmox`
  - `ansible-doc community.proxmox.proxmox_lxc`
  - `ansible-doc community.proxmox.proxmox_lxc_info`
