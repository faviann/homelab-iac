# SSH Key Management for Existing LXC Containers

## When You Need This

LXC containers created outside of Ansible (manually or by other tools) won't have the control node's SSH public key, preventing Ansible from connecting. This also applies if the provisioning phase's SSH injection step failed.

## Supported Recovery

```bash
# All existing containers
./recover.sh ssh-keys

# Specific container(s)
./recover.sh ssh-keys --limit portal
./recover.sh ssh-keys --limit portal,seedbox
```

`./recover.sh` is the only supported entry point for this recovery. It holds the machine-local lifecycle lock for the duration and reconciles the dependencies the playbook consumes before Ansible starts. Running `playbooks/add-ssh-keys-to-lxcs.yml` directly fails the controller prerequisite, which requires the wrapper.

Recovery reaches the guests with `pct exec` on the Proxmox host, so containers do not need to be SSH-accessible beforehand. It is idempotent and non-destructive: it only adds keys, never removes them.

It reads the control node public key from `~/.ansible/ssh/proxmox_lxc.pub`, the one machine-global location, and fails when that file is absent. No playbook generates that key pair; you create or restore it yourself.

**Prerequisites**: the container must be running, and the Proxmox host must already trust the controller identity. This command never enrolls the Proxmox host implicitly, so when that trust is absent it stops before any effect and points at the separate explicit transition:

```bash
./recover.sh proxmox-host-ssh
```

## Proxmox Host Access: Supported Scope

The trust check uses the configured Proxmox host, SSH user, and port for a fresh public-key login with `~/.ansible/ssh/proxmox_lxc`. It deliberately does not load `ssh_config`, so another configured identity or an existing shared connection cannot supply a successful trust result. A normal DNS hostname is supported; a host alias defined only in `ssh_config`, or a route that depends on `ProxyJump` there, is not. Host-key checking remains `accept-new` against the normal known-hosts files.

The supported lifecycle assumes root access on the Proxmox host. Enrollment installs the selected key for the configured SSH user, but changing that user alone does not provide end-to-end non-root operation: the subsequent `pct` validation runs without privilege escalation. Non-root support is a separate capability, not part of SSH enrollment.

Enrollment installs the selected identity; it is not general SSH repair. It does not promise to fix unrelated pre-existing ownership, permissions, or `sshd` configuration. If the selected identity still cannot authenticate after installation, enrollment fails rather than claiming success or attempting broader repairs.

These limits were retained when [PR #359](https://github.com/faviann/homelab-iac/pull/359) completed. Differences between the trust check, enrollment's connection handling, and Ansible's `pct` connection are recorded in [deferred investigation #362](https://github.com/faviann/homelab-iac/issues/362). That investigation may conclude that no change is needed; the observations are not a requirement to unify the SSH paths.

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
