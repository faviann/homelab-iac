# Remote Controller Setup and Usage (LXC-only)

Run these playbooks from the Ubuntu LTS LXC control node (unprivileged). Do not run them from the dev machine.

If you're using an IDE agent (Copilot/Codex), follow the repo contract in `AGENTS.md`.

## 1) Bootstrap the controller
```bash
ansible-playbook bootstrap.yml
```
This play creates the controller virtual environment under `~/.ansible/venv`, installs Python dependencies from `requirements/pip.txt`, fetches collections from `collections/requirements.yml`, and generates the SSH key material used by other plays. Re-run it whenever you change dependency files or upgrade Ansible components.

## 2) Configure Proxmox API credentials with Ansible Vault
```bash
cp inventory/group_vars/all/vault.yml.example inventory/group_vars/all/vault.yml
$EDITOR inventory/group_vars/all/vault.yml   # put your token secret
ansible-vault encrypt inventory/group_vars/all/vault.yml
```
Optional local vault password file (do **not** commit):
```bash
echo "your-strong-passphrase" > ~/.ansible/vault-pass.txt
chmod 600 ~/.ansible/vault-pass.txt
```

Set non-secret vars in `inventory/group_vars/all/proxmox.yml`:
- `proxmox_api_host`
- `proxmox_api_token_id`
- `proxmox_verify_ssl` (false by default for homelab self-signed certs)
- `proxmox_default_node`

## 3) Inventory
Edit `inventory/hosts.yml` as needed. The `proxmox_api` group is for API tasks (runs locally on the controller). Add your containers to `lxcs` for post-provision SSH configuration if you want to manage them after creation.

## 4) Validate connectivity
```bash
ansible-playbook -i inventory/hosts.yml site.yml --tags validation
```
The `validation` tag performs API checks using the same collections and virtual environment installed by bootstrap. The playbook includes a preflight assertion that fails fast if bootstrap prerequisites are missing.

## 5) Run provisioning or full orchestration
```bash
ansible-playbook -i inventory/hosts.yml site.yml
```
Apply tags such as `--tags provision`, `--tags host_prep`, or `--tags configure` to target specific phases. Example, fully provision and configure LXCs in one run by omitting `--tags`.

## TLS verification (TODO/future hardening)
- Current default: `proxmox_verify_ssl: false` for self-signed certs.
- Future steps:
  - Install a trusted certificate on Proxmox or distribute a CA bundle.
  - Set `proxmox_verify_ssl: true` and configure CA path if needed.

## Notes
- API tokens are preferred. Create a least-privilege token with only the permissions required for LXC lifecycle on relevant nodes.
- If module names differ in your installed `community.proxmox`, use:
  - `ansible-doc -l | grep proxmox`
  - `ansible-doc community.proxmox.proxmox_lxc`
  - `ansible-doc community.proxmox.proxmox_lxc_info`
