# ServerManagementScripts

Ansible automation for managing Proxmox LXC containers via API from a remote controller.

## Overview

This repository provides Ansible playbooks and configuration to manage LXC containers on Proxmox VE using the Proxmox API. All playbooks run from the **Proxmox LXC control node** (unprivileged Debian/Ubuntu LTS). Do not run Ansible from your dev machine.

### Key Features

- **Remote API-driven**: Manage Proxmox via API from a controller
- **LXC-only**: Focused exclusively on LXC container management (no VMs)
- **Secure**: API token authentication stored in Ansible Vault
- **Static Inventory**: Version-controlled configuration
- **Idempotent**: Safe to run multiple times

### LXC-Only Scope

This repository manages **LXC containers only**. Virtual machines (VMs/KVM) are not supported.

## Prerequisites

- **Controller**: Debian/Ubuntu LTS on the Proxmox LXC control node (unprivileged; do not run from a workstation)
- **Python**: 3.10+ with `python3-venv` and `pip` available (used by the bootstrap playbook)
- **Ansible dependencies**: Installed via `ansible-playbook bootstrap.yml`, which creates the controller virtual environment and pulls in `requirements/pip.txt` and `collections/requirements.yml`
- **Network**: Controller must reach the Proxmox API (HTTPS port 8006)
- **Proxmox**: API token with LXC management permissions

IMPORTANT: Some LXC operations (notably changing LXC "feature" flags such as `nesting=1` or `keyctl=1`) require privileged API access and are only permitted when performed by the local Proxmox root account (`root@pam`). If your automation will set or change LXC feature flags, create and use an API token for `root@pam` (see "Creating API Tokens in Proxmox" below). If you prefer not to use a `root@pam` token, avoid providing `features` in your LXC specs and configure those flags manually on the Proxmox host.

**Note**: This repository now automatically handles restricted feature flags (like `keyctl=1`) by applying them via `pct` commands directly on the Proxmox host after API-based provisioning. The automation will prompt for the Proxmox root password on first run to configure SSH access, then all subsequent operations are passwordless.

### Proxmox Environment Defaults

These defaults are configured for the target homelab:

- **API host**: `proxmox.internal.faviann.com`
- **Node name**: `proxmox`
- **Network bridge**: `vmbr1`
- **Default template**: `local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst`

Adjust or override them in `inventory/group_vars/all/proxmox.yml`, host variables, or playbook vars as needed for your environment.

## First-Time Setup

1. **Bootstrap the controller dependencies.**

   ```bash
   ansible-playbook bootstrap.yml
   ```

   This play creates the controller virtual environment under `.ansible/venv`, installs Python packages from `requirements/pip.txt`, downloads collections from `collections/requirements.yml`, and prepares SSH material. Re-run this play whenever those dependency files change or you upgrade Ansible components.

2. **Configure secrets and inventory.**

   Create and encrypt `inventory/group_vars/all/vault.yml` with your Proxmox API credentials (see [Configuration](#configuration) section below).

3. **Run the orchestration with `site.yml`.**

   ```bash
   ansible-playbook -i inventory/hosts.yml site.yml
   ```

   On first run, the playbook will:
   - Verify bootstrap prerequisites
   - **Automatically detect if SSH access to the Proxmox host is configured**
   - **Prompt for the Proxmox root password only if needed** to add your SSH key
   - Validate API connectivity
   - Provision LXC containers
   - Apply host-side configuration (including restricted feature flags via `pct` commands)

   Subsequent runs will use passwordless SSH and skip the interactive prompt.

   Use `--tags validation` to test connectivity without provisioning, or `--tags provision` to only provision containers.

## Repository Structure

```
.
|-- ansible.cfg
|-- bootstrap.yml
|-- collections/
|   `-- requirements.yml               # Ansible collection dependencies
|-- docs/
|   |-- inventory-structure-guide.md
|   |-- inventory-visualization.md
|   |-- proxmox-host-ssh-automation.md
|   |-- remote-controller-setup.md
|   `-- reference/
|       `-- agent-control-node-reference.md
|-- inventory/
|   |-- hosts.yml                      # Static inventory file
|   |-- group_vars/
|   |   `-- all/
|   |       |-- proxmox.yml            # Non-secret Proxmox configuration
|   |       |-- vault.yml              # Encrypted secrets
|   |       `-- vault.yml.example      # Template for vault
|   `-- host_vars/                     # Host-specific variables
|       |-- codeserver.yml
|       |-- frontend.yml
|       |-- gatekeeper.yml
|       |-- jellyfin.yml
|       `-- media.yml
|-- playbooks/
|   |-- lab-connectivity.yml           # SSH + Proxmox API connectivity checks
|   |-- proxmox_api_check.yml          # API connectivity test
|   |-- lxc-provision.yml              # Inventory-driven LXC provisioning
|   `-- tasks/
|       `-- proxmox_validation.yml
|-- requirements/
|   `-- pip.txt                        # Python package dependencies
|-- site.yml                           # Top-level orchestration playbook
`-- .ansible-lint
```

## Documentation

- **docs/reference/agent-control-node-reference.md** - Control node reference for agents
- **docs/remote-controller-setup.md** - Setup and usage guide
- **docs/proxmox-host-ssh-automation.md** - Host-side SSH automation details
- **docs/inventory-structure-guide.md** - Inventory design and best practices
- **docs/inventory-visualization.md** - Inventory group relationships

## Configuration

### Non-Secret Variables

Edit `inventory/group_vars/all/proxmox.yml` to configure your environment:

```yaml
proxmox_api_host: "proxmox.internal.faviann.com"           # Proxmox hostname or IP
proxmox_api_port: 8006                     # API port (default 8006)
proxmox_api_token_id: "ansible@pve!controller"  # API token ID
proxmox_default_node: "proxmox"           # Default node for operations
proxmox_verify_ssl: false                  # TLS verification (see below)
```

### Secret Variables (Ansible Vault)

Create `inventory/group_vars/all/vault.yml` from the example and encrypt:

```yaml
vault_proxmox_api_token_secret: "your-actual-token-secret"
```

```bash
ansible-vault encrypt inventory/group_vars/all/vault.yml
```

### Inventory

The `inventory/hosts.yml` defines two groups:

- **proxmox_api**: Controller host for API operations (runs locally)
- **lxcs**: Add your LXC containers here if you want to manage them via SSH after provisioning

## Creating API Tokens in Proxmox

1. Log into Proxmox web UI as `root@pam` or another privileged administrative user.
2. Navigate to **Datacenter -> Permissions -> API Tokens**.
3. Create a new token (example: `ansible@pve!controller`).
   - If you will be changing LXC feature flags (for example `nesting=1` or `keyctl=1`), create the token for `root@pam` (for example: `root@pam!ansible-controller`) because changing those feature flags is restricted to the `root@pam` account and other users/tokens will receive a 403 permission error when attempting those changes.
   - **Note**: With the new `proxmox_host_bootstrap` role, restricted features like `keyctl=1` are now applied via SSH and `pct` commands directly on the Proxmox host, so you can use a less-privileged API token (e.g., `ansible@pve`) for API operations. The automation handles restricted features separately.
   - If your automation does not modify feature flags, prefer a least-privilege service account (e.g., `ansible@pve`) with the minimal role required.
4. Grant appropriate permissions (for `root@pam` tokens this is already privileged; for service accounts grant only the roles needed, e.g., `PVEVMAdmin` on the target node/resource).
5. Copy the token secret immediately (shown only once).
6. Add the secret to your `vault.yml` file.

## SSH Access to Proxmox Host

The automation requires SSH access to the Proxmox host to apply certain configuration that cannot be done via API (such as restricted LXC feature flags like `keyctl=1`).

**Automatic Setup**: On first run of `site.yml`, the `proxmox_host_bootstrap` role will:
1. Check if your SSH key already works for `root@proxmox`
2. If not, prompt you for the Proxmox root password
3. Automatically add your SSH public key to the Proxmox host
4. Verify the connection works

**Manual Setup** (optional): If you prefer to configure SSH access manually:
```bash
# Copy your public key to Proxmox
ssh-copy-id -i .ansible/ssh/proxmox_lxc.pub root@proxmox.internal.faviann.com
```

After initial setup, all subsequent playbook runs will use passwordless SSH authentication.

## Example Playbooks

#### Connectivity validation

```bash
ansible-playbook playbooks/lab-connectivity.yml
```

Runs SSH ping checks against managed hosts and calls the Proxmox `/api2/json/version` endpoint using your API token.

### Check API Connectivity

```bash
ansible-playbook playbooks/proxmox_api_check.yml
```

Lists all LXC containers on the default node.

### Provision Inventory-Defined LXCs

```bash
ansible-playbook -i inventory/hosts.yml site.yml --tags provision
```

Builds the effective LXC specs from tier and capability group variables, ensures each container exists through the `proxmox_lxc_provision` role, and applies host-side preparation tasks when enabled. Edit inventory group and host vars to tailor resources and features.

## TLS Certificate Verification

**Current status**: TLS verification is **disabled** by default (`proxmox_verify_ssl: false`) to support self-signed certificates commonly used in homelabs.

**TODO/Future hardening**:
1. Install a trusted certificate on Proxmox or distribute your CA bundle to the controller
2. Set `proxmox_verify_ssl: true` in `inventory/group_vars/all/proxmox.yml`
3. Configure CA path if needed via `api_ca_path` parameter

## Troubleshooting

### Cannot reach Proxmox API

- Verify controller can reach Proxmox host: `curl -k https://proxmox.internal.faviann.com:8006`
- Check firewall rules allow HTTPS (port 8006)
- Verify VPN/network connectivity

### Authentication fails

- Verify API token secret in vault: `ansible-vault view inventory/group_vars/all/vault.yml`
- Check token permissions in Proxmox web UI
- Ensure token ID format: `user@realm!tokenid` (e.g., `ansible@pve!controller`)

### Module not found

- Verify collections installed: `ansible-galaxy collection list | grep proxmox`
- Re-run `ansible-playbook bootstrap.yml` to reinstall collections after updating dependency files

### Python import errors

- Verify Python packages: `python3 -m pip list | grep -E "proxmoxer|requests"`
- Re-run `ansible-playbook bootstrap.yml` to rebuild the controller virtual environment if packages drift

## Migration from Legacy Implementation

The previous implementation (running Ansible on the Proxmox host with shell commands) has been archived to `archive/ansible/`. It is **deprecated and unsupported**.

The new API-driven approach provides:
- No shell access required to Proxmox host
- Better security (API tokens vs root access)
- Remote execution from any controller
- Consistent with Proxmox best practices

## Contributing

When adding new playbooks or roles:
- Use `community.proxmox` modules only (no shell commands)
- Target the `proxmox_api` inventory group
- Set `connection: local` and `gather_facts: false`
- Pass authentication via the `_proxmox_auth` variable pattern
- Document in playbook comments

## Support

- Issues: https://github.com/faviann/ServerManagementScripts/issues
- Documentation: See [docs/](docs/) directory

## License

Part of ServerManagementScripts repository.
