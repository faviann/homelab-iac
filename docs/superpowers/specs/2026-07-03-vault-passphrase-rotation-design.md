# Vault Passphrase Rotation — Design

**Date**: 2026-07-03
**Status**: Design — pending implementation plan
**Author**: rotation tooling for the Ansible Vault passphrase

## Problem

The Ansible Vault passphrase protecting `inventory/group_vars/all/vault.yml` is weak
for a **public** GitHub repo:

- **15 chars, lowercase-only + 1 special** (~65–70 bits if random; far less if word-based).
- Ansible Vault's KDF is **PBKDF2-HMAC-SHA256 at 10,000 iterations, hardcoded and
  not tunable** in the installed ansible (`ansible/parsing/vault/__init__.py:1137`).
- A public repo means unlimited offline brute-force against the ciphertext.

The passphrase is the entire security boundary. We strengthen it by rotating to a
long random passphrase and re-encrypting the vault.

Out of scope (explicitly deferred): rotating the individual secret *values* inside the
vault, changing the KDF (impossible without patching ansible), and making the repo private.

## Current model (verified)

- **Source of truth**: a Bitwarden item. The chezmoi template already reads it via
  `bw get` (state confirmed: "already bw-templated, just stale value").
- **Sync**: `chezmoi apply` regenerates `~/.ansible/vault-pass` from that item.
- **Consumption**: `ansible.cfg` points the vault password file at
  `~/.ansible/vault-pass`. `setup.sh` treats the file as read-only and provisioned
  out-of-band (chezmoi + Bitwarden).

Therefore the only value that must change is the **Bitwarden item's field**; everything
else flows from `chezmoi apply`.

## Requirements

- **R1** — Generate a long random passphrase via the Bitwarden CLI
  (`bw generate -ulns --length 32`).
- **R2** — Re-encrypt `vault.yml` from the old passphrase to the new one.
- **R3** — Publish the new passphrase to the existing Bitwarden item (full-auto).
- **R4** — Regenerate `~/.ansible/vault-pass` via `chezmoi apply` and confirm it matches.
- **R5** — Never print any passphrase; keep plaintext only in mode-600 temp files with
  guaranteed cleanup.
- **R6** — Fail safe: Bitwarden is mutated last, so any earlier failure leaves the
  system unchanged; a rekey failure auto-restores `vault.yml` from backup.
- **R7** — Verify the new passphrase actually decrypts the vault before and after
  publishing.

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

1. **Preflight**
   - `bw status` shows `unlocked`; if not, prompt the user to run `bw unlock` and export
     `BW_SESSION` (do not capture the master password in the script).
   - `~/.ansible/vault-pass` exists and is non-empty → this is the OLD passphrase.
   - `vault.yml` first line matches `$ANSIBLE_VAULT` (it is encrypted).
   - Resolve the **Bitwarden item id** and **which field** the chezmoi template reads
     (`bw get password <id>` vs `bw get notes <id>` vs a custom field). Default item
     reference configurable via env/flag; discovery step documented against the dotfiles
     template. Abort if ambiguous.

2. **Generate** the new passphrase: `bw generate -ulns --length 32` captured directly
   into a `mktemp` file `NEW` created inside a mode-700 working dir, `chmod 600`.
   An `EXIT`/`ERR` trap `shred -u`s all temp files.

3. **Backup** `vault.yml` → `vault.yml.bak.<timestamp>` (mode 600).

4. **Rekey locally** with explicit files, not the live path:
   `uv run --locked ansible-vault rekey --vault-password-file="$OLD"
   --new-vault-password-file="$NEW" inventory/group_vars/all/vault.yml`
   where `OLD` is a copy of `~/.ansible/vault-pass` into a temp file.

5. **Verify (new decrypts)**:
   `uv run --locked ansible-vault view --vault-password-file="$NEW"
   inventory/group_vars/all/vault.yml` exits 0. On failure → restore `vault.yml` from the
   backup, abort, Bitwarden untouched.

6. **Publish to Bitwarden**: read the item JSON (`bw get item <id>`), set the resolved
   field to the new passphrase via `jq`, `bw encode`, `bw edit item <id>`. Then
   `bw sync`.

7. **chezmoi apply** regenerates `~/.ansible/vault-pass`; assert its content now equals
   `NEW` (compare via checksum of the files, never print). If mismatch → loud failure with
   manual remediation (Bitwarden already updated; instruct re-running `chezmoi apply` /
   checking the template item reference).

8. **End-to-end verify**: `uv run --locked ansible-vault view
   inventory/group_vars/all/vault.yml` using the **live** password file (no override
   flags) exits 0.

9. **Cleanup & report**: trap shreds temp files. Print the backup path and a warning that
   the backup (and any prior git history, if ever pushed) still holds ciphertext under the
   old passphrase — delete the backup once satisfied.

## Error handling / rollback summary

| Failure point | State | Recovery |
|---------------|-------|----------|
| Preflight (1) | Nothing changed | Fix precondition, rerun |
| Generate/backup (2–3) | Nothing changed | Trap cleans temp; rerun |
| Rekey (4) | `vault.yml` possibly modified | Auto-restore from backup |
| New-decrypt verify (5) | `vault.yml` rekeyed but unverified | Auto-restore from backup |
| Bitwarden publish (6) | vault.yml is NEW, BW may be partial | Manual: rerun publish step |
| chezmoi apply (7) | BW is NEW, local file may be stale | Rerun `chezmoi apply`; verify item ref |
| Final verify (8) | Everything applied | Investigate; backup available |

## Security constraints

- No passphrase (old or new) is ever echoed, logged, or passed as a CLI arg where it lands
  in process listings — only via `--*-password-file` pointing at mode-600 temp files.
- Temp files live in a `mktemp -d` dir (mode 700); `trap 'shred -u ...' EXIT ERR INT`.
- The script never handles the Bitwarden master password; it requires a pre-unlocked
  session (`BW_SESSION`).
- The old-passphrase backup of `vault.yml` is flagged to the user for deletion.

## Open items to resolve during implementation

- Exact Bitwarden item id and field the dotfiles chezmoi template consumes — discover from
  the `faviann/dotfiles` template; wire as a configurable default.
- Whether `bw edit item` requires re-fetching the item revision to avoid clobbering
  concurrent edits (single-user, low risk, but confirm the `bw` round-trip).
