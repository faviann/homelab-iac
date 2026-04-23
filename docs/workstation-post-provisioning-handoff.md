# Workstation Post-Provisioning Handoff

Use this after the `workstation` LXC has been provisioned by this repo.

## What This Repo Now Guarantees

The `workstation` host is baseline-ready:

- normal managed LXC in `tier_large` + `cap_docker`
- non-root daily user: `faviann`
- GitHub-backed SSH access for `faviann`
- Docker runtime support with `docker_user: faviann`
- `docker_agents_enabled: false`
- workstation baseline packages installed by `config/lxc_workstation_baseline`
- lifecycle wiring integrated into `site.yml`

This repo stops at the infrastructure baseline. It does not make the host operator-ready.

## What The Separate Workstation Repo Still Owns

The separate workstation repo is responsible for the personal/operator layer:

- dotfiles
- `sessions` command and tmux workflow
- Claude Code / Codex CLI / Copilot CLI setup
- Node, .NET, and other fast-moving toolchain choices
- workspace registry and project checkouts
- optional interactive SSH auto-menu
- any personal shell, editor, and session conventions

## Readiness States

- `Baseline ready`: the LXC exists, SSH works, and `faviann` can use tmux, Docker, and common tools.
- `Operator ready`: the separate workstation repo has been applied and the personal workflow is live.

## Post-Provisioning Checklist

1. Provision the host from this repo:
   `ansible-playbook site.yml --limit workstation`
2. SSH in as `faviann`.
3. Clone the separate workstation repo.
4. Run that repo's bootstrap/apply command.
5. Install and authenticate the agent CLIs and any required SDK/toolchain managers.
6. Verify the expected session workflow works:
   - tmux
   - `sessions` command
   - Docker as `faviann`
   - repo checkout/update flow
7. Confirm the host is now operator-ready.

## Fill These In Later

- Workstation repo URL/path:
  `git@github.com:faviann/dotfiles.git`
- Clone location on the LXC:
  `~` (chezmoi clones internally to `~/.local/share/chezmoi`)
- Bootstrap/apply command:
  `chezmoi init --apply git@github.com:faviann/dotfiles.git`
- Any required auth/bootstrap prerequisites:
  1. `bw login` (Bitwarden — interactive, one-time per machine)
  2. `export BW_SESSION=$(bw unlock --raw)` (unlock vault)
  3. chezmoi and bitwarden-cli must be installed first

## Useful Validation

Run these after the personal repo is applied:

- `whoami`
- `tmux -V`
- `docker ps`
- `gh auth status`
- `codex --help`
- `claude --help`
- `sessions`

Adjust the last three to match the actual tools and command names you install.

## Recovery Reminder

If the workstation is lost:

1. recreate the LXC baseline from this repo
2. restore any required local secrets on the new host
3. re-clone and reapply the separate workstation repo

The baseline is owned here. The personal workflow is restored from the separate workstation repo.
