# Agent Operating Instructions

**Project Type**: Ansible infrastructure-as-code (IaC)  
**Purpose**: Automate Proxmox LXC provisioning, configuration, and service deployments  
**Architecture**: Portable workstation-based (runs from any Linux workstation with network access to Proxmox)

## Non-negotiables
- Run Ansible from your Linux workstation (portable setup, no dedicated controller needed).
- Ensure you have network access to Proxmox API (typically `proxmox.internal.faviann.com:8006`).
- Never request, paste, or print secrets (API token secret, vault passphrase, private keys).
- Always run `git pull` before executing ansible commands.

## Workstation Requirements
- **OS**: Linux (Debian/Ubuntu recommended)
- **Python**: 3.10+ with venv support
- **Network**: Access to Proxmox API and managed LXC containers
- **Packages**: `python3-venv`, `python3-pip`, `sshpass` (installed via setup.sh)

## Standard Paths

| Item | Location |
|------|----------|
| Repo root | Project directory (portable - any location) |
| SSH key (private) | `.ansible/ssh/proxmox_lxc` (project-relative, gitignored) |
| SSH key (public) | `.ansible/ssh/proxmox_lxc.pub` (project-relative, gitignored) |
| Vault password | `.ansible/vault-pass.txt` (project-relative, gitignored) |
| Vaulted secrets | `inventory/group_vars/all/vault.yml` (encrypted) |
| Fact cache | `.ansible/cache/` (project-relative, gitignored) |
| Venv | `.ansible/venv/` (project-relative, gitignored) |

## Inventory Structure

| Type | Groups | Purpose |
|------|--------|---------|
| **Tiers** | `tier_tiny`, `tier_small`, `tier_medium`, `tier_large` | Resource allocation (mutually exclusive) |
| **Capabilities** | `cap_docker`, `cap_gpu`, `cap_wireguard`, `cap_service_agents` | Feature flags (compositional) |
| **Special** | `proxmox_api`, `lxcs` | API controller + all LXC targets |

**Naming**: LXCs resolve as `{{ inventory_hostname }}.faviann.vms`

## Variable Precedence

Variables merge in this order (later overrides earlier):
1. Role defaults (`roles/*/defaults/main.yml`)
2. Global vars (`inventory/group_vars/all/*.yml`)
3. Tier vars (`inventory/group_vars/tier_*/*.yml`)
4. Capability vars (`inventory/group_vars/cap_*/*.yml`)
5. Host vars (`inventory/host_vars/*.yml`)

## Playbook Tags

| Tag | Runs | Use Case |
|-----|------|----------|
| `validation` | API connectivity checks | Pre-flight validation |
| `provision` | LXC creation via Proxmox API | Initial deployment |
| `host_config` | Proxmox host-side config (pct) | Feature flags, bind mounts |
| `configure` | In-LXC setup tasks | Docker, system updates, services |

## Common Commands

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `./setup.sh` | Complete initial setup | First-time workstation setup |
| `./configure-vault.sh` | Update Proxmox credentials | Change API tokens or credentials |
| `ansible-playbook bootstrap.yml` | Setup controller environment | After clean install or venv issues |
| `ansible-playbook playbooks/validate-credentials.yml` | Test API credentials | Verify credentials work |
| `ansible-playbook site.yml` | Full orchestration run | Deploy/update all LXCs |
| `ansible-playbook site.yml --tags validation` | API connectivity only | Pre-flight check |
| `ansible-playbook site.yml --limit gatekeeper` | Target specific host(s) | Test changes on one LXC |
| `ansible-playbook site.yml --check` | Dry run (no changes) | Preview what would change |
| `ansible-playbook site.yml -vvv` | Verbose debug output | Troubleshoot failures |
| `ansible -i inventory/hosts.yml lxcs -m ping` | Test connectivity | Verify SSH access |
| `ansible-inventory -i inventory/hosts.yml --list` | Show computed variables | Debug variable precedence |
| `ansible-playbook playbooks/add-ssh-keys-to-lxcs.yml` | Manually add SSH keys to LXCs | Only if site.yml SSH step fails |

**First-time setup**: See [docs/remote-controller-setup.md](docs/remote-controller-setup.md) for complete venv installation instructions.

### Venv guard (idempotent one-liner for agents)

Use this at the start of any Ansible session to automatically activate or create the venv. It's **safe to run repeatedly** and prevents "ansible: command not found" errors:

```bash
# Activate project-local venv (portable setup)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$PWD}")" && pwd)"
if [ -x "$PROJECT_ROOT/.ansible/venv/bin/ansible" ]; then
	. "$PROJECT_ROOT/.ansible/venv/bin/activate"
else
	cd "$PROJECT_ROOT"
	python3 -m venv ".ansible/venv"
	. ".ansible/venv/bin/activate"
	python3 -m pip install --upgrade pip
	pip install ansible
	pip install -r "requirements/pip.txt"
fi
ansible --version
```

## Troubleshooting Quick Hits

- **"Permission denied (publickey)" on LXCs**: SSH key injection runs automatically in site.yml. If it fails, check `.ansible/ssh/proxmox_lxc.pub` exists and run `ansible-playbook playbooks/add-ssh-keys-to-lxcs.yml` manually
- **Venv missing**: Run `ansible-playbook bootstrap.yml` from project root
- **Permission denied (vault)**: Check `.ansible/vault-pass.txt` exists in project directory
- **SSH fails after automatic key addition**: Verify controller pubkey (`.ansible/ssh/proxmox_lxc.pub`) in target LXC `~/.ssh/authorized_keys` via `pct exec <vmid> -- cat /root/.ssh/authorized_keys`
- **API 403 (restricted features)**: Use `pct` on Proxmox host (see [docs/proxmox-host-ssh-automation.md](docs/proxmox-host-ssh-automation.md))
- **Variable not applied**: Check precedence with `ansible-inventory -i inventory/hosts.yml --list`
- **Stale facts**: Clear cache at `.ansible/cache/`

## Security rules
- Do not commit or paste: `.ansible/vault-pass.txt`, any private key (`.ansible/ssh/proxmox_lxc`), or token secrets (keep them in encrypted `vault.yml` only).
- All secrets are gitignored and must be generated locally via `bootstrap.yml`.
- Use placeholders like `<REPLACE_ME>` in docs or examples that mention secrets.

## Role Design Guidelines (IaC)

Keep roles small, composable, and configurable.

- One role = one concern; split config, deploy, firewall, certs, etc.
- Prefer extension via variables/defaults over task edits.
- Keep variable names consistent across interchangeable roles.
- Avoid hardcoded hostnames/paths/creds; inject via vars.
- Declare dependencies in `meta/main.yml`; document required vars.
- Ensure idempotency; use `assert` to fail fast on missing inputs.

## Related Documentation

- Full reference: [docs/reference/agent-control-node-reference.md](docs/reference/agent-control-node-reference.md)
- Inventory guide: [docs/inventory-structure-guide.md](docs/inventory-structure-guide.md)
- SSH automation: [docs/proxmox-host-ssh-automation.md](docs/proxmox-host-ssh-automation.md)
- Initial setup: [docs/remote-controller-setup.md](docs/remote-controller-setup.md)
