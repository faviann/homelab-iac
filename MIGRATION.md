# Migration Guide: Workstation-Portable Setup

## What Changed?

The project is now **fully portable** - all Ansible artifacts are stored within the project directory instead of scattered across your home directory. This makes it easy to run from any workstation without cluttering `~/.ssh` or `~/.ansible`.

### Path Changes

| Artifact | Old Location | New Location |
|----------|-------------|--------------|
| SSH private key | `~/.ssh/proxmox_lxc` | `.ansible/ssh/proxmox_lxc` |
| SSH public key | `~/.ssh/proxmox_lxc.pub` | `.ansible/ssh/proxmox_lxc.pub` |
| Vault password | `~/.ansible/vault-pass.txt` | `.ansible/vault-pass.txt` |
| Virtual environment | `~/.ansible/venv` | `.ansible/venv` |
| SSH control path | `~/.ansible/cp/` | `.ansible/cp/` |
| Fact cache | `.ansible/cache/` | `.ansible/cache/` (unchanged) |

## Migration Steps

### If migrating from the old LXC controller setup:

1. **Backup your secrets** (on the old controller):
   ```bash
   cd ~/ServerManagementScripts
   
   # Backup vault password
   [ -f ~/.ansible/vault-pass.txt ] && cp ~/.ansible/vault-pass.txt .ansible/vault-pass.txt
   
   # Backup SSH keys
   mkdir -p .ansible/ssh
   [ -f ~/.ssh/proxmox_lxc ] && cp ~/.ssh/proxmox_lxc .ansible/ssh/proxmox_lxc
   [ -f ~/.ssh/proxmox_lxc.pub ] && cp ~/.ssh/proxmox_lxc.pub .ansible/ssh/proxmox_lxc.pub
   
   # Set proper permissions
   chmod 600 .ansible/vault-pass.txt .ansible/ssh/proxmox_lxc
   chmod 644 .ansible/ssh/proxmox_lxc.pub
   ```

2. **Pull the latest changes**:
   ```bash
   git pull
   ```

3. **Remove old venv** (will be recreated in new location):
   ```bash
   rm -rf ~/.ansible/venv
   ```

4. **Re-run bootstrap** to create the new venv:
   ```bash
   ansible-playbook bootstrap.yml
   ```

5. **Test the setup**:
   ```bash
   source activate-env.sh
   ansible --version
   ansible-playbook site.yml --tags validation
   ```

### Fresh setup on a new workstation:

**Automated (Recommended):**

```bash
git clone <your-repo-url> ServerManagementScripts
cd ServerManagementScripts
./setup.sh
```

The setup script handles everything automatically, including:
- Installing system prerequisites
- Generating/configuring vault password
- Creating Python virtual environment
- Running bootstrap
- Setting up vault configuration

**Manual Setup:**

1. **Install system prerequisites**:
   ```bash
   sudo apt update
   sudo apt install -y python3-venv python3-pip sshpass
   ```

2. **Clone the repository**:
   ```bash
   git clone <your-repo-url> ServerManagementScripts
   cd ServerManagementScripts
   ```

3. **Create vault password file**:
   ```bash
   echo "your-vault-passphrase" > .ansible/vault-pass.txt
   chmod 600 .ansible/vault-pass.txt
   ```

4. **Run bootstrap** (creates venv and SSH keys):
   ```bash
   ansible-playbook bootstrap.yml
   ```

5. **Configure vault secrets**:
   ```bash
   cp inventory/group_vars/all/vault.yml.example inventory/group_vars/all/vault.yml
   # Edit vault.yml with your Proxmox API token secret
   ansible-vault encrypt inventory/group_vars/all/vault.yml
   ```

6. **Test connectivity**:
   ```bash
   source activate-env.sh
   ansible-playbook site.yml --tags validation
   ```

## Helper Script

A new activation helper is available:

```bash
source activate-env.sh
```

This will:
- Activate the project-local venv at `.ansible/venv`
- Show which Python/Ansible version is active
- Display an error if the venv doesn't exist yet

## Benefits

✅ **Portable** - Clone and run from any location  
✅ **Multi-user** - Each developer has their own checkout with isolated secrets  
✅ **Clean** - No home directory pollution  
✅ **CI/CD ready** - Works in ephemeral containers  
✅ **Self-contained** - Everything lives in the project tree

## Cleanup (Optional)

After migration, you can clean up the old files from your home directory:

```bash
# ⚠️  Only run this AFTER verifying the migration worked!
rm -rf ~/.ansible/venv
rm -f ~/.ssh/proxmox_lxc ~/.ssh/proxmox_lxc.pub
rm -f ~/.ansible/vault-pass.txt
rm -rf ~/.ansible/cp
```

## Troubleshooting

### "No such file or directory: .ansible/vault-pass.txt"

Create the vault password file in the project directory:
```bash
echo "your-passphrase" > .ansible/vault-pass.txt
chmod 600 .ansible/vault-pass.txt
```

### "ansible: command not found"

Activate the venv:
```bash
source activate-env.sh
```

Or if venv doesn't exist, run bootstrap:
```bash
ansible-playbook bootstrap.yml
```

### "Permission denied (publickey)"

Ensure SSH keys exist and have correct permissions:
```bash
ls -la .ansible/ssh/
# Should show:
# -rw------- proxmox_lxc
# -rw-r--r-- proxmox_lxc.pub

# Fix if needed:
chmod 600 .ansible/ssh/proxmox_lxc
chmod 644 .ansible/ssh/proxmox_lxc.pub
```

### Old paths still referenced

All configuration now uses project-relative paths. If you see errors about `~/.ssh` or `~/.ansible`, ensure you've pulled the latest changes:
```bash
git pull
```
