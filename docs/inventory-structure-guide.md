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

- **cap_docker**: Docker runtime, compose, and the default-on docker-agents managed stack
- **cap_gpu**: GPU passthrough for hardware acceleration
- **cap_wireguard**: WireGuard kernel module access

Every `cap_docker` host receives Docker runtime support. By default, `docker_agents_enabled: true`
also seeds the managed `docker-agents` stack:
- `docker-metadata-proxy` — read-only Docker socket proxy for Homepage discovery
- `dockwatch-socket-proxy` — write-capable proxy for container management
- `dockwatch` — container monitoring UI
- `traefik-kop` — Traefik label replication (controlled by `traefik_kop_enabled`, default `true`; set `false` on portal)
- `hawser` — Standard-mode Dockhand remote agent on every non-`portal` Docker host where `docker_agents_enabled: true`

Hosts that need Docker without Dockhand/Homepage sidecars, such as `workstation`, should set
`docker_agents_enabled: false` in `host_vars`.

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
proxmox_lxc_group_defaults:
  cores: 4
  memory: 16384
  disk: "8"

# 3. group_vars/cap_docker/vars.yml
install_docker: true
proxmox_lxc_capability_defaults:
  features: [nesting=1, keyctl=1]

# 4. host_vars/servarr.yml
proxmox_lxc_overrides:
  vmid: 303
  hostname: servarr
```

## Capability Group Requirements

Capability groups do more than toggle booleans. They also publish role inputs that are
required by downstream provisioning and configuration roles.

| Group | Variables provided | Roles consuming them |
|-------|--------------------|----------------------|
| `cap_docker` | `docker_enabled`, `install_docker`, `docker_user`, `docker_uid`, `docker_gid`, `proxmox_lxc_capability_defaults.features`, `docker_agents_enabled`, `traefik_kop_enabled`, `dockhand_hawser_token` | `config/lxc_docker_environment`, `config/lxc_docker_runtime`, `provisioning/lxc_spec_builder` |
| `cap_wireguard` | `wireguard_enabled` | `infrastructure/proxmox_lxc_host_config` |
| `cap_gpu` | `gpu_enabled` | `infrastructure/proxmox_lxc_host_config` |

If a host should run Docker, it must be in `cap_docker` so the Docker roles and
`lxc_spec_builder` receive the expected user and feature variables. Missing membership
now fails early with a clear validation message instead of an undefined-variable error
later in the run.

The Hawser remote-agent baseline follows `docker_agents_enabled`: hosts with
`docker_agents_enabled: false`, such as `workstation`, do not receive Hawser or the
managed `docker-agents` stack. `portal` additionally sets `traefik_kop_enabled: false`
and is excluded from Hawser because it hosts Dockhand rather than acting as a remote
service host.

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

## Temporary Template Overrides

For one-off reprovisioning or migration waves, add an `ostemplate` override in the host's
`proxmox_lxc_overrides` block instead of changing the global template immediately.

```yaml
proxmox_lxc_overrides:
  vmid: 303
  hostname: servarr
  ostemplate: "local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst"
```

This is the preferred way to do a Debian release canary. The per-host override is merged after
the global defaults, so it only affects the selected host.

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
