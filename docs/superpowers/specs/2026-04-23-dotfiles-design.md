# Dotfiles & Workstation Repo Design

**Date:** 2026-04-23
**Status:** Approved

## Summary

A single private GitHub repo (`faviann/workstation`) serves as both the dotfiles repo and the personal workstation bootstrap repo. It uses [chezmoi](https://chezmoi.io) for dotfile management and Bitwarden CLI for secret injection. Secrets never touch the repo.

## Machines in Scope

| Machine | OS | Shell | Notes |
|---|---|---|---|
| Laptop | Ubuntu/Debian | fish | Primary personal machine |
| WSL2 (PC Workstation) | Ubuntu (WSL2) | fish | Windows 10 host, Linux-side only |
| LXC Workstation (`workstation`) | Ubuntu/Debian | bash | Ansible-managed baseline; chezmoi handles personal layer |

## Repo Structure

```
workstation/                         # repo root = chezmoi source dir
├── .chezmoi.toml.tmpl               # chezmoi config + machine type detection
├── .chezmoiignore                   # skip fish config on LXC
├── dot_gitconfig.tmpl               # git config with SSH signing + Bitwarden secrets
├── dot_ssh/
│   ├── config                       # SSH host aliases (no private keys)
│   └── allowed_signers              # local SSH signing verification
├── dot_config/
│   ├── fish/
│   │   ├── config.fish.tmpl         # fish config + secret env vars
│   │   └── functions/
│   │       └── fish_greeting.fish   # bootstrap reminder (BW_SESSION + chezmoi state)
│   └── claude/
│       └── settings.json            # Claude Code config (no secrets)
├── dot_bashrc.tmpl                  # LXC bash config + secret env vars
├── .chezmoiscripts/
│   └── run_once_install-packages.sh # one-time package installs per machine type
├── scripts/
│   └── sessions                     # tmux session manager
├── packages/
│   ├── fish-machines.txt            # apt packages for laptop + WSL2
│   └── lxc.txt                      # apt packages for LXC
└── BOOTSTRAP.md                     # cheat sheet — commands for new machine setup
```

## Machine Detection

`.chezmoi.toml.tmpl` detects machine type by hostname. The LXC hostname `workstation` is a **contract with the ServerManagementScripts Ansible repo** — changing it there requires updating this file.

```toml
{{- $is_lxc := false -}}
{{- if eq .chezmoi.hostname "workstation" -}}
{{-   $is_lxc = true -}}
{{- end -}}

[data]
  is_lxc = {{ $is_lxc }}
```

`.chezmoiignore` skips fish config on the LXC:

```
{{- if .is_lxc }}
dot_config/fish
{{- end }}
```

## Secret Management

All secrets are stored as Bitwarden **Secure Notes**. Item names use a `dotfiles/` prefix as a naming convention (e.g. `dotfiles/anthropic-api-key`) — Bitwarden CLI searches by item name, so the prefix namespaces them without requiring a specific folder. Optionally organize them into a `dotfiles` folder in the Bitwarden UI for tidiness. chezmoi fetches them at apply time via the active `BW_SESSION` env var. Nothing is cached to disk.

| Bitwarden item | Env var injected | Shells |
|---|---|---|
| `dotfiles/anthropic-api-key` | `ANTHROPIC_API_KEY` | fish + bash |
| `dotfiles/openai-api-key` | `OPENAI_API_KEY` | fish + bash |
| `dotfiles/copilot-token` | per tool docs | fish + bash |
| `dotfiles/gh-token` | `GH_TOKEN` | fish + bash |

Template pattern (fish):
```
set -gx ANTHROPIC_API_KEY {{ (bitwarden "notes" "dotfiles/anthropic-api-key") }}
```

Template pattern (bash):
```
export ANTHROPIC_API_KEY={{ (bitwarden "notes" "dotfiles/anthropic-api-key") }}
```

## SSH Keys

One SSH key generated fresh per machine. Private keys are never stored in Bitwarden or the repo.

chezmoi manages:
- `~/.ssh/config` — host aliases and options (safe to commit, no secrets)
- `~/.ssh/allowed_signers` — own public key for local commit verification

Each machine's public key is added manually to GitHub (Settings → SSH keys → signing key).

## SSH Commit Signing

Git uses the per-machine SSH key for commit signing — no GPG key needed.

`dot_gitconfig.tmpl` includes:
```ini
[user]
  name = Fav
  email = faviann@gmail.com
  signingkey = ~/.ssh/id_ed25519.pub

[commit]
  gpgsign = true

[gpg]
  format = ssh

[gpg "ssh"]
  allowedSignersFile = ~/.ssh/allowed_signers
```

## Bootstrap Flow

On a fresh machine:

```bash
# 1. Install chezmoi and bitwarden-cli
# 2. Log in to Bitwarden
bw login

# 3. Unlock vault (required before chezmoi apply)
export BW_SESSION=$(bw unlock --raw)

# 4. Init and apply dotfiles
chezmoi init --apply git@github.com:faviann/workstation.git
```

Day-to-day (pull repo changes + re-apply):
```bash
export BW_SESSION=$(bw unlock --raw)
chezmoi update
```

Full cheat sheet available in `BOOTSTRAP.md` in the repo root.

## Login Reminder (fish greeting)

`fish_greeting.fish` checks on every login:

1. Is `BW_SESSION` set and valid? → if not, prints: `Bitwarden locked. Run: export BW_SESSION=$(bw unlock --raw)`
2. Is chezmoi up to date with the remote? → if not, prints: `Dotfiles out of date. Run: chezmoi update`

Silent when everything is fine.

## Relationship to ServerManagementScripts

The Ansible repo provisions the LXC baseline (packages, user `faviann`, Docker). The workstation repo is applied on top as `faviann` to add the personal layer.

**Hostname contract:** The LXC hostname `workstation` is hardcoded in `.chezmoi.toml.tmpl` for machine detection. See `docs/workstation-post-provisioning-handoff.md` for the full handoff sequence.

## Out of Scope

- Windows-side config (Windows Terminal, PowerShell) — Linux/WSL2 only
- SSH private key management — generated fresh per machine, never in repo or Bitwarden
- Ansible roles or playbook logic — owned by ServerManagementScripts
