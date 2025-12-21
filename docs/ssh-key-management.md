# SSH Key Management for Existing LXC Containers

## Overview

This guide explains how to add the Ansible control node SSH key to existing LXC containers **without deleting or recreating them**.

## Why This Is Needed

When LXC containers are created outside of this Ansible automation (manually or by other tools), they don't have the control node's SSH public key in their `authorized_keys`. This prevents Ansible from connecting to manage them.

## Solution: Non-Destructive SSH Key Addition

### Method 1: Automated Playbook (Recommended)

A dedicated playbook has been created to safely add SSH keys to existing containers.

**File**: `playbooks/add-ssh-keys-to-lxcs.yml`

#### Features
- ✅ **Non-destructive**: Only adds SSH keys, never deletes containers
- ✅ **Idempotent**: Can be run multiple times safely
- ✅ **Selective**: Use `--limit` to target specific containers
- ✅ **Validation**: Tests SSH connectivity after adding keys
- ✅ **Smart**: Skips containers that don't exist
- ✅ **Safe**: Checks if key already exists before adding

#### Usage

**Add SSH key to all LXC containers:**
```bash
ansible-playbook playbooks/add-ssh-keys-to-lxcs.yml
```

**Add SSH key to specific container:**
```bash
ansible-playbook playbooks/add-ssh-keys-to-lxcs.yml --limit gatekeeper
```

**Add SSH key to multiple specific containers:**
```bash
ansible-playbook playbooks/add-ssh-keys-to-lxcs.yml --limit gatekeeper,seedpod
```

**Dry run (check what would happen):**
```bash
ansible-playbook playbooks/add-ssh-keys-to-lxcs.yml --check
```

**With verbose output:**
```bash
ansible-playbook playbooks/add-ssh-keys-to-lxcs.yml -v
```

### Method 2: Manual SSH Key Addition

If you prefer manual control or the automated playbook isn't working:

#### Option A: Via Proxmox Host (pct command)

```bash
# SSH into Proxmox host
ssh root@proxmox.lan

# Get the public key content (from control node)
# cat .ansible/ssh/proxmox_lxc.pub

# For each container, run:
VMID=300  # Change to your container VMID
PUBKEY="ssh-ed25519 AAAAC3... your-key-here"

pct exec $VMID -- mkdir -p /root/.ssh
pct exec $VMID -- chmod 700 /root/.ssh
pct exec $VMID -- bash -c "echo '$PUBKEY' >> /root/.ssh/authorized_keys"
pct exec $VMID -- chmod 600 /root/.ssh/authorized_keys
```

#### Option B: Via Container Console

```bash
# From Proxmox web UI: Select container → Console
# Or from Proxmox host:
pct enter <VMID>

# Inside the container:
mkdir -p /root/.ssh
chmod 700 /root/.ssh

# Add the public key (paste content from .ansible/ssh/proxmox_lxc.pub)
cat >> /root/.ssh/authorized_keys << 'EOF'
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyContentHere ansible-control
EOF

chmod 600 /root/.ssh/authorized_keys
exit
```

#### Option C: Copy Your Existing SSH Key

If you already have SSH access to the containers with a different key:

```bash
# From your control node
cat .ansible/ssh/proxmox_lxc.pub

# SSH into each container with your existing key
ssh -i ~/.ssh/your-existing-key root@gatekeeper.faviann.vms

# Inside the container, add the new key
echo "ssh-ed25519 AAAAC3... ansible-control" >> /root/.ssh/authorized_keys
```

### Method 3: Use Ansible's authorized_key Module

If you have temporary password access or another SSH key:

```yaml
# Create a temporary playbook: temp-add-keys.yml
---
- hosts: lxcs
  gather_facts: false
  vars:
    ansible_ssh_private_key_file: ~/.ssh/your-temporary-key  # Your current key
  tasks:
    - name: Add control node SSH key
      ansible.posix.authorized_key:
        user: root
        key: "{{ lookup('file', '.ansible/ssh/proxmox_lxc.pub') }}"
        state: present
```

Run it:
```bash
ansible-playbook temp-add-keys.yml
```

## How It Works (Automated Playbook)

The automated playbook performs these steps for each container:

1. **Verify container exists**: Uses `pct status <VMID>` to check
2. **Create .ssh directory**: Ensures `/root/.ssh` exists with proper permissions (700)
3. **Check for existing key**: Avoids duplicates by checking if key is already present
4. **Add SSH key**: Appends public key to `/root/.ssh/authorized_keys` if not present
5. **Set permissions**: Ensures `authorized_keys` has mode 600
6. **Verify**: Confirms the key was added successfully
7. **Test connectivity**: Attempts SSH connection to validate

All operations are done via the Proxmox host using `pct exec` commands, so containers don't need to be accessible via SSH beforehand.

## Prerequisites

- Access to Proxmox host via SSH (the automated playbook requires this)
- Proxmox host SSH access already configured (run `ansible-playbook site.yml --tags bootstrap` first)
- Containers must be running (stopped containers cannot execute commands)

## Verification

After adding SSH keys, verify connectivity:

```bash
# Test all containers
ansible lxcs -m ping

# Test specific container
ansible gatekeeper -m ping

# Test with verbose output
ansible lxcs -m ping -v
```

Expected output for successful connection:
```
gatekeeper | SUCCESS => {
    "changed": false,
    "ping": "pong"
}
```

## Troubleshooting

### "Container does not exist"
- Verify VMID in `inventory/host_vars/<hostname>.yml`
- Check container exists: `ssh root@proxmox.lan pct list`

### "Container is not running"
- Start the container: `ssh root@proxmox.lan pct start <VMID>`
- Or from Proxmox web UI

### "Permission denied (publickey)"
- Verify key was actually added: `ssh root@proxmox.lan pct exec <VMID> -- cat /root/.ssh/authorized_keys`
- Check permissions: `ssh root@proxmox.lan pct exec <VMID> -- ls -la /root/.ssh/`
- Verify you're using the correct key: `ssh -i .ansible/ssh/proxmox_lxc root@container.faviann.vms`

### "Cannot connect to Proxmox host"
- Run bootstrap first: `ansible-playbook site.yml --tags bootstrap`
- Verify Proxmox host access: `ssh root@proxmox.lan`

## Security Notes

- The playbook only **adds** keys, never removes or replaces them
- Existing SSH keys in `authorized_keys` remain untouched
- Multiple keys can coexist in `authorized_keys` (one per line)
- The playbook is idempotent - running it multiple times is safe
- Key fingerprint verification happens automatically

## Integration with Main Workflow

Once SSH keys are added to existing containers, the normal workflow works:

```bash
# 1. Add SSH keys to existing containers (one-time)
ansible-playbook playbooks/add-ssh-keys-to-lxcs.yml

# 2. Verify connectivity
ansible lxcs -m ping

# 3. Run normal configuration
ansible-playbook site.yml --tags configure

# 4. Future runs work normally
ansible-playbook site.yml
```

## Summary

**Is it feasible to update SSH keys on existing LXCs without deleting them?**

**Answer: Extremely feasible!** It's actually a common operation and can be done:
- ✅ Automatically via the provided playbook
- ✅ Manually via `pct exec` commands
- ✅ Via container console access
- ✅ Via Ansible if you have temporary access

The automated playbook makes it a one-command operation that's safe, idempotent, and non-destructive.
