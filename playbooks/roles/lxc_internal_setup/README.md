# Ansible Role: lxc_internal_setup

Internal configuration for LXC containers after provisioning. This role runs **inside** the LXC containers (via SSH) to configure the operating system and application stack.

## Overview

This role is part of the Proxmox LXC lifecycle automation and runs after:
1. Container provisioning via API (`proxmox_lxc_provision`)
2. Host-side configuration (`proxmox_lxc_host_config`)

It performs internal configuration tasks that cannot be done from the Proxmox host, such as:
- System package updates
- Journald log rotation configuration
- Docker installation (for containers in `cap_docker` group)
- Docker environment setup (for containers in `cap_docker` group)
- Container reboot

## Requirements

- **Ansible**: 2.10+
- **Target OS**: Debian 12+ (containers)
- **Collections**: 
  - `ansible.posix` (for mount module)
  - `community.docker` (installed via collections/requirements.yml)
- **Roles**:
  - `geerlingguy.docker` (installed via collections/requirements.yml)
- **SSH Access**: Control node SSH key must be injected into containers (done by `proxmox_lxc_provision`)
- **Network**: Containers must be resolvable via DNS (`{hostname}.faviann.vms`)

## Role Variables

### System Update Configuration

```yaml
# Whether to update apt cache before upgrading packages
lxc_internal_apt_update_cache: true

# Whether to upgrade all packages
lxc_internal_apt_upgrade: true

# APT cache valid time in seconds (3600 = 1 hour)
lxc_internal_apt_cache_valid_time: 3600
```

### Journald Configuration

```yaml
# Maximum disk space journald can use
lxc_internal_journald_max_use: "1000M"

# Maximum size of individual journal files
lxc_internal_journald_max_file_size: "20M"
```

### Docker Configuration (cap_docker group only)

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

# Shared storage path inside container (source for bind mount)
lxc_internal_shared_mount_source: "/shared/{{ inventory_hostname }}"

# Target mount point for Docker configuration
lxc_internal_root_docker_conf_path: "/conf/docker"

# Ownership for files in shared directory (UID:GID)
lxc_internal_shared_owner: "1001"
lxc_internal_shared_group: "1001"

# Dockge compose directory (relative to mount target)
lxc_internal_dockge_compose_dir: "{{ lxc_internal_root_docker_conf_path }}/dockge"

# Docker user configuration (inherited from cap_docker group vars)
lxc_internal_docker_user: "{{ docker_user | default('dockeruser') }}"
lxc_internal_docker_uid: "{{ docker_uid | default(1000) }}"
lxc_internal_docker_gid: "{{ docker_gid | default(1000) }}"
```

### Reboot Configuration

```yaml
# Whether to reboot the container after configuration
lxc_internal_reboot_enabled: true

# Maximum time to wait for container to reboot (seconds)
lxc_internal_reboot_timeout: 300

# Time to wait after reboot before continuing (seconds)
lxc_internal_post_reboot_delay: 30

# Command to test if container is back online after reboot
lxc_internal_reboot_test_command: "uptime"
```

## Dependencies

This role expects:
- Containers to be provisioned and started
- SSH key injected during provisioning
- Host-side configuration completed (bind mounts, idmaps, features)
- For `cap_docker` containers: Docker will be installed automatically via geerlingguy.docker role

## Example Playbook

### Basic Usage (via site.yml)

```yaml
- name: Configure LXC containers internally
  hosts: lxcs
  gather_facts: false
  tags:
    - configure
    - lxc_internal
  roles:
    - lxc_internal_setup
```

### Standalone Playbook

```yaml
---
- name: Configure LXC containers internally
  hosts: lxcs
  become: false
  gather_facts: false
  roles:
    - role: lxc_internal_setup
      vars:
        lxc_internal_journald_max_use: "500M"
        lxc_internal_reboot_enabled: false
```

### Selective Execution with Tags

```bash
# Run only system updates
ansible-playbook site.yml --tags system_update

# Run only Docker installation
ansible-playbook site.yml --tags docker_install

# Run only Docker setup (without reinstalling Docker)
ansible-playbook site.yml --tags docker_setup

# Run all Docker tasks (install + setup)
ansible-playbook site.yml --tags docker

# Skip reboot
ansible-playbook site.yml --skip-tags reboot

# Configure only specific container
ansible-playbook site.yml --limit gatekeeper
```

## Template Files

The role copies template files from `templates/files/` to `/shared/{{ inventory_hostname }}/` on each container in the `cap_docker` group.

### Directory Structure

```
playbooks/roles/lxc_internal_setup/templates/files/
├── dockge/
│   └── compose.yml          # Dockge configuration
└── example-app/
    ├── compose.yml.j2       # Jinja2 templated compose file
    └── .env.example         # Example environment file
```

### Adding Your Own Templates

1. **Create a folder** in `templates/files/` for your application:
   ```bash
   mkdir -p templates/files/myapp
   ```

2. **Add your files**:
   ```bash
   templates/files/myapp/
   ├── compose.yml
   ├── config.json
   └── .env
   ```

3. **Use Jinja2 templating** (optional):
   - Rename files to `.j2` extension
   - Use Ansible variables: `{{ inventory_hostname }}`, `{{ ansible_host }}`, etc.

4. **Files will be copied to**: `/shared/{{ inventory_hostname }}/myapp/` on each container

### Example Template File

```yaml
# templates/files/myapp/compose.yml.j2
services:
  myapp:
    image: myapp:latest
    container_name: myapp-{{ inventory_hostname }}
    hostname: {{ inventory_hostname }}.faviann.vms
    environment:
      - APP_HOST={{ ansible_host }}
      - APP_NAME={{ inventory_hostname }}
```

## Tasks Breakdown

### 1. System Update (`tasks/system_update.yml`)
- Updates apt cache
- Upgrades all packages
- Removes unnecessary packages (autoremove)
- Cleans apt cache

### 2. Journald Configuration (`tasks/journald_config.yml`)
- Backs up original journald.conf
- Configures log size limits
- Restarts systemd-journald service

### 3. Docker Installation (`tasks/docker_install.yml`) - cap_docker only
- Installs Docker using geerlingguy.docker role
- Installs Docker Compose plugin
- Configures Docker daemon options (logging)
- Starts and enables Docker service
- Verifies Docker and Docker Compose installation

### 4. Docker Setup (`tasks/docker_setup.yml`) - cap_docker only
- Copies template files to shared directory
- Templates Jinja2 files
- Creates bind mount for Docker config
- Adds fstab entry for persistence
- Ensures docker group exists
- Creates dockeruser with proper groups
- Configures passwordless sudo for dockeruser
- Starts Dockge (if compose file exists)

### 5. Reboot (`tasks/reboot.yml`)
- Reboots the container
- Waits for container to come back online
- Gathers facts after reboot
- Displays uptime information

## File Ownership and Permissions

### Shared Directory Files
- **Owner**: UID 1001 (matches dockeruser on host)
- **Group**: GID 1001
- **Reason**: Files created in `/shared/` appear with correct ownership on both host and container

### Docker User
- **Name**: dockeruser (configurable)
- **UID**: 1000 (inside container)
- **Groups**: docker, sudo
- **Password**: Disabled (passwordless account)

### UID/GID Mapping

The UID/GID mapping is configured host-side by `proxmox_lxc_host_config`:

```
Container UID 1000 (dockeruser) → Host UID 1001
Container UID 1001               → Host UID 101001
```

This ensures:
- dockeruser (UID 1000) creates files as UID 1001 on host
- Files in `/shared/` are owned by UID 1001 (both host and container perspective)
- No permission conflicts on shared storage

## Idempotency

The role is fully idempotent and safe to run multiple times:

- **apt upgrade**: Only installs new packages/updates
- **journald config**: Uses `blockinfile` with markers
- **bind mount**: Checks if already mounted before mounting
- **fstab entry**: Uses `state: present` (won't duplicate)
- **user creation**: Creates user only if doesn't exist
- **Dockge startup**: Checks if containers are already running

## Tags

- `system_update` - System package updates
- `updates` - Alias for system_update
- `journald` - Journald configuration
- `logging` - Alias for journald
- `docker` - All Docker-related tasks (installation + setup)
- `docker_install` - Docker installation only
- `docker_setup` - Docker environment setup only
- `reboot` - Container reboot

## Handlers

- `restart journald` - Restarts systemd-journald service when config changes

## Error Handling

The role includes error handling for:
- SSH connection failures (retries with backoff)
- Missing Dockge directory (skips gracefully)
- Already-mounted filesystems (skips mounting)
- Reboot timeout (fails after configured timeout)

## Integration with Project

### Execution Flow

1. **Bootstrap** (`bootstrap.yml`)
   - Prepares control node
   - Installs dependencies
   - Generates SSH key

2. **Provision** (`site.yml` - provision phase)
   - Creates containers via API
   - Injects SSH key
   - Starts containers

3. **Host Config** (`site.yml` - host_config phase)
   - Applies idmaps, bind mounts, features
   - Runs on Proxmox host

4. **Internal Setup** (`site.yml` - configure phase) ← **This Role**
   - Runs inside containers via SSH
   - Updates system packages
   - Configures journald
   - Installs Docker (cap_docker only)
   - Configures Docker environment (cap_docker only)
   - Reboots containers

### Group Membership

- **All LXCs**: System updates, journald config, reboot
- **cap_docker**: Additional Docker setup tasks

### Variable Inheritance

Variables are inherited from:
1. `group_vars/all/proxmox.yml` - Global defaults
2. `group_vars/tier_*/vars.yml` - Resource tiers
3. `group_vars/cap_docker/vars.yml` - Docker configuration
4. `host_vars/{hostname}.yml` - Host-specific overrides
5. Role `defaults/main.yml` - Role defaults

## Troubleshooting

### Container not accessible via SSH

**Problem**: Role fails with "Unable to connect"

**Solutions**:
- Verify container is running: `pct status <vmid>`
- Check SSH key was injected during provisioning
- Test manual SSH: `ssh -i ~/.ssh/proxmox_lxc root@{hostname}.faviann.vms`
- Verify DNS resolution: `ping {hostname}.faviann.vms`

### Docker compose fails to start

**Problem**: Dockge doesn't start

**Solutions**:
- Verify Dockge compose file exists in `templates/files/dockge/`
- Check Docker is installed: `docker --version`
- Verify Docker service is running: `systemctl status docker`
- Verify dockeruser exists and is in docker group: `id dockeruser`
- Check compose file syntax: `docker compose config`
- Check Docker daemon logs: `journalctl -u docker`

### Docker installation fails

**Problem**: Docker installation errors

**Solutions**:
- Verify container has internet access: `ping 8.8.8.8`
- Check apt repositories are accessible
- Verify LXC features are enabled: `pct config <vmid> | grep features`
  - Should include `nesting=1` and `keyctl=1`
- Check role output for specific error messages
- Try manual Docker installation to identify issue

### Bind mount fails

**Problem**: Mount point creation fails

**Solutions**:
- Verify `/shared/{hostname}` exists on host (created by host-side config)
- Check bind mount was applied in container config: `pct config <vmid>`
- Verify idmaps are correct in `/etc/pve/lxc/<vmid>.conf`

### Permission denied errors

**Problem**: Files in `/shared/` have wrong ownership

**Solutions**:
- Verify idmap configuration on host side
- Check `lxc_internal_shared_owner` and `lxc_internal_shared_group` match expected UIDs
- Inside container: `ls -ln /shared/{hostname}` (should show UID 1001)

## Development

### Testing the Role

```bash
# Syntax check
ansible-playbook site.yml --syntax-check

# Dry run (check mode)
ansible-playbook site.yml --check --tags configure

# Run on single container
ansible-playbook site.yml --limit gatekeeper --tags configure

# Verbose output
ansible-playbook site.yml --tags configure -vvv
```

### Adding New Tasks

1. Create task file in `tasks/`
2. Import in `tasks/main.yml`
3. Add appropriate tags
4. Update this README with task description

### Extending Template Files

1. Add files to `templates/files/your-app/`
2. Files are automatically copied to containers
3. Use `.j2` extension for Jinja2 templating
4. Test with: `--tags docker_setup`

## License

Part of ServerManagementScripts repository.

## Author

Faviann

## Version History

- **1.0.0** (2025-11-04): Initial release
  - System updates
  - Journald configuration
  - Docker environment setup
  - Container reboot
