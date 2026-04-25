# Workstation Post-Provisioning Handoff

Use this after the `workstation` LXC has been provisioned by this repo.

## Boundary

`ServerManagementScripts` makes the workstation baseline-ready:

- normal managed LXC in `tier_large` + `cap_docker`
- non-root daily user: `faviann`
- inbound SSH access for `faviann` from GitHub public keys listed in `lxc_github_users`
- Docker runtime support with `docker_user: faviann`
- baseline packages installed by `config/lxc_workstation_baseline`
- `gh`, `chezmoi`, and `bw` installed but not personally authenticated

The separate `dotfiles` repo makes the workstation operator-ready.

## Operator Readiness

Follow the bootstrap documentation in:

```text
~/repos/dotfiles/BOOTSTRAP.md
```

That repo owns personal workstation state such as:

- outbound GitHub SSH identity
- Git SSH signing config
- GitHub `known_hosts`
- `~/.ansible/vault-pass`
- shell and personal workflow config
- optional `gh auth login`

Do not duplicate those personal bootstrap details here.

## Recovery Reminder

If the workstation is lost:

1. Recreate the LXC baseline from this repo.
2. Apply the separate dotfiles bootstrap.
3. Verify operator readiness using the dotfiles verification commands.
