# Ansible Inventory Structure

## Design Principles

### Resource Tiers (Mutually Exclusive)

Each host belongs to **exactly one** tier that defines its compute resources:

- **tier_tiny**: 1 core, 1GB RAM, 8GB disk
- **tier_small**: 2 cores, 4GB RAM, 8GB disk
- **tier_medium**: 4 cores, 16GB RAM, 8GB disk
- **tier_large**: 8 cores, 32GB RAM, 8GB disk

All tiers use network bridge `vmbr1` by default.

### Capabilities (Compositional)

Hosts can belong to **multiple** capability groups:

- **cap_docker**: Docker runtime, compose, and the docker-agents managed stack
- **cap_gpu**: GPU passthrough for hardware acceleration
- **cap_wireguard**: WireGuard kernel module access

Every `cap_docker` host automatically receives the **docker-agents** stack:
- `docker-metadata-proxy` — read-only Docker socket proxy for Homepage discovery
- `dockwatch-socket-proxy` — write-capable proxy for container management
- `dockwatch` — container monitoring UI
- `traefik-kop` — Traefik label replication (controlled by `traefik_kop_enabled`, default `true`; set `false` on portal)

Traefik discovery contract: routes are created from service labels. Apply labels only to intentionally exposed user-facing services.

## Variable Precedence

Variables merge in this order (later overrides earlier):

1. `group_vars/all/` — base configuration for all hosts
2. `group_vars/tier_*/` — resource specifications
3. `group_vars/cap_*/` — capability flags
4. `host_vars/<hostname>.yml` — host-specific overrides

### Example: Variable Inheritance

For `servarr` in `tier_medium` + `cap_docker`:

```yaml
# 1. group_vars/all/proxmox.yml
proxmox_api_host: "proxmox.lan"
proxmox_default_node: "proxmox"

# 2. group_vars/tier_medium/vars.yml
lxc_cores: 4
lxc_memory: 16384
lxc_disk: "8"

# 3. group_vars/cap_docker/vars.yml
install_docker: true
lxc_features: [nesting=1, keyctl=1]

# 4. host_vars/servarr.yml
proxmox_lxc_overrides:
  vmid: 303
  hostname: servarr
  cores: "{{ lxc_cores }}"    # inherited: 4
  memory: "{{ lxc_memory }}"  # inherited: 16384
```

## Adding New Hosts

### Step 1: Determine Tier and Capabilities

- Does it run Docker? → `cap_docker`
- Does it need GPU? → `cap_gpu`
- Does it need VPN? → `cap_wireguard`
- Disable traefik-kop? → Set `traefik_kop_enabled: false` in host_vars

### Step 2: Add to `inventory/hosts.yml`

```yaml
tier_small:
  hosts:
    mynewhost:

cap_docker:
  hosts:
    mynewhost:
```

### Step 3: Create `inventory/host_vars/mynewhost.yml`

```yaml
---
lxc_hwaddr: "BC:24:11:XX:XX:XX"
default_domain: admin.faviann.com

proxmox_lxc_overrides:
  vmid: 305
  hostname: mynewhost
  description: "My new service managed via Ansible"
  tags:
    - ansible
    - mynewhost
```

Override only what differs from the tier defaults. Leave CPU, memory, disk, network, and mount settings out unless they genuinely need to change.

## Validation and Safety

The provisioning playbook includes automated validation to prevent accidental overwrites:

**Pre-provisioning checks:**
1. Duplicate VMID detection — blocks run if multiple hosts claim the same VMID
2. Proxmox state comparison — compares inventory against actual Proxmox containers
3. Strict name matching — container names must match exactly

**Conflict types detected:**
- ID match, name mismatch: VMID exists with different container name
- Name match, ID mismatch: Container name exists with different VMID
- Cross-mismatch: Both exist but point to different containers

**Behavior modes** (`inventory/group_vars/all/proxmox.yml`):

```yaml
proxmox_validation_strict: false  # Default: skip conflicting hosts, continue with others
proxmox_validation_strict: true   # Abort entire playbook on any conflict
```

**Error messages include remediation options:**
```
Host 'portal': Inventory expects [vmid=300, name=portal],
but Proxmox shows [vmid=300, name=oldserver] - ID match, name mismatch

Remediation options:
  - Fix inventory name in inventory/host_vars/portal.yml to match Proxmox: oldserver
  - OR rename container in Proxmox: pct set 300 -hostname portal
  - OR destroy conflicting container: pct destroy 300
```
