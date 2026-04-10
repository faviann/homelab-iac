# Agent Operating Instructions

**Project Type**: Ansible infrastructure-as-code (IaC)  
**Purpose**: Automate Proxmox LXC provisioning, configuration, and service deployments  
**Architecture**: Portable workstation-based (runs from any Linux workstation with network access to Proxmox)

## Project Philosophy

**Code is a liability, not an asset.** When two approaches exist, recommend the one with less code and fewer objects.

## Non-negotiables
- Never request, paste, or print secrets (API token secret, vault passphrase, private keys).
- Activate the venv before running any ansible command: `source .ansible/venv/bin/activate` (create with `ansible-playbook bootstrap.yml` if missing).

## Standard Paths

| Item | Location |
|------|----------|
| SSH key (private) | `.ansible/ssh/proxmox_lxc` (project-relative, gitignored) |
| SSH key (public) | `.ansible/ssh/proxmox_lxc.pub` (project-relative, gitignored) |
| Vault password | `.ansible/vault-pass.txt` (project-relative, gitignored) |
| Vaulted secrets | `inventory/group_vars/all/vault.yml` (encrypted) |
| Fact cache | `.ansible/cache/` (project-relative, gitignored, 1h TTL) |
| Venv | `.ansible/venv/` (project-relative, gitignored) |
| External roles | `.ansible/roles/` (project-relative, gitignored, auto-installed) |

Secrets are only in encrypted `inventory/group_vars/all/vault.yml` — never commit plaintext credentials.

## Inventory Structure

| Type | Groups | Purpose |
|------|--------|---------|
| **Tiers** | `tier_tiny`, `tier_small`, `tier_medium`, `tier_large` | Resource allocation (mutually exclusive) |
| **Capabilities** | `cap_docker`, `cap_gpu`, `cap_wireguard` | Sets feature flags: `docker_enabled`, `gpu_enabled`, etc. |
| **Special** | `proxmox_api`, `lxcs` | API controller + all LXC targets |

**Naming**: LXCs resolve as `{{ inventory_hostname }}.faviann.vms`

**Feature Flags**: Capability groups set boolean flags (`docker_enabled: true`) instead of checking group membership. Roles use `when: docker_enabled | default(false)`, never `'cap_docker' in group_names`.

## Variable Precedence

Variables merge in this order (later overrides earlier):
1. Role defaults (`playbooks/roles/*/defaults/main.yml`)
2. Global vars (`inventory/group_vars/all/*.yml`)
3. Tier vars (`inventory/group_vars/tier_*/*.yml`)
4. Capability vars (`inventory/group_vars/cap_*/*.yml`)
5. Host vars (`inventory/host_vars/*.yml`)

## Deployment Lifecycle

`site.yml` runs three phases in sequence: **validate** → **provision** (LXC create/update via Proxmox API) → **configure** (in-container: packages, Docker, stacks). Two-tier host config: `proxmox_lxc_provision` handles API-allowed settings; `proxmox_lxc_host_config` handles restricted features (`keyctl=1`, `nesting=1`) via `pct` on the Proxmox host.

Roles live in `playbooks/roles/{base,infrastructure,provisioning,config}/`.

## Docker Stacks

Stacks live in `stacks/<hostname>/<stack-name>/compose.yaml`. Files ending in `.j2` are Jinja2-templated with all inventory vars. Stacks are auto-discovered and started with `docker compose up -d` — no registration needed.

**Traefik routing**: Non-portal hosts use `traefik-kop` to replicate Docker labels to portal's Redis. Portal runs Traefik directly (`traefik_kop_enabled: false` in `host_vars/portal.yml`).

## Command Reference

| Command | Purpose |
|---------|---------|
| `ansible-playbook site.yml` | Full lifecycle — deploy/update all LXCs |
| `ansible-playbook site.yml --limit <host>` | Target one host |
| `ansible-playbook site.yml --check` | Dry run |
| `ansible-playbook site.yml -vvv` | Verbose debug |
| `ansible -i inventory/hosts.yml lxcs -m ping` | Test SSH connectivity |
| `ansible-inventory -i inventory/hosts.yml --host <name> --yaml` | Show merged vars (debug precedence) |
| `ansible-playbook bootstrap.yml` | Recreate venv + SSH keys after clean install |
| `./configure-vault.sh` | Update Proxmox credentials |

## Troubleshooting

- **`ansible: command not found`**: `source .ansible/venv/bin/activate`
- **API 403 (restricted features)**: Requires `root@pam` token — see [docs/proxmox-host-ssh-automation.md](docs/proxmox-host-ssh-automation.md)
- **Variable not applied**: `ansible-inventory -i inventory/hosts.yml --host <name> --yaml`
- **Stale facts**: Delete `.ansible/cache/`

## Role Design Principles

- One role = one concern; use `meta/main.yml` for dependencies
- Use feature flags (`docker_enabled`) not group checks (`'cap_docker' in group_names`)
- Avoid hardcoded values; inject via vars. Ensure idempotency; use `assert` to fail fast

## Security Rules

- Do not commit or paste: `.ansible/vault-pass.txt`, any private key (`.ansible/ssh/proxmox_lxc`), or token secrets
- All secrets are gitignored and must be generated locally via `bootstrap.yml`
- Use placeholders like `<REPLACE_ME>` in docs or examples that mention secrets

## Related Documentation

- Inventory guide: [docs/inventory-structure-guide.md](docs/inventory-structure-guide.md)
- SSH automation: [docs/proxmox-host-ssh-automation.md](docs/proxmox-host-ssh-automation.md)
- Docker stacks conventions: [stacks/README.md](stacks/README.md)
