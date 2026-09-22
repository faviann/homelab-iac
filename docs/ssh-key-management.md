# SSH Key Management for Existing LXC Containers

## When You Need This

LXC containers created outside of Ansible (manually or by other tools) won't have the control node's SSH public key, preventing Ansible from connecting. This also applies if the provisioning phase's SSH injection step failed.

## Supported Recovery

```bash
# All containers
./recover.sh ssh-keys

# Specific container(s)
./recover.sh ssh-keys --limit portal
./recover.sh ssh-keys --limit portal,seedbox
```

`./recover.sh` is the only supported entry point for this recovery. It holds the machine-local lifecycle lock for the duration and reconciles the dependencies the playbook consumes before Ansible starts. Running `playbooks/add-ssh-keys-to-lxcs.yml` directly fails the controller prerequisite, which requires the wrapper.

Recovery reaches the guests with `pct exec` on the Proxmox host, so containers do not need to be SSH-accessible beforehand. It is idempotent and non-destructive: it only adds keys, never removes them.

It reads the control node public key from `~/.ansible/ssh/proxmox_lxc.pub`, the one machine-global location, and fails when that file is absent. No playbook generates that key pair; you create or restore it yourself.

**Prerequisites**: the container must be running. Proxmox host SSH access is established by the command itself — its prerequisite layer installs the controller key on the Proxmox host, prompting once for the root password when key authentication is not yet configured.

## Last Resort: Manual Injection via the Proxmox Host

Human-only, and only when the supported recovery cannot run at all. This bypasses the live boundary, so nothing serializes it against another lifecycle operation.

**Step 1 — on the control node.** Print the public key and copy the single line it outputs.

```bash
cat ~/.ansible/ssh/proxmox_lxc.pub
```

**Step 2 — on the Proxmox host.** Paste that line between the single quotes, and set the container's VMID.

```bash
ssh root@proxmox.lan

VMID=300
PUBKEY='ssh-ed25519 AAAA... ansible-control@workstation'

pct exec $VMID -- mkdir -p /root/.ssh
pct exec $VMID -- chmod 700 /root/.ssh
pct exec $VMID -- bash -c "echo '$PUBKEY' >> /root/.ssh/authorized_keys"
pct exec $VMID -- chmod 600 /root/.ssh/authorized_keys
```

## Verification

```bash
./inspect.sh connectivity
./inspect.sh connectivity --limit portal
```
