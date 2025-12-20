# Agent Operating Instructions (Controller LXC)

Operate this repository **only** from the Proxmox LXC control node. Reference: `docs/reference/agent-control-node-reference.md`.

## Non-negotiables
- SSH into the controller LXC and run Ansible there (not from your dev machine).
- Connect to the controller as `root@ansible.faviann.vms` over SSH (VS Code Remote SSH or plain shell).
- Never request, paste, or print secrets (API token secret, vault passphrase, private keys).

## Controller SSH Access
- Preferred user/host: `root@ansible.faviann.vms`.
- Host key policy: `StrictHostKeyChecking=accept-new` (first connect will trust and cache).
- Recommended `~/.ssh/config` entry on your client:

```
Host ansible.faviann.vms
		HostName ansible.faviann.vms
		User root
		IdentityFile ~/.ssh/proxmox_lxc
		IdentitiesOnly yes
		StrictHostKeyChecking accept-new
```

- Quick connection tests:
	- Plain SSH: `ssh ansible.faviann.vms 'hostname && whoami'`
	- VS Code Remote SSH: select target `ansible.faviann.vms` (uses the above config).

## Standard locations (controller)
- Repo workspace and `ansible.cfg`: repository root.
- SSH key: `~/.ssh/proxmox_lxc` (private) and `~/.ssh/proxmox_lxc.pub` (public).
- Vault password file (do not commit): `~/.ansible/vault-pass.txt`.
- Vaulted secrets file (encrypted): `inventory/group_vars/all/vault.yml` (template: `.example`).

## Host key behavior
- Ansible disables strict host key checking (`host_key_checking = False` in `ansible.cfg`).
- Proxmox SSH uses `StrictHostKeyChecking=accept-new` (see `inventory/group_vars/all/proxmox.yml`).

## Host naming convention
- LXCs resolve as `{{ inventory_hostname }}.faviann.vms` in the `lxcs` group.
- Proxmox API host is set in `inventory/group_vars/all/proxmox.yml` (`proxmox_api_host`).

## Quick reference (venv-first)
- **Pull latest changes**: `cd ~/ServerManagementScripts && git pull`
- Activate venv: `source ~/.ansible/venv/bin/activate`
- Bootstrap: `ansible-playbook bootstrap.yml`
- Validate: `ansible-playbook -i inventory/hosts.yml site.yml --tags validation`
- Full run: `ansible-playbook -i inventory/hosts.yml site.yml`

### Smoke test (controller)
- Activate venv: `source ~/.ansible/venv/bin/activate`
- Check Ansible present: `ansible --version`
- Ping a target from inventory: `ansible -i inventory/hosts.yml gatekeeper -m ping`

### First-time setup (venv-only)
Run these on the controller as `root`:

```
# Ensure system prerequisites exist
command -v python3 >/dev/null || (echo "python3 missing" && exit 1)
python3 -m venv ~/.ansible/venv
source ~/.ansible/venv/bin/activate
python3 -m pip install --upgrade pip
pip install ansible
pip install -r ~/ServerManagementScripts/requirements/pip.txt
```

Then initialize from the repo:

```
cd ~/ServerManagementScripts
source ~/.ansible/venv/bin/activate
ansible --version
ansible-playbook bootstrap.yml
```

### Venv guard (idempotent one-liner for agents)

Use this at the start of any Ansible session to automatically activate or create the venv. It's **safe to run repeatedly** and prevents "ansible: command not found" errors:

```bash
if [ -x "$HOME/.ansible/venv/bin/ansible" ]; then
	. "$HOME/.ansible/venv/bin/activate"
else
	python3 -m venv "$HOME/.ansible/venv"
	. "$HOME/.ansible/venv/bin/activate"
	python3 -m pip install --upgrade pip
	pip install ansible
	pip install -r "$HOME/ServerManagementScripts/requirements/pip.txt"
fi
ansible --version
```

**When to use**: Place this before running any `ansible` or `ansible-playbook` commands, especially in new shell sessions, remote SSH connections, or automation scripts.

**IMPORTANT**: Always run `git pull` before executing ansible commands to ensure you are using the latest playbooks and configurations:
```bash
cd ~/ServerManagementScripts
git pull
```

## Security rules
- Do not commit or paste: `~/.ansible/vault-pass.txt`, any private key (`~/.ssh/proxmox_lxc`), or token secrets (keep them in encrypted `vault.yml` only).
- Use placeholders like `<REPLACE_ME>` in docs or examples that mention secrets.

## Role Design Guidelines (IaC)

Keep roles small, composable, and configurable.

- One role = one concern; split config, deploy, firewall, certs, etc.
- Prefer extension via variables/defaults over task edits.
- Keep variable names consistent across interchangeable roles.
- Avoid hardcoded hostnames/paths/creds; inject via vars.
- Declare dependencies in `meta/main.yml`; document required vars.
- Ensure idempotency; use `assert` to fail fast on missing inputs.
