# Proxmox Host SSH Access

## Why SSH is Required

Certain LXC configuration operations cannot be performed via the Proxmox API, even with `root@pam` credentials. Attempting to set restricted feature flags returns:

```
403 Forbidden: Permission check failed (changing feature flags (except nesting) is only allowed for root@pam)
```

Affected features: `keyctl=1` (required for Docker kernel keyring support) and any future flags Proxmox restricts to pct.

## Architecture

Three roles handle this split:

1. **`proxmox_host_bootstrap`** — Sets up SSH key auth on first run. Tests if key auth works; prompts for root password once if not; adds the public key; validates. Subsequent runs skip the prompt entirely.
2. **`proxmox_lxc_provision`** — Filters the feature list before the API call, passing only API-compatible features.
3. **`proxmox_lxc_host_config`** — Applies restricted features via `pct set` on the Proxmox host after provisioning.

```
site.yml execution:
  1. proxmox_host_bootstrap  →  SSH key setup (password prompt once, then never again)
  2. API validation
  3. Per-LXC:
       proxmox_lxc_provision      →  API call with nesting=1 only
       proxmox_lxc_host_config    →  pct set <vmid> -features keyctl=1,nesting=1
```

## Feature Flag Handling

| Feature | Via API | Via pct |
|---------|---------|---------|
| `nesting=1` | ✅ | — |
| `keyctl=1` | ❌ (filtered out) | ✅ |

The `proxmox_lxc_provision` role automatically strips restricted features before the API call. `proxmox_lxc_host_config` reads the current container config, merges desired features, and only runs `pct set` if a change is needed.

## Troubleshooting

**Password prompt appears on every run**

SSH key wasn't successfully added. Verify manually:
```bash
ssh -i .ansible/ssh/proxmox_lxc root@proxmox.lan
```
If it fails, check that `PubkeyAuthentication yes` is set in `/etc/ssh/sshd_config` on the Proxmox host and that `/root/.ssh/authorized_keys` has mode 600.

**`keyctl=1` not present after provisioning**

```bash
# Check current container features
ssh root@proxmox.lan pct config <vmid> | grep features

# Re-run host config phase
ansible-playbook site.yml --tags host_prep -vv
```

Common causes: `lxc_features` not defined in inventory, or `proxmox_lxc_host_config_enabled` set to false.
