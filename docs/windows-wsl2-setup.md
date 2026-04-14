# Windows 10 + WSL2 Setup

Use WSL2 as the Linux control node for this project. Do not run Ansible from PowerShell or `cmd.exe`.

You do not need a devcontainer for the normal workflow. The repository already bootstraps its own project-local virtual environment, SSH keys, vault password file, and VS Code terminal settings.

## Recommended Workflow

- Install Ubuntu under WSL2.
- Clone this repository inside the WSL filesystem, for example `~/src/ServerManagementScripts`.
- Open the repo in VS Code using the `Remote - WSL` extension.
- Run Codex CLI from a WSL shell in the repo root.
- Keep secrets, SSH keys, and the Python virtual environment inside WSL.

This is the intended shape of the project:

- `.ansible/venv/` holds the project-local Python environment.
- `.ansible/ssh/` holds the SSH keypair used for Proxmox and LXC access.
- `.ansible/vault-pass.txt` holds the local vault password file.
- `inventory/group_vars/all/vault.yml` remains encrypted at rest.

## Why Not a Devcontainer

A devcontainer is optional, not required.

For this repository, a devcontainer adds another layer around:

- SSH key access
- local secret files
- `direnv` shell activation
- filesystem performance

without providing much value, because the actual control node is already just a normal Linux environment with a project-local venv.

Use a devcontainer only if you have another constraint that specifically requires one.

## Install WSL2

Install WSL2 and an Ubuntu distribution on Windows 10, then update the distro:

```bash
sudo apt update
sudo apt upgrade -y
```

If you have not configured Git in WSL before, set it up there rather than in Windows:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

## Clone in the Linux Filesystem

Clone the repository under your Linux home directory, not under `/mnt/c`.

Good:

```bash
mkdir -p ~/src
cd ~/src
git clone <REPO_URL>
cd ServerManagementScripts
```

Avoid:

```bash
cd /mnt/c/Users/<you>/...
```

Keeping the repo in the WSL filesystem avoids slow file operations, odd permission behavior, and worse tooling performance.

## Bootstrap the Project

Run the normal workstation setup inside WSL:

```bash
./setup.sh
```

`setup.sh` handles:

- installing `python3`, `python3-venv`, `python3-pip`, `sshpass`, and `direnv`
- creating `.ansible/venv`
- installing Ansible
- running `ansible-playbook bootstrap.yml`
- generating SSH keys under `.ansible/ssh/`
- configuring the encrypted vault workflow
- writing minimal VS Code terminal settings for login-shell behavior

After setup, reload your shell if `direnv` was newly installed, or start a fresh WSL terminal.

## VS Code

Install these Windows-side VS Code extensions:

- `Remote - WSL`
- `Ansible`
- `YAML`
- `EditorConfig`

Then open the project from WSL:

```bash
code .
```

or use the VS Code command palette and choose `WSL: Open Folder in WSL`.

Important:

- Open the folder in WSL, not via a Windows path.
- Use the integrated terminal inside the WSL window.
- Let `direnv` activate the repo environment automatically.

The repository already uses:

- [`.envrc`](../.envrc) to activate `.ansible/venv`
- [`.vscode/settings.json`](../.vscode/settings.json) to make the integrated terminal start as a login shell

## Codex CLI

Run Codex CLI directly inside WSL from the repository root.

That gives it the same Linux filesystem, shell, SSH keys, and virtual environment as the rest of the project.

## Connectivity Notes

WSL2 must be able to reach:

- the Proxmox API endpoint on port `8006`
- the Proxmox host over SSH
- any VPN or internal DNS services your lab requires

If your homelab is only reachable over VPN, connect the VPN in the place that actually gives WSL network access in your setup.

## Validation

After setup, validate from WSL:

```bash
ansible-playbook site.yml --tags validation
```

Useful checks:

```bash
ansible-inventory -i inventory/hosts.yml --host <name> --yaml
ansible -i inventory/hosts.yml lxcs -m ping
```

## Common Pitfalls

- Running the repo from `/mnt/c/...` instead of the Linux filesystem
- Running Ansible from Windows shells instead of WSL
- Opening the folder in normal Windows VS Code instead of a Remote WSL window
- Expecting a devcontainer to fix network, VPN, or DNS reachability issues
- Copying secrets or SSH keys into Windows paths unnecessarily

## Summary

The efficient Windows 10 setup is:

1. WSL2 Ubuntu
2. repo cloned inside WSL
3. `./setup.sh` run inside WSL
4. VS Code via `Remote - WSL`
5. Codex CLI run directly in WSL

That keeps the environment aligned with the project's Linux workstation model and avoids an unnecessary container layer.
