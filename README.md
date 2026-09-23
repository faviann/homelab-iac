# homelab-iac

Ansible automation for managing Proxmox LXC containers via API from a remote controller.

## Quick Start (New Workstation)

**Generic controller setup:**

```bash
git clone https://github.com/faviann/homelab-iac.git
cd homelab-iac
```

On the Ansible-managed `workstation` LXC, complete `workstation-setup` first.
That command applies the dotfiles Home Manager flake for Node/npm, `uv`, `gh`,
and other baseline tools, then repairs missing npm-managed agent CLIs. Use
`update-agent-tools` on the workstation when you want the latest Codex, Claude
Code, and Pi.dev CLIs. On any other controller, install `uv` yourself; this
repository runs it but never installs it.

`./setup.sh sync` optionally synchronizes the locked Python environment ahead
of time. It is not prerequisite sequencing: every command reconciles the
environment through `uv run --locked`, and `./run.sh`, `./inspect.sh`, and
`./recover.sh` install and verify the collections and roles they consume.
Nothing establishes controller identity either, so a new controller still needs
`~/.ansible/ssh/proxmox_lxc` put in place explicitly before any managed-host
operation.

**After setup, validate your credentials:**

```bash
./inspect.sh credentials
```

**Manual setup:** See [detailed instructions below](#first-time-setup).

## Commands

Six commands are the supported interface: `./run.sh`, `./inspect.sh`,
`./recover.sh`, `./vault.sh`, `./validate.sh`, and `./setup.sh`. Each answers
`--help` with its operations. [docs/command-policy.md](docs/command-policy.md)
records their grammar, exit statuses, and lock classes, and the few raw
commands that remain permitted.

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

### System Requirements

- **Operating System**: Debian/Ubuntu Linux (tested on Ubuntu 24.04 LTS)
- **Python**: 3.12+
- **Network**: Must reach Proxmox API (HTTPS port 8006)
- **Proxmox**: API token with LXC management permissions

### Required System Packages (Install First)

Before running any repository command, install these packages:

```bash
sudo apt update
sudo apt install -y python3 curl sshpass
```

**Package purposes:**
- `python3` - Base Python runtime for `uv` and Ansible tooling
- `curl` - Required to install `uv` when it is missing
- `sshpass` - Required for initial SSH key distribution to Proxmox host

### Ansible Dependencies

Python dependencies are declared in `pyproject.toml` and locked in `uv.lock`.
Commands reconcile the environment through `uv run --locked`; `./setup.sh sync` does it ahead of time.

Collections are pinned in `collections/requirements.yml` and external roles in
`requirements/roles.yml`. Each live command reconciles the subset it consumes
before Ansible starts, so `./run.sh provision` never waits on the Docker role
and `./inspect.sh credentials` never waits on a collection at all. That holds
because `scripts/live_dependencies.py` records what each playbook reaches; it
does not infer new consumption. When a live playbook begins consuming a
collection or external role, update its `LIVE_OPERATIONS` row in the same
change. An existing installation can otherwise mask a stale row.

Reconciliation installs into the repository-owned `collections/` and
`.ansible/roles/` paths configured in `ansible.cfg`. SSH-consuming operations
also create the repository's configured `.ansible/cp/` directory before
Ansible starts. They verify the controller SSH identity and never create it:
when `~/.ansible/ssh/proxmox_lxc` is missing, or does not pair with its `.pub`,
the operation fails before any live effect and names the condition.

IMPORTANT: Some LXC operations (notably changing LXC "feature" flags such as `nesting=1` or `keyctl=1`) require privileged API access and are only permitted when performed by the local Proxmox root account (`root@pam`). If your automation will set or change LXC feature flags, create and use an API token for `root@pam` (see "Creating API Tokens in Proxmox" below). If you prefer not to use a `root@pam` token, avoid providing `features` in your LXC specs and configure those flags manually on the Proxmox host.

**Note**: This repository handles restricted feature flags (like `keyctl=1`) by applying them via `pct` commands directly on the Proxmox host after API-based provisioning. Ordinary lifecycle runs require the selected controller identity to be trusted already; they never prompt for a password or enroll it implicitly.

### Proxmox Environment Defaults

These defaults are configured for the target homelab:

- **API host**: `proxmox.lan`
- **Node name**: `proxmox`
- **Network bridge**: `vmbr1`
- **Default template**: `local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst`

Adjust or override them in `inventory/group_vars/all/proxmox.yml`, host variables, or playbook vars as needed for your environment.

## First-Time Setup

### Manual Setup

On the managed `workstation` LXC, run `workstation-setup` first so Home Manager provides `uv` and the other base tools. On any other controller:

1. **Install system prerequisites:**

   ```bash
   sudo apt update
   sudo apt install -y python3 curl sshpass
   ```

2. **Provision the vault password file:**

   ```bash
   bw login                                  # first time only
   export BW_SESSION=$(bw unlock --raw)
   chezmoi init --apply https://github.com/faviann/dotfiles.git
   ```

   This writes `~/.ansible/vault-pass` before any command needs the vault.

3. **Install uv and sync dependencies:**

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   export PATH="$HOME/.local/bin:$PATH"
   ./setup.sh sync
   ```

4. **Establish the controller SSH identity:**

   Managed-host operations authenticate with `~/.ansible/ssh/proxmox_lxc`.
   Nothing in this repository creates it. Live commands verify it and fail
   before any live effect when it is missing, because which of the two cases
   below you are in is yours to decide.

   On a rebuilt controller, restore the previously trusted private key and its
   `.pub` from your own backup. Minting a new identity loses the trust the
   fleet already grants, and managed hosts will still reject it.

   On a genuinely first controller, create one:

   ```bash
   mkdir -p -m 700 ~/.ansible/ssh
   ssh-keygen -t ed25519 -N '' -f ~/.ansible/ssh/proxmox_lxc -C "ansible-control@$(hostname)"
   ```

   Neither restoring nor creating enrolls trust on managed infrastructure, and
   no ordinary run enrolls it for you. Each target is a separate explicit
   transition: `./recover.sh proxmox-host-ssh` enrolls the Proxmox host,
   prompting once for its root password, and `./recover.sh ssh-keys` enrolls
   existing LXCs.

   When you run the lifecycle from the `workstation` LXC itself, it excludes that host by
   default. To manage it intentionally, run:

   ```bash
   ./run.sh --include-controller
   ```

5. **Configure Proxmox API credentials:**

   Run the guided vault configuration:

   ```bash
   ./vault.sh configure
   ```

   **To generate a Proxmox API token:**
   - Log into Proxmox web interface
   - Navigate to: **Datacenter → Permissions → API Tokens**
   - Click "Add" and configure:
     - **User**: Select your user (e.g., `root@pam`)
     - **Token ID**: Name it (e.g., `ansible-automation`)
     - **Privilege Separation**: Uncheck (to inherit user permissions)
   - Copy the token secret (UUID) - shown only once!

6. **Validate credentials:**

   ```bash
   ./inspect.sh credentials
   ```

### After Setup

Test connectivity:

```bash
./inspect.sh credentials
./inspect.sh connectivity
```

## Usage

### Running the Lifecycle

```bash
./run.sh                                  # full lifecycle for every LXC
./run.sh provision                        # create or update LXCs only
./run.sh configure                        # in-container configuration only
./run.sh --limit portal                   # one host (Ansible limit grammar)
./run.sh --limit portal --stack traefik3  # one stack on one host
./run.sh --check                          # dry run
./inspect.sh plan                         # report planning problems without running anything
```

A full run verifies control node prerequisites, **verifies that the Proxmox
host already trusts the controller identity** (stopping before any effect when
it does not), validates API connectivity, provisions LXC containers, applies
host-side configuration (including restricted feature flags via `pct`), and
configures each container.

A lifecycle run never prompts for the Proxmox root password. Enroll trust once
with `./recover.sh proxmox-host-ssh`.

Live commands share one machine-local lock across every worktree on the
controller. A mutating run takes it exclusively; `--check` and `./inspect.sh`
take it shared. A command that cannot take the lock exits 75 at once and names
the holder. The lock does not coordinate two control nodes.

## Repository Structure

```
.
|-- ansible.cfg
|-- collections/
|   `-- requirements.yml               # Ansible collection dependencies
|-- docs/
|   |-- command-policy.md
|   |-- inventory-structure-guide.md
|   `-- ssh-key-management.md
|-- inventory/
|   |-- hosts.yml                      # Static inventory file
|   |-- vault.yml                      # Encrypted secrets (loaded explicitly)
|   |-- vault.yml.example              # Template for vault
|   |-- group_vars/
|   |   `-- all/
|   |       `-- proxmox.yml            # Non-secret Proxmox configuration
|   `-- host_vars/                     # Host-specific variables
|       |-- auth.yml
|       |-- portal.yml
|       |-- servarr.yml
|       |-- seedbox.yml
|       `-- jellyfin.yml
|-- playbooks/                         # Playbooks and roles behind the commands
|-- pyproject.toml                     # Python dependency declarations for uv
|-- uv.lock                            # Locked Python dependency resolution
|-- site.yml                           # Top-level orchestration playbook
`-- .ansible-lint                      # Lint gate config: production profile; exemption rationale in comments
```

## Documentation

- **docs/command-policy.md** - Command grammar, lock classes, and permitted raw commands
- **docs/inventory-structure-guide.md** - Inventory design and best practices
- **docs/ssh-key-management.md** - Adding SSH keys to existing containers
- **stacks/README.md** - Docker Compose conventions and Traefik label contract
- **AGENTS.md** - Agent operating instructions

## Configuration

### Non-Secret Variables

Edit `inventory/group_vars/all/proxmox.yml` to configure your environment:

```yaml
proxmox_api_host: "proxmox.lan"           # Proxmox hostname or IP
proxmox_api_port: 8006                     # API port (default 8006)
proxmox_api_token_id: "ansible@pve!controller"  # API token ID
proxmox_default_node: "proxmox"           # Default node for operations
proxmox_verify_ssl: false                  # TLS verification (see below)
```

### Secret Variables (Ansible Vault)

The encrypted vault lives outside `group_vars` so SSH connectivity and recovery
do not load it. API-consuming workflows load it explicitly and validate their
API credentials; configuration checks only the selected service inputs.

`./vault.sh configure` creates the encrypted vault, or updates its Proxmox
credentials, through a TTY prompt. `./vault.sh edit` opens the whole vault in
your editor, and `./vault.sh check` verifies it without printing any value.
Every top-level key starts with `vault_`, as in `inventory/vault.yml.example`.

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

Check whether the selected controller identity is already trusted by running the
intended lifecycle or inspection operation. If it is not, that operation stops
before its effects and points to the explicit enrollment transition:

```bash
./recover.sh proxmox-host-ssh
```

The enrollment command identifies the configured Proxmox target and the selected
public-key fingerprint before requesting the Proxmox host password. It then runs
`ssh-copy-id` for that one public key, which appends it to the configured SSH
user's `~/.ssh/authorized_keys`, and confirms that the private key can log in.
Ordinary lifecycle and inspection operations never request that password or
modify `authorized_keys`.

After initial setup, all subsequent playbook runs will use passwordless SSH authentication.

## Diagnostics

```bash
./inspect.sh credentials     # Proxmox API credential and permission ladder
./inspect.sh connectivity    # SSH reachability of the LXCs; non-zero when one is unreachable
./inspect.sh containers      # every LXC on the Proxmox node
./inspect.sh vars portal     # merged variables, vault-derived values masked
```

## TLS Certificate Verification

**Current status**: TLS verification is **disabled** by default (`proxmox_verify_ssl: false`) to support self-signed certificates commonly used in homelabs.

**TODO/Future hardening**:
1. Install a trusted certificate on Proxmox or distribute your CA bundle to the controller
2. Set `proxmox_verify_ssl: true` in `inventory/group_vars/all/proxmox.yml`
3. Configure CA path if needed via `api_ca_path` parameter

## Troubleshooting

### Cannot reach Proxmox API

- Verify controller can reach Proxmox host: `curl -k https://proxmox.lan:8006`
- Check firewall rules allow HTTPS (port 8006)
- Verify VPN/network connectivity

### Authentication fails

- Run `./inspect.sh credentials` to see which step of the credential ladder fails
- Run `./vault.sh check` to verify the vault without printing its values; `./vault.sh configure` replaces the token secret
- Check token permissions in Proxmox web UI
- Ensure token ID format: `user@realm!tokenid` (e.g., `ansible@pve!controller`)

### Module not found

- Live commands reconcile only dependencies listed in their `LIVE_OPERATIONS`
  row. For a missing module, verify that its collection is both exactly pinned
  and listed for the playbook; an existing installation can mask a stale row.

### Python import errors

- Run `./setup.sh sync` to resynchronize the locked Python environment

## Contributing

Run the complete non-live verification suite before handoff:

```bash
./validate.sh
```

This runs the production Ansible lint gate, full credential-free lifecycle regressions, and the full Python test suite. It does not load live inventory or acquire the lifecycle lock. Route all live operations, including check-mode runs, through `./run.sh`, `./inspect.sh`, or `./recover.sh`. In pull request descriptions, report `./validate.sh` as the verification command rather than listing its internal commands.

`./validate.sh` needs `/usr/sbin/sshd` (Debian package `openssh-server`) on the machine that runs it. The Proxmox trust regression starts an unprivileged `sshd` on `127.0.0.1` so the real `ssh` client decides trust; it installs nothing and fails with that path in its message when `sshd` is absent. The `workstation` guest has it because the `debian-13-standard` template it is built from ships `openssh-server`. The system `sshd` service does not need to be running.

When adding new playbooks or roles:
- Use `community.proxmox` modules only (no shell commands)
- Target the `proxmox_api` inventory group
- Set `connection: local` and `gather_facts: false`
- Pass authentication via the `_proxmox_auth` variable pattern
- Document in playbook comments

## Support

- Issues: https://github.com/faviann/homelab-iac/issues
- Documentation: See [docs/](docs/) directory

## License

Part of homelab-iac repository.
