---
# Ansible Inventory Structure - Best Practices and Guidelines

## Overview

This document describes the resource-based inventory structure for managing
Proxmox LXC containers.

## Directory Structure

```text
inventory/
|-- hosts.yml
|-- group_vars/
|   |-- all/
|   |   |-- proxmox.yml
|   |   `-- vault.yml
|   |-- proxmox_api/vars.yml
|   |-- tier_tiny/vars.yml
|   |-- tier_small/vars.yml
|   |-- tier_medium/vars.yml
|   |-- tier_large/vars.yml
|   |-- cap_docker/vars.yml
|   |-- cap_gpu/vars.yml
|   `-- cap_wireguard/vars.yml
`-- host_vars/
  |-- auth.yml
  |-- portal.yml
  |-- seedbox.yml
  `-- servarr.yml
```

## Design Principles

### 1. Resource Tiers (Mutually Exclusive)

Each host belongs to **exactly ONE** resource tier group that defines its compute resources:

- **tier_tiny**: 1 core, 1GB RAM, 8GB disk
- **tier_small**: 2 cores, 4GB RAM, 8GB disk
- **tier_medium**: 4 cores, 16GB RAM, 8GB disk
- **tier_large**: 8 cores, 32GB RAM, 8GB disk

All tiers use the same network bridge (`vmbr1`) by default.

### 2. Functional Groups (Compositional/Additive)

Hosts can belong to **MULTIPLE** functional groups based on capabilities needed:

- **cap_docker**: LXCs with Docker runtime, compose, and Dockge baseline
- **cap_gpu**: LXCs with GPU passthrough for hardware acceleration
- **cap_wireguard**: LXCs with WireGuard kernel module access
Every `cap_docker` host automatically receives the **docker-agents** managed stack:
  - docker-metadata-proxy (read-only Docker socket proxy for Homepage discovery)
  - dockwatch-socket-proxy (write-capable proxy for container management)
  - dockwatch (container monitoring UI)
  - traefik-kop (Traefik label replication — controlled by `traefik_kop_enabled`, default `true`; set `false` on portal)

Traefik discovery contract:
- Routes are created from service labels.
- If a service has no Traefik labels, no public route is expected.
- Apply labels only to intentionally exposed user-facing services.

### 3. Exception Handling

Resource overrides for special cases are handled in `host_vars/`:

```yaml
# Example: portal.yml
proxmox_lxc_overrides:
  vmid: 300
  hostname: portal
  description: "Portal service managed via Ansible"
```

Use overrides **sparingly** and document the reason for each exception.

## Variable Precedence

Ansible applies variables in this order (later sources override earlier ones):

1. **group_vars/all/**: Base configuration for all hosts
2. **group_vars/{resource_tier}.yml**: Resource specifications
3. **group_vars/{functional_group}.yml**: Functional capabilities
4. **host_vars/{hostname}.yml**: Host-specific overrides

### Example: Variable Inheritance

For a host named `servarr` in `tier_medium` and `cap_docker`:

```yaml
# Inherited variables (in merge order):
# 1. group_vars/all/proxmox.yml
proxmox_api_host: "proxmox.lan"
proxmox_default_node: "proxmox"
proxmox_default_mounts: { ... }

# 2. group_vars/tier_medium/vars.yml
lxc_cores: 4
lxc_memory: 16384
lxc_disk: "8"
lxc_network_bridge: vmbr1

# 3. group_vars/cap_docker/vars.yml
install_docker: true
docker_user: dockeruser
lxc_features: [nesting=1, keyctl=1]

# 4. host_vars/servarr.yml (can override any of the above)
proxmox_lxc_overrides:
  vmid: 302
  hostname: servarr
  cores: "{{ lxc_cores }}"      # Uses inherited value: 4
  memory: "{{ lxc_memory }}"    # Uses inherited value: 16384
```

## Adding New Hosts

### Step 1: Determine Resource Tier

Choose the appropriate tier based on workload requirements:
- Tiny: Monitoring agents, lightweight proxies
- Small: Development tools, small web services
- Medium: Application servers, media processing
- Large: Database servers, media servers with transcoding

### Step 2: Determine Functional Groups

Select all applicable functional groups:
- Does it run Docker? → Add to `cap_docker`
- Does it need GPU? → Add to `cap_gpu`
- Does it need VPN? → Add to `cap_wireguard`
- Does it need traefik-kop disabled? → Set `traefik_kop_enabled: false` in host_vars

### Step 3: Add to Inventory

Edit `inventory/hosts.yml`:

```yaml
tier_small:
  hosts:
    mynewhost:

cap_docker:
  hosts:
    mynewhost:

# traefik_kop_enabled defaults to true from cap_docker
# Override in host_vars/mynewhost.yml only if needed
```

### Step 4: Create Host Variables

Create `inventory/host_vars/mynewhost.yml`:

```yaml
---
# Host-specific configuration for mynewhost
# Inherits from: tier_small, cap_docker

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

## Best Practices

### 1. Use Templates for Common Patterns

Most host_vars files now only declare what is unique to the host. Copy an existing file and edit the override map:
- Use `auth.yml` as a template for small docker hosts
- Use `seedbox.yml` as a template for larger hosts with extra capability flags

### 2. Document Exceptions

When overriding resource allocations, add a comment explaining why:

```yaml
# OVERRIDE: Extra memory for heavy transcoding workload
proxmox_lxc_overrides:
  memory: 65536  # example: 64GB instead of tier_large default 32GB
```

### 3. Keep Defaults Generic

Variables in `group_vars/` should represent sensible defaults, not host-specific values. Host-specific tweaks belong in `proxmox_lxc_overrides`.

### 4. Ensure Unique VMIDs

Each LXC must have a unique VMID across the entire inventory. The validation system will detect and block duplicate VMID assignments before any provisioning occurs.

```yaml
# BAD - duplicate VMID
portal:
  proxmox_lxc_overrides:
    vmid: 301  # ❌ Already used by another host

# GOOD - unique VMID
portal:
  proxmox_lxc_overrides:
    vmid: 300  # ✓ Unique across inventory
```

## Validation and Safety

### VMID/Name Mismatch Detection

The playbook includes automated validation to prevent configuration drift and accidental overwrites:

**Pre-Provisioning Checks:**
1. **Inventory duplicate VMID detection** - Blocks runs if multiple hosts claim the same VMID
2. **Proxmox state comparison** - Compares inventory expectations against actual Proxmox containers
3. **Strict name matching** - Container names must match exactly (no automatic FQDN normalization)

**Detected Conflicts:**
- **ID match, name mismatch**: VMID exists in Proxmox with different container name
- **Name match, ID mismatch**: Container name exists with different VMID
- **Cross-mismatch**: Both VMID and name exist but point to different containers

**Behavior Modes:**

```yaml
# inventory/group_vars/all/proxmox.yml
proxmox_validation_strict: false  # Default: skip conflicting hosts, continue with others
proxmox_validation_strict: true   # Alternative: abort entire playbook on any conflict
```

**Default (non-strict) mode:**
- Conflicting hosts are **skipped** in provision, host_config, and configure phases
- Other hosts proceed normally
- Summary shows eligible vs skipped host counts

**Strict mode:**
- **Entire playbook aborts** before provisioning if any conflicts exist
- Use when you need guaranteed all-or-nothing deployment

**Error Messages:**

Conflicts include detailed remediation guidance:
```
Host 'portal': Inventory expects [vmid=300, name=portal], 
but Proxmox shows [vmid=300, name=oldserver] - ID match, name mismatch

Remediation options:
  - Fix inventory name in inventory/host_vars/portal.yml to match Proxmox: oldserver
  - OR rename container in Proxmox: pct set 300 -hostname portal
  - OR destroy conflicting container: pct destroy 300
```

**Validation Execution:**

Validation runs automatically (tagged with `always`) before any provisioning work:
```bash
# Run only validation (pre-flight check)
ansible-playbook site.yml --tags validation

# Full run (validation runs first automatically)
ansible-playbook site.yml

# Provision specific hosts (validation still runs first)
ansible-playbook site.yml --limit portal --tags provision
```

### 4. Override Only What You Need

Leave CPU, memory, disk, network, and mount settings out of host_vars unless they genuinely differ. The provisioning role builds those from tier and capability groups automatically.

### 5. Organize Functional Groups Logically

- All `cap_docker` hosts automatically get the docker-agents stack (dockwatch, socket proxies)
- For `cap_docker` hosts with `traefik_kop_enabled: true` (default), `default_domain` in host_vars is required
- Use `traefik_kop_enabled: false` in host_vars to opt out of traefik-kop (for example, on portal)
- GPU access is typically independent of other functional groups

### 6. Network Resolution

Hosts will be resolved via DNS as `{hostname}.faviann.vms` or through Proxmox API using their container ID or name.

## Workflow Integration

### Provisioning Workflow

1. **Control node** connects to Proxmox API (`proxmox_api` group)
2. Playbook provisions LXC using variables from:
   - Resource tier (cores, memory, disk)
   - Functional groups (features, capabilities)
   - Host vars (vmid, hostname, specific config)
3. **After provisioning**, control node can connect to LXC via SSH for configuration
4. Configuration playbooks use functional group variables to install software:
  - `cap_docker` → Install Docker and deploy Dockge baseline
   - `cap_gpu` → Configure GPU passthrough
  - `cap_docker` → Also deploys universal docker-agents stack (dockwatch, socket proxies, traefik-kop if enabled)

### Example Playbook Targets

```yaml
# Provision all small servers
- hosts: tier_small
  roles:
    - proxmox_lxc_provision

# Configure all Docker hosts (also deploys docker-agents stack)
- hosts: cap_docker
  roles:
    - docker_install
    - lxc_docker_environment
```

## Variable Conflict Resolution

### Potential Conflicts

When a variable is defined in multiple groups, Ansible's merge order determines the final value. The order is **alphabetical by group name** for groups at the same level, then overridden by host_vars.

### Avoiding Conflicts

1. **Use unique variable names per group**
   ```yaml
   # Good: Prefixed variable names
   docker_user: dockeruser           # in cap_docker.yml
   wireguard_interface: wg0          # in cap_wireguard.yml
   
   # Avoid: Generic names that might conflict
   user: dockeruser
   interface: wg0
   ```

2. **Use nested dictionaries for complex config**
   ```yaml
   # Good: Nested structure
   lxc_features:
     - nesting=1
     - keyctl=1
   
   # Better: Merging dictionaries
   lxc_config:
     docker:
       nesting: true
       keyctl: true
     gpu:
       device_passthrough: true
   ```

3. **Document merge behavior in group_vars**
   ```yaml
   # This variable merges with cap_docker.lxc_features
   lxc_features:
     - nesting=1
     - keyctl=1
   ```

## Scaling Guidance

### Small Scale (1-10 hosts)
- Current structure is sufficient
- All hosts can be in `hosts.yml`
- Keep group_vars as-is

### Medium Scale (10-50 hosts)
- Consider splitting `hosts.yml` by function:
  - `inventory/production.yml`
  - `inventory/staging.yml`
- Add environment-specific group_vars:
  - `group_vars/production/`
  - `group_vars/staging/`

### Large Scale (50+ hosts)
- Use dynamic inventory via Proxmox API
- Keep static inventory for core services only
- Add automation for host_vars generation
- Consider Ansible Tower/AWX for centralized management

## Migration from Legacy Structure

If migrating from the previous structure:

1. **Map old variables to new groups**
   - `disk_size`, `ram_size`, `core_count` → Resource tier variables
   - `enable_nvidia`, `enable_wireguard` → Functional group membership

2. **Move host-specific config to host_vars**
   - Each host in old `lxc_containers` → New host_vars file
   - Reference group variables instead of hardcoded values

3. **Update playbooks**
   - Change group targets from `lxc_containers` to resource/functional groups
   - Use new variable names (`lxc_cores` vs `core_count`)

4. **Test incrementally**
   - Validate syntax: `yamllint inventory/`
   - Check variable resolution: `ansible-inventory --host <hostname> --yaml`
   - Provision test host before migrating production hosts

## Validation and Testing

### Syntax Validation

```bash
# Validate YAML syntax
yamllint inventory/

# Check inventory structure
ansible-inventory --list --yaml

# View variables for specific host
ansible-inventory --host servarr --yaml
```

### Variable Inspection

```bash
# Show all variables for a host
ansible-inventory --host portal --yaml

# Show group membership
ansible-inventory --graph

# Debug variable precedence
ansible -m debug -a "var=hostvars[inventory_hostname]" servarr
```

### Test Provisioning

```bash
# Dry-run mode (check mode)
ansible-playbook playbooks/lxc-provision.yml --check --diff

# Provision single host
ansible-playbook playbooks/lxc-provision.yml --limit auth

# Provision by resource tier
ansible-playbook playbooks/lxc-provision.yml --limit tier_small
```

## Troubleshooting

### Variables Not Applied

**Problem**: Host not getting expected variables from group
**Solution**: Check group membership in `hosts.yml` and verify YAML indentation

### Variable Override Not Working

**Problem**: host_vars value not overriding group_vars
**Solution**: Ensure variable name matches exactly (case-sensitive)

### Unexpected Variable Value

**Problem**: Variable has unexpected value from wrong group
**Solution**: Use `ansible-inventory --host <name> --yaml` to trace variable sources

## Additional Resources

- [Ansible Inventory Documentation](https://docs.ansible.com/ansible/latest/inventory_guide/)
- [Variable Precedence](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_variables.html#variable-precedence-where-should-i-put-a-variable)
- [Group Variables](https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html#organizing-host-and-group-variables)
