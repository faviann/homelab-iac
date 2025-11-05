# Docker Installation Integration - Update Summary

## Overview

Added Docker installation to the `lxc_internal_setup` role using the official `geerlingguy.docker` Ansible role.

## Changes Made

### New Files Created

1. **`playbooks/roles/lxc_internal_setup/tasks/docker_install.yml`**
   - New task file for Docker installation
   - Uses `geerlingguy.docker` role
   - Installs Docker and Docker Compose plugin
   - Configures Docker daemon logging
   - Verifies installation

### Files Modified

2. **`playbooks/roles/lxc_internal_setup/tasks/main.yml`**
   - Added Docker installation step before Docker setup
   - Maintains proper execution order:
     1. System updates
     2. Journald config
     3. **Docker install** ← NEW
     4. Docker setup
     5. Reboot

3. **`playbooks/roles/lxc_internal_setup/defaults/main.yml`**
   - Added Docker installation configuration variables
   - Configure Docker Compose plugin installation
   - Configure Docker daemon options (log rotation)

4. **`playbooks/roles/lxc_internal_setup/tasks/docker_setup.yml`**
   - Added explicit docker group creation
   - Ensures group exists before creating user
   - Prevents race condition with Docker installation

5. **`playbooks/roles/lxc_internal_setup/README.md`**
   - Updated requirements to include geerlingguy.docker
   - Added Docker installation variables documentation
   - Updated task breakdown to include docker_install step
   - Added new tags documentation
   - Updated troubleshooting section with Docker installation issues
   - Updated selective execution examples

6. **`inventory/group_vars/cap_docker/vars.yml`**
   - Added comment documenting automatic Docker installation

7. **`collections/requirements.yml`**
   - Already includes geerlingguy.docker (version 7.8.0) ✓

## New Variables

Added to `defaults/main.yml`:

```yaml
# Docker installation (uses geerlingguy.docker role)
lxc_internal_docker_install_compose_plugin: true
lxc_internal_docker_compose_package: docker-compose-plugin
lxc_internal_docker_compose_package_state: present

# Docker daemon options
lxc_internal_docker_daemon_options:
  log-driver: "json-file"
  log-opts:
    max-size: "10m"
    max-file: "3"
```

## New Tags

- `docker_install` - Docker installation only
- `docker_setup` - Docker environment setup only  
- `docker` - All Docker tasks (install + setup)

## Execution Flow

### Before (Missing Step)
```
System Update → Journald → Docker Setup* → Reboot
                                ↑
                        *Assumed Docker already installed
```

### After (Complete)
```
System Update → Journald → Docker Install → Docker Setup → Reboot
                              ↑
                        Installs Docker automatically
```

## Docker Installation Details

### What Gets Installed

Via `geerlingguy.docker` role:
- Docker Engine (latest stable)
- Docker Compose plugin (v2)
- Docker service (started & enabled)

### Configuration Applied

- **Logging**: JSON file driver with rotation
  - Max size: 10MB per log file
  - Max files: 3 rotated files
- **Users**: Adds `dockeruser` to docker group (done in docker_setup.yml)
- **Service**: Enabled to start on boot

### Verification

The role automatically verifies:
- Docker version installed
- Docker Compose version installed
- Docker service running

## Usage Examples

### Full Configuration (includes Docker install)
```bash
ansible-playbook site.yml --tags configure
```

### Install Docker only
```bash
ansible-playbook site.yml --tags docker_install --limit cap_docker
```

### Reconfigure Docker environment (skip reinstall)
```bash
ansible-playbook site.yml --tags docker_setup --limit cap_docker
```

### All Docker tasks
```bash
ansible-playbook site.yml --tags docker --limit cap_docker
```

## Prerequisites

The role requires:
1. ✅ `geerlingguy.docker` role installed (via `collections/requirements.yml`)
2. ✅ `community.docker` collection installed (via `collections/requirements.yml`)
3. ✅ LXC features enabled (`nesting=1`, `keyctl=1`) - done by host-side config
4. ✅ Internet access in containers (to download Docker packages)

## Testing Recommendations

1. **Syntax check**:
   ```bash
   ansible-playbook site.yml --syntax-check
   ```

2. **Test Docker installation on single container**:
   ```bash
   ansible-playbook site.yml --limit gatekeeper --tags docker_install -v
   ```

3. **Verify Docker works**:
   ```bash
   ssh root@gatekeeper.faviann.vms "docker run hello-world"
   ```

4. **Full configuration test**:
   ```bash
   ansible-playbook site.yml --limit gatekeeper --tags configure
   ```

## Troubleshooting

### Docker installation fails

**Check LXC features**:
```bash
pct config <vmid> | grep features
# Should show: features: keyctl=1,nesting=1
```

**Check internet access**:
```bash
ssh root@container.faviann.vms "ping -c 3 8.8.8.8"
```

**Check apt repositories**:
```bash
ssh root@container.faviann.vms "apt update"
```

### Docker service not starting

**Check logs**:
```bash
ssh root@container.faviann.vms "journalctl -u docker -n 50"
```

**Verify features**:
- LXC must have `nesting=1` for Docker to work
- LXC must have `keyctl=1` for Docker networking

## Benefits

✅ **Complete automation** - No manual Docker installation needed
✅ **Consistent installation** - Same Docker version across all containers
✅ **Proper logging** - Log rotation configured from the start
✅ **Verified installation** - Automatic verification of Docker and Compose
✅ **Idempotent** - Safe to run multiple times
✅ **Official role** - Uses trusted geerlingguy.docker role
✅ **Tagged execution** - Can install/configure separately

## Backward Compatibility

This change is **fully compatible** with existing infrastructure:
- Containers without `cap_docker` are unaffected
- Docker installation is conditional (`when: "'cap_docker' in group_names"`)
- If Docker is already installed, geerlingguy.docker role is idempotent
- No changes to existing provisioning or host-side configuration

## Next Steps

1. **Run bootstrap** to ensure geerlingguy.docker role is installed:
   ```bash
   ansible-playbook bootstrap.yml
   ```

2. **Test on a new container** or existing container:
   ```bash
   ansible-playbook site.yml --limit gatekeeper
   ```

3. **Verify Docker is working**:
   ```bash
   ssh root@gatekeeper.faviann.vms "docker --version"
   ssh root@gatekeeper.faviann.vms "docker compose version"
   ```

## Summary

Docker installation is now fully integrated into the LXC internal setup workflow. The role automatically installs Docker on all containers in the `cap_docker` group using the trusted geerlingguy.docker role, with proper logging configuration and verification steps.
