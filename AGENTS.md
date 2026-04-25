# Agent Operating Instructions

**Project Type**: Ansible infrastructure-as-code (IaC)  
**Purpose**: Automate Proxmox LXC provisioning, configuration, and service deployments  
**Architecture**: Portable workstation-based (runs from any Linux workstation with network access to Proxmox)

## Project Philosophy

**Code is a liability, not an asset.** When two approaches exist, recommend the one with less code and fewer objects.

## Non-negotiables
- Never request, paste, or print secrets (API token secret, vault passphrase, private keys). Use placeholders like `<REPLACE_ME>` in docs or examples.
- The venv is on `PATH` automatically. If it doesn't exist yet, run `ansible-playbook bootstrap.yml` to create it.
- `ansible.cfg` expects the vault passphrase at `~/.ansible/vault-pass`.
- Lifecycle playbooks skip any host whose `inventory_hostname` matches the controller's hostname (`proxmox_skip_self: true` by default). To manage the control node intentionally: `ansible-playbook site.yml -e proxmox_skip_self=false --limit workstation` (`--limit` targets the host, `-e` disables the guard).

## Standard Paths

| Item | Location |
|------|----------|
| SSH key (private) | `.ansible/ssh/proxmox_lxc` (project-relative, gitignored) |
| SSH key (public) | `.ansible/ssh/proxmox_lxc.pub` (project-relative, gitignored) |
| Vault password | `~/.ansible/vault-pass` (home-dir, written by chezmoi from Bitwarden) |
| Vaulted secrets | `inventory/group_vars/all/vault.yml` (encrypted) |
| Fact cache | `.ansible/cache/` (project-relative, gitignored, 1h TTL) |
| Venv | `.ansible/venv/` (project-relative, gitignored) |
| External roles | `.ansible/roles/` (project-relative, gitignored, auto-installed) |

Secrets are only in encrypted `inventory/group_vars/all/vault.yml` — never commit plaintext credentials. The vault password file is machine-local and should be provisioned outside this repo.

## Inventory Structure

| Type | Groups | Purpose |
|------|--------|---------|
| **Tiers** | `tier_tiny`, `tier_small`, `tier_medium`, `tier_large` | Resource allocation (mutually exclusive) |
| **Capabilities** | `cap_docker`, `cap_gpu`, `cap_wireguard` | Sets feature flags: `docker_enabled`, `gpu_enabled`, etc. |
| **Special** | `proxmox_api`, `lxcs` | API controller + all LXC targets |

**Naming**: LXCs resolve as `{{ inventory_hostname }}.faviann.vms`

**Feature Flags**: Capability groups set boolean flags (`docker_enabled: true`) instead of checking group membership. Roles use `when: docker_enabled | default(false)`, never `'cap_docker' in group_names`.

→ [docs/inventory-structure-guide.md](docs/inventory-structure-guide.md) — read for variable precedence order, worked examples, and adding new hosts.

## Deployment Lifecycle

`site.yml` runs three phases in sequence: **validate** → **provision** (LXC create/update via Proxmox API) → **configure** (in-container: packages, Docker, stacks). Two-tier host config: `proxmox_lxc_provision` handles API-allowed settings; `proxmox_lxc_host_config` handles restricted features (`keyctl=1`, `nesting=1`) via `pct` on the Proxmox host.

Roles live in `playbooks/roles/{base,infrastructure,provisioning,config}/`.

## Docker Stacks

Stacks live in `stacks/<hostname>/<stack-name>/compose.yaml`. Auto-discovered and started with `docker compose up -d` — no registration needed.

→ [stacks/README.md](stacks/README.md) — read for stack contract, Traefik routing, secrets, and full conventions.

## Command Reference

| Command | Purpose |
|---------|---------|
| `ansible-playbook site.yml` | Full lifecycle — deploy/update all LXCs |
| `ansible-playbook site.yml -e proxmox_skip_self=false --limit workstation` | Intentionally include the control node when running from `workstation` |
| `ansible-playbook site.yml --limit <host>` | Target one host |
| `ansible-playbook site.yml --limit <host> -e stack_filter=<stack>` | Deploy one stack on a host (skips all others) |
| `ansible-playbook site.yml --check` | Dry run |
| `ansible-playbook bootstrap.yml` | Recreate venv + SSH keys after clean install |
| `./setup.sh` | Fresh workstation setup — extend here for new workstation config (editor, tooling, env) |
| `ssh -l root -i .ansible/ssh/proxmox_lxc <host>` | Direct SSH into an LXC |

**Timing**: `ansible-playbook` runs against live hosts typically take 5–10 minutes. Do not assume a hang — wait for completion before acting on the result.

Debug: `ansible-playbook site.yml -vvv` for verbose output, `ansible-inventory -i inventory/hosts.yml --host <name> --yaml` for merged vars, `ansible -i inventory/hosts.yml lxcs -m ping` for connectivity, delete `.ansible/cache/` for stale facts.

## Role Design Principles

- One role = one concern; use `meta/main.yml` for dependencies
- Use feature flags (`docker_enabled`) not group checks (`'cap_docker' in group_names`)
- Avoid hardcoded values; inject via vars. Ensure idempotency; use `assert` to fail fast

## Related Documentation

→ [docs/inventory-structure-guide.md](docs/inventory-structure-guide.md) — read when adding hosts or debugging variable precedence.
→ [stacks/README.md](stacks/README.md) — read when creating or modifying Docker stacks.
→ [setup.sh](setup.sh) — read when addressing workstation tooling, editor config, or environment setup for contributors.
