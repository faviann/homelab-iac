# What the dotfiles non-workstation profile does on the bootstrap node

Research for [#520](https://github.com/faviann/homelab-iac/issues/520), part of
the bootstrap-node map [#518](https://github.com/faviann/homelab-iac/issues/518).

**Question.** On a fresh Debian 13 LXC with hostname `bootstrap`, what does
`chezmoi init --apply` from the live dotfiles source do, and what must change
for it to deliver the bootstrap node's secrets?

**Method.** Source reading only. No template was rendered, `bw` was not called,
and no secret value was read.

## Sources

| Source | Revision |
|---|---|
| `faviann/dotfiles` (private), `main` | `dff6ca038c90b2546448f82cf1c5ea28f4e06865`. The live chezmoi source at `~/.local/share/chezmoi` is the same commit. |
| `faviann/homelab-iac`, `main` | `dcba325630fb2b3807eba1bda0d3127e4a6f32d6` |
| chezmoi reference | [target types](https://www.chezmoi.io/reference/target-types/), [application order](https://www.chezmoi.io/reference/application-order/), [source state attributes](https://www.chezmoi.io/reference/source-state-attributes/), [scripts guide](https://www.chezmoi.io/user-guide/use-scripts-to-perform-actions/), [global flags](https://www.chezmoi.io/reference/command-line-flags/global/) |
| Bitwarden CLI | [install options](https://bitwarden.com/help/cli/) |

In this document, `dotfiles:<path>` means the path in `faviann/dotfiles` at
`dff6ca0`, and `iac:<path>` means the path in `faviann/homelab-iac` at `dcba325`.

## Short answer

- **The secrets work as-is.** On any host whose name is not `workstation`,
  chezmoi renders `~/.ansible/vault-pass` (0600), `~/.ansible/ssh/proxmox_lxc`
  (0600), and `~/.ansible/ssh/proxmox_lxc.pub` (0644 under umask 022). The
  parent directories are 0700. The workstation uses the same templates in
  production today.
- **The bootstrap node gets more than it needs.** It also gets the personal
  GitHub SSH key (authentication and commit signing), unpinned remote code
  (the `herdr` installer), `fish`, and the workstation helper scripts.
- **A fresh LXC breaks the apply, but only after the secrets are written.**
  Without `sudo` or `git`, the apply exits non-zero. `.ansible/*` sorts before
  the scripts that fail, so the secrets are already on disk.
- **`sudo snap install bw` does not work on this fleet's LXCs.** They are
  unprivileged without FUSE. Use the native `bw` binary, the way
  `lxc_workstation_baseline` does.
- **`faviann/dotfiles` is still private.** The documented HTTPS
  `chezmoi init` therefore needs a GitHub credential on the node, even though
  ADR 0001 says the repository "is being made public".
- **The operator account is `root`.** On a tier_small LXC with no
  capabilities, root is the only account the fleet key can reach, so chezmoi
  and `./run.sh` run as root and render into `/root/.ansible/`.

## Profile selection

`dotfiles:.chezmoi.toml.tmpl` sets `is_workstation = true` only when
`.chezmoi.hostname` equals `workstation`. On `bootstrap` it is `false`.

`dotfiles:.chezmoiignore` ignores the following:

- On every host: the repository-only paths (docs, tests, scripts, flake files,
  `home/`, `packages/`).
- When `is_workstation` is true: `.config/fish/`.
- When `is_workstation` is false: `.config/github-tokens/`.

On `bootstrap`, the fish config is therefore managed and the work GitHub token
is not.

## What gets written on `bootstrap`

chezmoi applies targets in alphabetical order of their target name. Attributes
are stripped before sorting, and dot-files sort before letters. `run_after_`
scripts run after every target
([application order](https://www.chezmoi.io/reference/application-order/)).
All of the following are written before any `run_once_` script runs.

| Target | Source | Mode | Bitwarden item | Needed on bootstrap? |
|---|---|---|---|---|
| `~/.ansible/` | `private_dot_ansible/` | 0700 | none | yes |
| `~/.ansible/ssh/` | `private_dot_ansible/private_ssh/` | 0700 | none | yes |
| `~/.ansible/ssh/proxmox_lxc` | `private_dot_ansible/private_ssh/private_proxmox_lxc.tmpl` | 0600 | `dotfiles/proxmox-lxc-ssh-key` (Notes, trimmed, one trailing newline) | **yes** |
| `~/.ansible/ssh/proxmox_lxc.pub` | `private_dot_ansible/private_ssh/proxmox_lxc.pub.tmpl` | 0644 (umask 022) | `dotfiles/proxmox-lxc-ssh-key`, custom field `public_key` | **yes** |
| `~/.ansible/vault-pass` | `private_dot_ansible/private_vault-pass.tmpl` | 0600, not executable | `dotfiles/ansible-vault-pass` (Notes) | **yes** |
| `~/.bash_profile`, `~/.bashrc` | `dot_bash_profile.tmpl`, `dot_bashrc.tmpl` | 0644 | none | harmless: they add `~/.local/bin` and Nix paths to `PATH`, and Nix is absent |
| `~/.config/fish/config.fish`, `functions/fish_greeting.fish` | `dot_config/fish/` | 0644 | none | no |
| `~/.gitconfig` | `dot_gitconfig.tmpl` | 0644 | none on non-workstation hosts. The work-owner credential block is behind `if .is_workstation`. | no. It sets `commit.gpgsign = true` with the GitHub key and uses `gh auth git-credential` for `https://github.com`. A public fetch never asks for a credential, so `git fetch` of `faviann/homelab-iac` is unaffected. |
| `~/.local/bin/{dev-session,gh,github-token,update-agent-tools,workstation-update}` | `dot_local/bin/executable_*` | 0755 | none at render time | no. These are workstation tools. The `gh` wrapper fails if no real `gh` is installed. |
| `~/.npmrc` | `dot_npmrc` | 0644 | none | no |
| `~/.ssh/` | `private_dot_ssh/` | 0700 | none | n/a. The directory already exists with root's `authorized_keys`. |
| `~/.ssh/config` | `private_dot_ssh/config` | 0644 | none | no. It sets `Host * IdentityFile ~/.ssh/id_ed25519`. |
| `~/.ssh/id_ed25519` | `private_dot_ssh/private_id_ed25519.tmpl` | 0600 | `dotfiles/workstation-ssh-key` (Notes) | **no. This is the personal GitHub authentication and signing key.** |
| `~/.ssh/id_ed25519.pub`, `~/.ssh/allowed_signers` | `private_dot_ssh/id_ed25519.pub.tmpl`, `allowed_signers.tmpl` | 0644 | `dotfiles/workstation-ssh-key`, field `public_key` | no |

The modes follow from chezmoi's own rules. `private_` "remove[s] all group and
world permissions from the target file or directory", and files without
`executable_` are not executable
([source state attributes](https://www.chezmoi.io/reference/source-state-attributes/)).

`dotfiles:tests/ansible-controller-key.bats` covers part of this with
`is_workstation=false`. It asserts that `~/.ansible/ssh` is 700, that
`proxmox_lxc` is 600 and ends in exactly one newline, and that `.pub` comes
from the `public_key` field. No test covers the mode of `vault-pass`. The
`private_` attribute and the workstation's live file (0600) agree on it.

**Bitwarden items the non-workstation profile needs.** All three must exist,
and the vault must be unlocked (`BW_SESSION` exported), or the template fails.

1. `dotfiles/ansible-vault-pass`: Notes.
2. `dotfiles/proxmox-lxc-ssh-key`: Notes, plus custom field `public_key`.
3. `dotfiles/workstation-ssh-key`: Notes, plus custom field `public_key`. Only
   the unwanted GitHub key needs this item.

`dotfiles/github-token-work` is not read on non-workstation hosts.
`dotfiles/github-cli-token` is read only by the `workstation-setup` and
`github-token` helpers, never during apply.

## Scripts that fire when `is_workstation` is false

| Script | Phase | Fires on bootstrap? | What it does | Needs |
|---|---|---|---|---|
| `dotfiles:.chezmoiscripts/run_once_install-herdr.sh.tmpl` | during apply, after all dot-targets (`install-herdr.sh` sorts after `.*`) | **yes, on every host. It has no `is_workstation` guard.** | `curl -fsSL https://herdr.dev/install.sh` and runs it with `sh`, installing to `~/.local/bin`. The installer is unpinned and unverified. | `curl` |
| `dotfiles:.chezmoiscripts/run_once_install-packages.sh.tmpl` | during apply, after herdr | yes. The `fish` block is the only content when not workstation. | If `fish` is absent, runs `sudo apt update && sudo apt install -y fish`. | `sudo` (the script calls it even as root) |
| `dotfiles:.chezmoiscripts/run_after_github-known-hosts.sh.tmpl` | after | yes | Pins GitHub's Ed25519 host key into `~/.ssh/known_hosts`. | `ssh-keygen` (from openssh-client in the template) |
| `dotfiles:.chezmoiscripts/run_after_reconcile-agent-skills.sh.tmpl` | after | **no.** The whole body is inside `if .is_workstation`, so it renders empty, and chezmoi skips a script whose template "resolves to only whitespace or an empty string" ([scripts guide](https://www.chezmoi.io/user-guide/use-scripts-to-perform-actions/)). It clones `faviann/skillset`, not `faviann/skills`. | n/a |
| `dotfiles:.chezmoiscripts/run_after_switch-chezmoi-origin-to-ssh.sh.tmpl` | after | yes | Rewrites the chezmoi source `origin` from HTTPS to `git@github.com:faviann/dotfiles.git`. Later `chezmoi update` runs then authenticate with `~/.ssh/id_ed25519`. If the origin URL is empty or unrecognized, the script exits 1. | `git` on `PATH` |

There are no `run_before_` scripts. chezmoi stops at the first error unless
`--keep-going` is passed
([global flags](https://www.chezmoi.io/reference/command-line-flags/global/)).
A failed `run_once_` script runs again on the next apply
([target types](https://www.chezmoi.io/reference/target-types/)).

## Prerequisites the flow assumes

`dotfiles:BOOTSTRAP.md` steps 1–3 install chezmoi with
`sh -c "$(curl -fsLS get.chezmoi.io)" -- -b ~/.local/bin`, install `bw` with
`sudo snap install bw`, export `BW_SESSION=$(bw unlock --raw)`, and then run
`chezmoi init --apply https://github.com/faviann/dotfiles.git`.

Facts about the template and these LXCs:

- **What the template ships.** The workstation was built from the same
  `debian-13-standard_13.1-2` template (`iac:inventory/group_vars/all/proxmox.yml`).
  Its `/var/log/dpkg.log` shows `wget` installed at template build time. It
  shows `sudo`, `curl`, `git`, and `unzip` installed later by Ansible. The
  template therefore lacks `sudo`, `curl`, `git`, and `unzip`, and snapd is not
  installed.
- **What an ordinary configure run adds.** `iac:playbooks/roles/config/lxc_base_system/tasks/main.yml`
  installs `sudo`, `curl`, `ca-certificates`, and `gnupg` on every LXC. No role
  installs `git` on a host without `workstation_enabled`. On the workstation,
  `git` arrived only as a dependency of `docker-ce-rootless-extras`. `unzip` is
  likewise absent.
- **Snap.** LXCs are `unprivileged: true` with `features: [nesting=1]` and no
  FUSE (`iac:inventory/group_vars/all/proxmox.yml`). snapd in an unprivileged
  container needs FUSE and squashfuse to mount snap images
  ([Proxmox forum](https://forum.proxmox.com/threads/cant-install-snap-in-lxc-container.68708/),
  [linuxcontainers forum](https://discuss.linuxcontainers.org/t/snapd-inside-lxc/6223)).
  Proxmox staff also warn that FUSE in a container conflicts with snapshot
  backups. Bitwarden ships a dependency-free native Linux executable
  ([Bitwarden CLI](https://bitwarden.com/help/cli/)), and
  `iac:playbooks/roles/config/lxc_workstation_baseline/tasks/bitwarden_cli.yml`
  already installs that zip with a digest check.
- **chezmoi.** It is not packaged for Debian trixie
  (packages.debian.org reports "Package not available in this suite"). The
  `get.chezmoi.io` script is the install path. It needs `curl` or `wget`, and
  the template's `wget` is enough.
- **Repository access.** `faviann/dotfiles` is `PRIVATE` (`gh repo view`). An
  HTTPS `chezmoi init` therefore prompts for a GitHub credential, which
  contradicts BOOTSTRAP.md's premise that "a new machine does not need an SSH
  key". `dotfiles:docs/adr/0001-public-repo-accepted-exposure.md` accepts
  making the repository public, but the flip has not happened.
- **Out of scope.** Dotfiles does not deliver `uv`, which `./run.sh` needs as a
  machine prerequisite (`iac:scripts/lib/uv-prerequisite.sh`).

## Which user

- **Root is how the fleet gets in.** Ansible reaches every LXC as `root`
  (`ansible_user: root`, `iac:inventory/group_vars/lxcs/vars.yml`), and
  provisioning injects the fleet key into `/root/.ssh/authorized_keys`
  (`iac:playbooks/roles/infrastructure/lxc_ssh_key_injector/tasks/main.yml`).
- **No `faviann` account on this kind of host.** `lxc_ssh_user: faviann` is
  created only by `lxc_docker_environment` (Docker hosts) and
  `lxc_browser_device`. On a tier_small host with no capabilities,
  `lxc_github_keys` writes `/home/faviann/.ssh/authorized_keys` owned by uid
  1000, but no `faviann` account exists to log in with.
- **Consequence.** The operator logs in to `bootstrap` as root and runs
  `bw`, `chezmoi`, and `./run.sh` as root. chezmoi renders into `/root`.
  homelab-iac reads `$HOME/.ansible/vault-pass`
  (`iac:scripts/lib/live-execution.sh`, `iac:vault.sh`) and
  `Path.home() / ".ansible/ssh/proxmox_lxc"` (`iac:scripts/live_dependencies.py`),
  so the paths line up with no change.
- **`sudo` as root.** It does not prompt, so `install-packages` works as root
  once `lxc_base_system` has installed `sudo`.

## What breaks on a fresh LXC

| Timing | What happens |
|---|---|
| Before homelab-iac has configured the LXC (no `sudo`, `curl`, `git`) | The `.ansible/*` secrets render. `install-herdr` then fails because `curl` is missing, and the apply stops with a non-zero exit. The after scripts never run. |
| After a normal `./run.sh --limit bootstrap` from the workstation (`sudo` and `curl` present, `git` absent) | Secrets render. `herdr` and `fish` install. `switch-chezmoi-origin-to-ssh` exits 1 with "chezmoi source repo has no origin remote", because `git` is missing and `$(git … \|\| true)` is empty. chezmoi falls back to its built-in git for the clone itself, so init gets this far. |
| In every case | `sudo snap install bw` fails, so `bw` has to be installed another way first. |

The bootstrap node needs `git` anyway to fetch homelab-iac (map decision), so
the last failure disappears once `git` is a declared package for that host.

## Minimal changes

Changes in `faviann/dotfiles`:

1. **Guard `run_once_install-herdr.sh.tmpl` with `{{ if .is_workstation }}`.**
   It is the only unguarded script that fetches and runs remote code, and it
   would do so on the node that holds the vault passphrase and the fleet key.
2. **Do not render the GitHub SSH key on the bootstrap node.** Add
   `.ssh/id_ed25519`, `.ssh/id_ed25519.pub`, `.ssh/allowed_signers`, and
   `.ssh/config` to `.chezmoiignore` for that host. Skip
   `run_after_switch-chezmoi-origin-to-ssh` there too, because it depends on
   that key. This also removes the `dotfiles/workstation-ssh-key` lookup, so the
   node reads only the two items it needs.
3. **Select the host by name, not by "not the workstation".** Today
   `is_workstation == false` means "every other machine". The smallest clean
   form is a second flag in `.chezmoi.toml.tmpl` (for example
   `is_bootstrap = eq .chezmoi.hostname "bootstrap"`), used by changes 1–2 and
   to ignore `.config/fish/`, `.local/bin/`, `.gitconfig`, and `.npmrc` there.
   The `fish` install can stay unguarded. It is harmless once `sudo` exists.
4. **Document a bootstrap-node path in `BOOTSTRAP.md`.** Install the native
   `bw` binary instead of the snap, with `unzip` or the same digest-checked zip
   flow as `lxc_workstation_baseline`. Install chezmoi with the
   `get.chezmoi.io` script. Run as root.

One prerequisite is the user's decision, not a code change:

5. **Make `faviann/dotfiles` reachable without a GitHub credential.** Either
   carry out the public flip that ADR 0001 already accepts, or accept a
   one-time credential entry during `chezmoi init` on the bootstrap node.

Changes 1–3 together are under 10 lines of template. Without them, the node
still works as a control node. It also carries the personal GitHub key and
runs an unpinned third-party installer, both of which go against keeping the
bootstrap node minimal.

Spec-side items for homelab-iac, outside the dotfiles changes and named here
because the flow depends on them:

- Install `git` (and `unzip` if `bw` is fetched as a zip) on `bootstrap`.
- Install `uv`, which `./run.sh` treats as a machine prerequisite.
