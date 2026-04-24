# Design: Stable Workstation GitHub SSH Identity

- **Date**: 2026-04-24
- **Status**: Approved

## Problem

The `workstation` LXC needs stable GitHub SSH behavior across rebuilds. The current baseline can generate an SSH key inside the LXC and attempt to register that public key with GitHub through controller-side `gh`, but that makes the workstation identity transient and makes provisioning depend on a controller GitHub CLI token.

The target behavior is different: if the LXC is destroyed and recreated, the rebuilt workstation should regain the same Git-over-SSH identity after the personal dotfiles layer is applied. Normal Git clone, pull, push, and SSH commit signing should work without creating new GitHub keys every rebuild.

## Goals

- Keep the workstation's outbound GitHub SSH identity stable across LXC rebuilds.
- Avoid GitHub account mutation from the infrastructure Ansible lifecycle.
- Keep Git-over-SSH and GitHub CLI API auth as separate concerns.
- Store the dedicated workstation private key in Bitwarden for recovery.
- Restore the key through the `dotfiles` chezmoi layer.
- Preserve `lxc_github_keys` for inbound LXC SSH access.
- Keep operational GitHub/key details in the `dotfiles` repo, not duplicated in this infrastructure repo.

## Non-Goals

- Fully automate `gh auth login`.
- Rotate GitHub SSH keys automatically.
- Store the workstation GitHub SSH private key in Ansible Vault.
- Make `ServerManagementScripts` apply dotfiles during `site.yml`.
- Use GitHub APIs from the one-time migration helper.

## Ownership Boundary

### `dotfiles` Owns Outbound GitHub Identity

The `dotfiles` repo owns user-level GitHub SSH and Git signing state:

- `~/.ssh/id_ed25519`
- `~/.ssh/id_ed25519.pub`
- `~/.ssh/config`
- `~/.ssh/allowed_signers`
- Git signing configuration
- GitHub `known_hosts`
- key bootstrap, verification, and rotation documentation

The key is a dedicated workstation key, not a generic personal laptop key. It is used for both GitHub SSH authentication and SSH commit signing. GitHub must have the public key registered once as an Authentication Key and once as a Signing Key.

### `ServerManagementScripts` Owns Baseline Capability

This repo owns the infrastructure baseline:

- provision the `workstation` LXC
- create/configure the daily user
- install stable tools such as `git`, `gh`, `chezmoi`, `bw`, SSH tooling, `tmux`, and Docker support
- preserve inbound LXC SSH access through `config/lxc_github_keys`
- point the operator to `dotfiles` for operator readiness

This repo must not own or mutate the workstation's outbound GitHub identity.

## Stable Key Bootstrap

A one-time shell helper will be run directly on the live workstation LXC. It is a migration helper, not committed lifecycle automation.

The helper will:

- require `BW_SESSION` to already be set and valid
- fail clearly if required commands are missing: `bw`, `jq`, `ssh-keygen`
- use existing `~/.ssh/id_ed25519` if present
- generate a new Ed25519 key with comment `faviann@workstation` if no key exists
- preserve the comment on an existing imported key
- derive or repair `~/.ssh/id_ed25519.pub` if missing or mismatched
- enforce `~/.ssh` mode `0700`
- enforce private key mode `0600`
- enforce public key mode `0644`
- create the Bitwarden item `dotfiles/workstation-ssh-key`
- store the private key in item notes
- store the public key in a custom field named `public_key`
- refuse to overwrite an existing Bitwarden item unless `--replace` is passed
- verify the Bitwarden item after writing
- print only the public key and manual GitHub registration instructions

The helper will not:

- print private key material
- call GitHub APIs
- install missing packages
- apply dotfiles
- write to this infrastructure repo

## Dotfiles Restore Behavior

After migration, Bitwarden plus chezmoi is authoritative for the workstation key files.

The `dotfiles` repo should add templates equivalent to:

- `private_dot_ssh/private_id_ed25519.tmpl`, rendered from the Bitwarden item notes
- `private_dot_ssh/id_ed25519.pub.tmpl`, rendered from the `public_key` custom field

The existing dotfiles SSH config and Git signing config should continue to use the standard key path:

```text
~/.ssh/id_ed25519
```

Missing or invalid `BW_SESSION` should fail the dotfiles apply. The apply should not silently skip restoring the SSH key.

### Initial Bootstrap URL

Because the SSH key is restored by dotfiles, initial chezmoi bootstrap must use HTTPS:

```bash
chezmoi init --apply https://github.com/faviann/dotfiles.git
```

After apply, dotfiles should automatically switch the chezmoi source repo remote to SSH:

```bash
git@github.com:faviann/dotfiles.git
```

That remote switch should be idempotent:

- run only when the chezmoi source repo exists
- switch only the expected HTTPS origin for `faviann/dotfiles`
- do nothing if already using SSH
- fail clearly or leave untouched if the remote is unexpected

### GitHub Known Hosts

Dotfiles should manage the daily user's GitHub `known_hosts` entry with a simple `ssh-keyscan github.com` script. This is acceptable for the homelab bootstrap path and avoids storing static GitHub host key material in dotfiles. The trust tradeoff should be documented in dotfiles if needed.

## Infrastructure Cleanup

After dotfiles restore is verified, `playbooks/roles/config/lxc_workstation_baseline` should stop managing outbound GitHub SSH identity.

Remove from that role:

- GitHub `known_hosts` management for the daily user
- `ssh-keygen` generation of `~/.ssh/id_ed25519`
- public key slurp/fact tasks
- controller-side `gh auth status`
- controller-side `gh api user/keys` listing
- GitHub SSH public key registration
- unused `workstation_github_*` defaults and argument spec entries

Keep in that role:

- workstation package installation
- `gh` package installation, unauthenticated by default
- `chezmoi` installation
- `bw` installation
- `config/lxc_github_keys` for inbound `authorized_keys`

The `config/lxc_github_keys` role remains unchanged. It manages inbound SSH login keys for LXCs and is separate from the workstation's outbound GitHub SSH identity.

## GitHub CLI Auth

`gh` CLI auth is intentionally separate from Git-over-SSH.

Git-over-SSH uses:

- `~/.ssh/id_ed25519`
- `~/.ssh/config`
- the GitHub authentication key registration

`gh` uses a local GitHub API token and is only needed for commands such as `gh pr`, `gh issue`, `gh workflow`, and `gh api`.

If `gh` is needed after rebuild, the operator can run:

```bash
gh auth login --git-protocol ssh --skip-ssh-key
```

The `--skip-ssh-key` flag prevents `gh` from creating or uploading another SSH key.

## Documentation

`dotfiles/BOOTSTRAP.md` should be the durable source of truth for:

- Bitwarden item shape
- manual GitHub auth/signing key registration
- initial HTTPS chezmoi bootstrap
- lightweight verification
- manual rotation runbook

`ServerManagementScripts` operational docs should avoid duplicating those details. The workstation handoff doc should shrink to a boundary pointer: this repo produces a baseline-ready LXC; operator readiness is completed by following the dotfiles bootstrap docs.

The formal design spec may mention `dotfiles/workstation-ssh-key` because it is an implementation record, not the day-to-day runbook.

## Verification

After dotfiles apply, use lightweight checks:

```bash
test -s ~/.ssh/id_ed25519
test -s ~/.ssh/id_ed25519.pub
diff <(ssh-keygen -y -f ~/.ssh/id_ed25519) ~/.ssh/id_ed25519.pub
ssh -T git@github.com
git config --global --get user.signingkey
```

A scratch signed commit test is intentionally deferred. GitHub's `Verified` badge after a pushed signed commit is enough for day-to-day confidence.

`gh auth status` is not part of baseline readiness.

## Migration Order

1. Run the one-time helper on the live workstation LXC to import or generate the stable key and write the Bitwarden item.
2. Manually register the public key in GitHub as both Authentication Key and Signing Key.
3. Update `dotfiles` to restore the key, manage GitHub SSH user state, and switch the source remote to SSH after HTTPS bootstrap.
4. Apply and verify dotfiles on the workstation.
5. Update `ServerManagementScripts` to remove conflicting outbound GitHub identity automation and shrink handoff docs.

This order avoids a gap where Ansible stops generating keys before dotfiles can restore them.

## Rotation

Rotation is documented, not automated.

Manual rotation should:

1. generate a new dedicated workstation key
2. update the Bitwarden item notes with the new private key
3. update the Bitwarden `public_key` field
4. add the new public key to GitHub as Authentication Key
5. add the new public key to GitHub as Signing Key
6. apply dotfiles and verify Git-over-SSH
7. remove the old GitHub auth/signing keys

Automating rotation is out of scope because it would require coordinating Bitwarden mutation, GitHub auth key mutation, GitHub signing key mutation, and live workstation file replacement.
