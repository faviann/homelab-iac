# Vault Passphrase Rotation — Design

**Date**: 2026-07-03
**Status**: Design — reviewed (agent), pending implementation plan
**Author**: rotation tooling for the Ansible Vault passphrase

## Problem

The Ansible Vault passphrase protecting `inventory/group_vars/all/vault.yml` is too weak
to safely publish. Motivation: the vault is currently **gitignored and has never been
committed** (verified: empty `git log --all` for the path), but the intent is to be able
to commit it to the **public** repo. Before that is safe, the passphrase must be strong:

- **15 chars, lowercase-only + 1 special** (~65–70 bits if random; far less if word-based).
- Ansible Vault's KDF is **PBKDF2-HMAC-SHA256 at 10,000 iterations, hardcoded and
  not tunable** in the installed ansible (`ansible/parsing/vault/__init__.py:1137`).
- If ever published, a public repo means unlimited offline brute-force against the
  ciphertext, and the passphrase is the entire security boundary.

**Important caveat**: passphrase rotation only protects secrets that have **not already
been exposed**. If the ciphertext or any secret value has ever leaked, rotating the
passphrase does nothing for the already-captured data — those require rotating the secret
*values* (explicitly out of scope here). This rotation is defense for a *future/planned*
commit, not remediation of a past exposure.

Out of scope (explicitly deferred): rotating the individual secret *values* inside the
vault, changing the KDF (impossible without patching ansible), and making the repo private.

## Current model (verified)

- **Source of truth**: a Bitwarden item. The chezmoi template already reads it via
  `bw get` (state confirmed: "already bw-templated, just stale value").
- **Sync**: `chezmoi apply` regenerates `~/.ansible/vault-pass` from that item.
- **Consumption**: `ansible.cfg` sets `vault_password_file = ~/.ansible/vault-pass`.
  Explicit `--vault-password-file` flags override it (verified). `setup.sh` treats the file
  as read-only and provisioned out-of-band (chezmoi + Bitwarden).

Therefore the only value that must change is the **Bitwarden item's field**; everything
else flows from `chezmoi apply`.

## Requirements

- **R1** — Generate a long random passphrase via the Bitwarden CLI
  (`bw generate -ulns --length 32`).
- **R2** — Re-encrypt `vault.yml` from the old passphrase to the new one.
- **R3** — Publish the new passphrase to the existing Bitwarden item (full-auto).
- **R4** — Regenerate `~/.ansible/vault-pass` via `chezmoi apply` and confirm decryption
  works end-to-end via the live file.
- **R5** — Never print or pass any passphrase as a process argument; keep plaintext only
  in mode-600 files **on tmpfs** with guaranteed cleanup.
- **R6** — Fail safe: on **any** failure after the local rekey, auto-restore `vault.yml`
  from backup so the system returns to a fully-OLD consistent state; Bitwarden is mutated
  last.
- **R7** — Verify the new passphrase actually decrypts the vault before publishing and
  again through the live file after `chezmoi apply`.

## Deliverable

A single interactive script `rotate-vault-passphrase.sh` in the repo root, matching the
style/helpers of `setup.sh` and `configure-vault.sh` (status/info/error print helpers,
`set -euo pipefail`).

## Flow (rekey-then-publish)

The ordering is load-bearing. `ansible-vault rekey` needs the **old** passphrase to
decrypt and the **new** to re-encrypt. Publishing to Bitwarden / running `chezmoi apply`
*before* the rekey would leave the live `~/.ansible/vault-pass` holding the new value
while `vault.yml` is still encrypted with the old — breaking decryption. So Bitwarden and
chezmoi are touched only after the local rekey provably succeeds.

**Workspace**: a `mktemp -d -p /dev/shm` directory (tmpfs, mode 700) so plaintext never
lands on the journaled ext4 working tree (where `shred` is unreliable). A
`trap 'cleanup' EXIT INT TERM HUP` shreds files then `rm -rf`s the dir; EXIT fires after
ERR under `set -e`.

1. **Preflight**
   - `bw status` shows `unlocked`; if not, instruct the user to run `bw unlock` and export
     `BW_SESSION` (the script never handles the master password).
   - `~/.ansible/vault-pass` exists and is non-empty → this is the OLD passphrase, used
     directly as `--vault-password-file` (no temp copy — narrows plaintext footprint).
   - `vault.yml` first line matches `$ANSIBLE_VAULT` (it is encrypted).
   - Resolve the **Bitwarden item id** and **which field** the chezmoi template reads
     (`bw get password <id>` vs `bw get notes <id>` vs a custom field). Default item
     reference configurable via env/flag; discovery documented against the dotfiles
     template. Abort if ambiguous.

2. **Generate** the new passphrase: `bw generate -ulns --length 32` captured directly into
   a tmpfs file `NEW` (`chmod 600`). Never echoed.

3. **Backup** `vault.yml` → **outside the repo**: `~/.ansible/vault.yml.bak.<timestamp>`
   (mode 600). Kept out of the working tree so it can never be swept into a commit
   (`.gitignore`'s `*.bak` glob does **not** match `vault.yml.bak.<ts>`).

4. **Rekey locally** with explicit files:
   `uv run --locked ansible-vault rekey
   --vault-password-file="$HOME/.ansible/vault-pass"
   --new-vault-password-file="$NEW" inventory/group_vars/all/vault.yml`

5. **Verify (new decrypts)**:
   `uv run --locked ansible-vault view --vault-password-file="$NEW"
   inventory/group_vars/all/vault.yml` exits 0. On failure → restore `vault.yml` from the
   backup, abort, Bitwarden untouched.

6. **Re-check `bw status`** (session may have timed out during the multi-minute rekey);
   fail cleanly here if locked (still recoverable — see rollback). Then **publish to
   Bitwarden**: `bw get item <id>` → stream the JSON through `jq` setting the resolved
   field from the secret file via `--rawfile pass "$NEW"` (with `rtrimstr("\n")`), never
   `--arg`/interpolation → pipe into `bw encode | bw edit item <id>`. The secret never
   appears in a process argument or on disk outside tmpfs.

7. **chezmoi apply** regenerates `~/.ansible/vault-pass` from the updated item.
   (No byte-for-byte checksum gate — the chezmoi-written file may differ only by a trailing
   newline, which ansible strips; the authoritative check is step 8.)

8. **End-to-end verify**: `uv run --locked ansible-vault view
   inventory/group_vars/all/vault.yml` using the **live** password file (no override flags)
   exits 0. This is the single source of truth that rotation succeeded.

9. **Cleanup & report**: trap shreds tmpfs files and removes the workdir. Print the backup
   path with a warning that it holds ciphertext under the **old** passphrase — delete it
   once satisfied.

## Recovery invariant

`vault.yml` is only ever in one of two consistent states: encrypted with OLD (recoverable
from the backup) or encrypted with NEW (verified decryptable via `$NEW`, then via the live
file). **On any failure after step 4, before releasing the trap, restore `vault.yml` from
the OLD backup** — this guarantees the live `~/.ansible/vault-pass` (still OLD until a
successful `chezmoi apply`) can always decrypt it. This closes the brick window where the
trap would otherwise shred the only NEW copy while `vault.yml` is NEW and the live file is
OLD.

## Error handling / rollback summary

| Failure point | State after auto-recovery | Manual step, if any |
|---------------|---------------------------|---------------------|
| Preflight (1) | Nothing changed | Fix precondition, rerun |
| Generate/backup (2–3) | Nothing changed | Rerun |
| Rekey (4) | `vault.yml` restored to OLD | Rerun |
| New-decrypt verify (5) | `vault.yml` restored to OLD | Investigate ansible/bw, rerun |
| Re-check / publish (6) | `vault.yml` restored to OLD | Re-unlock `bw`, rerun whole script |
| chezmoi apply (7) | `vault.yml` restored to OLD; **BW already NEW** | Rerun script: preflight sees BW=NEW as the OLD-of-next-run mismatch → instead re-run `chezmoi apply` manually, then step 8 |
| Final verify (8) | Everything applied | Investigate; OLD backup still available |

Note on step 7 failure: Bitwarden holds NEW but `vault.yml` was restored to OLD. The safe
manual recovery is to re-run `chezmoi apply` (bringing the live file to NEW) and re-key
`vault.yml` OLD→NEW again, or restore from backup and re-run the whole script (which will
detect BW already holds the intended value). The implementation plan must spell out this
one non-auto path explicitly.

## Security constraints

- No passphrase (old or new) is ever echoed, logged, or passed as a CLI argument (avoids
  `/proc/<pid>/cmdline` exposure) — only via `--*-password-file` and jq `--rawfile`.
- All plaintext temp files live on **tmpfs** (`/dev/shm`), mode 600, in a mode-700 dir;
  `trap 'cleanup' EXIT INT TERM HUP` shreds files then `rm -rf` the dir.
- The script never handles the Bitwarden master password; it requires a pre-unlocked
  session (`BW_SESSION`).
- The old-passphrase backup lives outside the repo and is flagged for deletion.
- `.ansible/cache/` holds host facts only (no vault plaintext) — no action needed.

## Open items to resolve during implementation

- Exact Bitwarden item id and field the dotfiles chezmoi template consumes — discover from
  the `faviann/dotfiles` template; wire as a configurable default.
- Whether `bw edit item` needs a fresh item revision to avoid clobbering (single-user, low
  risk; `bw get item` immediately before edit suffices). `bw sync` is **not** issued after
  edit — `bw edit` updates the local cache that chezmoi's `bw get` reads; add sync only if
  the template forces a remote pull.
- Exact wording of the step-7-failure manual recovery path in the plan.
