# Debian 13 LXC Migration Runbook

Date: 2026-04-14
Status: ready for execution

## Current Repo State

- The global default LXC template now points at `local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst`.
- `servarr` is the first real rebuild canary via a host-specific `ostemplate` override.
- Existing LXCs are not re-imaged automatically. The provisioner still uses `state: present` with `update: false`, so a template change only applies when a container is newly created or explicitly destroyed and recreated.

## Fleet Order

Recommended migration order:

1. `servarr` (VMID 303) — first real canary
2. `public` (VMID 305)
3. `seedbox` (VMID 302)
4. `jellyfin` (VMID 304)
5. `auth` (VMID 301)
6. `portal` (VMID 300)

This keeps the first rebuild on a simpler Docker host and leaves identity and ingress for the end.

## Pre-Flight Checks

Run before every host rebuild:

```bash
source .ansible/venv/bin/activate
ansible-playbook playbooks/validate-infrastructure.yml
```

Confirm on Proxmox:

```bash
ssh -i .ansible/ssh/proxmox_lxc root@proxmox.lan "ls -1 /var/lib/vz/template/cache/debian-13-standard_13.1-2_amd64.tar.zst"
```

## Per-Host Migration Procedure

Replace `<host>` and `<vmid>` with the current target.

### 1. Capture host state

```bash
ssh -i .ansible/ssh/proxmox_lxc root@proxmox.lan "pct config <vmid>"
ssh -i .ansible/ssh/proxmox_lxc root@<host> "cat /etc/os-release"
ssh -i .ansible/ssh/proxmox_lxc root@<host> "docker ps -a"
ssh -i .ansible/ssh/proxmox_lxc root@<host> "findmnt -rn -o TARGET,SOURCE /shared /conf /data /ephemeral"
```

### 2. Create a Proxmox backup

```bash
ssh -i .ansible/ssh/proxmox_lxc root@proxmox.lan "vzdump <vmid> --mode snapshot --compress zstd --storage <backup-storage>"
```

### 3. Stop workloads cleanly

```bash
ssh -i .ansible/ssh/proxmox_lxc root@<host> "cd /conf/docker/stacks && docker compose ls"
ssh -i .ansible/ssh/proxmox_lxc root@proxmox.lan "pct stop <vmid>"
```

### 4. Destroy the old Debian 12 CT

```bash
ssh -i .ansible/ssh/proxmox_lxc root@proxmox.lan "pct destroy <vmid>"
```

The shared bind mounts remain outside the CT root filesystem, so this destroys the container root disk, not the shared service data under `/shared`, `/conf`, or `/data`.

### 5. Recreate and configure from Ansible

```bash
source .ansible/venv/bin/activate
ansible-playbook site.yml --limit <host>
```

### 6. Validate the rebuilt host

```bash
ssh -i .ansible/ssh/proxmox_lxc root@<host> "cat /etc/os-release"
ssh -i .ansible/ssh/proxmox_lxc root@<host> "docker --version && docker compose version"
ssh -i .ansible/ssh/proxmox_lxc root@<host> "docker ps"
ssh -i .ansible/ssh/proxmox_lxc root@<host> "systemctl --failed"
```

For Docker hosts, also re-check the container runtime state:

```bash
source .ansible/venv/bin/activate
ansible -i inventory/hosts.yml <host> -o -m shell -a "printf 'version='; dpkg-query --showformat='\${Version}' --show containerd.io; printf ' hold='; if apt-mark showhold | grep -qx containerd.io; then echo yes; else echo no; fi"
```

Expected result: the rebuilt host reports Debian 13, Docker starts normally, and `containerd.io` is not held.

## Canary Host

`servarr` is already configured as the first Debian 13 rebuild candidate in `inventory/host_vars/servarr.yml`.

First real canary commands:

```bash
source .ansible/venv/bin/activate
ansible-playbook playbooks/validate-infrastructure.yml
ssh -i .ansible/ssh/proxmox_lxc root@proxmox.lan "vzdump 303 --mode snapshot --compress zstd --storage <backup-storage>"
ssh -i .ansible/ssh/proxmox_lxc root@proxmox.lan "pct stop 303 && pct destroy 303"
ansible-playbook site.yml --limit servarr
ssh -i .ansible/ssh/proxmox_lxc root@servarr "cat /etc/os-release"
```

If `servarr` passes, continue through the fleet order above.

## Rollback

If a host rebuild fails:

1. Restore the latest `vzdump` backup from Proxmox.
2. Set the host's `ostemplate` override back to the Debian 12 template if needed.
3. Re-run `ansible-playbook site.yml --limit <host>` after the restore.

## Final Cleanup After Fleet Completion

When all hosts are confirmed on Debian 13:

1. Remove per-host `ostemplate` overrides that were only needed during the migration wave.
2. Keep the global Debian 13 template default in `inventory/group_vars/all/proxmox.yml`.
3. Search the repo for remaining Debian 12 assumptions and remove them.
4. Run one final full deployment:

```bash
source .ansible/venv/bin/activate
ansible-playbook site.yml
```