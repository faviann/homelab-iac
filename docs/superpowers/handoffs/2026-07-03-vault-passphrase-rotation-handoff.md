# Handoff — Vault Passphrase Rotation

**Date**: 2026-07-03
**Branch**: `feat/vault-passphrase-rotation`
**Status**: Script authored + reviewed, **not yet run on a live workstation**

## Why this exists

The Ansible Vault passphrase protecting `inventory/group_vars/all/vault.yml` is weak
(15 chars, lowercase-only + 1 special) and Ansible Vault's KDF is a fixed, un-tunable
PBKDF2 at 10,000 iterations. `vault.yml` is currently gitignored and has never been
committed, but the goal is to be able to commit it to the **public** repo — which is only
safe with a strong passphrase. This work rotates the passphrase to a long random value and
re-encrypts the vault.

**Not addressed (out of scope):** rotating the individual secret *values* inside the vault,
changing the KDF (impossible), making the repo private. Note: passphrase rotation does
**not** protect any secret that was already exposed — that needs value rotation.

## What's in this branch

| File | What |
|------|------|
| `rotate-vault-passphrase.sh` | The interactive rotation script (repo root, `+x`) |
| `docs/superpowers/specs/2026-07-03-vault-passphrase-rotation-design.md` | Authoritative design spec |
| `docs/superpowers/handoffs/2026-07-03-vault-passphrase-rotation-handoff.md` | This file |

## What the script does (rekey-then-publish)

1. Preflight: `bw` unlocked, `~/.ansible/vault-pass` present (= OLD), `vault.yml` encrypted,
   resolve Bitwarden item + field.
2. Generate NEW: `bw generate -ulns --length 32` → tmpfs mode-600 file, never echoed.
3. Backup `vault.yml` → `~/.ansible/vault.yml.bak.<ts>` (outside repo).
4. `ansible-vault rekey` OLD→NEW.
5. Verify NEW decrypts (`ansible-vault view --vault-password-file=$NEW`).
6. Re-check `bw` unlocked, then publish NEW to the Bitwarden item
   (`bw get item | jq --rawfile | bw encode | bw edit`).
7. `chezmoi apply` regenerates `~/.ansible/vault-pass`.
8. End-to-end verify via the live file (authoritative). Then report.

Bitwarden is mutated **last**; all plaintext lives only on tmpfs (`/dev/shm`), mode 600,
shredded on exit; no passphrase is ever echoed or passed as a process argument.

## Recovery behavior (important)

Two-directional, gated on whether `chezmoi apply` may have switched the live file:

- **Before `chezmoi apply`** — roll **back**: restore `vault.yml` from the OLD backup →
  OLD/OLD consistent.
- **After `chezmoi apply`** — roll **forward**: force the live file to NEW from the tmpfs
  copy (`vault.yml` is verified-NEW, Bitwarden is NEW) → NEW/NEW consistent. Rolling back
  here would strand `vault.yml` on an OLD backup that is no longer decryptable, so forward
  is the safe direction.

This closed a brick/data-loss window in the first draft. Forward recovery also auto-heals
the most likely real failure: `BW_FIELD` not matching the field the chezmoi template reads.

## BEFORE running — must do on the real workstation

This environment has no `bw` / `chezmoi` / `~/.ansible/vault-pass`, so runtime behavior was
never exercised. On the workstation:

1. **Confirm `BW_ITEM` and `BW_FIELD`.** Check the `faviann/dotfiles` chezmoi template to see
   which Bitwarden item id and field it reads for `~/.ansible/vault-pass`. The script defaults
   `BW_ITEM` to a `<REPLACE_ME…>` sentinel that hard-aborts before any mutation. Pass via env
   or flags:
   ```
   BW_ITEM=<item-id> BW_FIELD=<password|notes|auto|custom-name> ./rotate-vault-passphrase.sh
   ```
   `BW_FIELD=auto` prefers a non-empty `login.password`, else `notes`, and aborts if both are
   populated (ambiguous).
2. **Unlock Bitwarden:** `export BW_SESSION=$(bw unlock --raw)`.
3. **Dry-run against a throwaway vault first.** The money path (rekey → `bw edit` →
   `chezmoi apply`) only exercises on the live box. Suggested smoke test: copy an encrypted
   test vault + a scratch `vault-pass`, point the script's file vars at them, and confirm a
   clean OLD→NEW→verify cycle before touching the real vault.
4. After a successful run: verify normal ops (`uv run --locked ansible-vault view
   inventory/group_vars/all/vault.yml`), then `shred -u ~/.ansible/vault.yml.bak.<ts>`.

## Validation done here

- `bash -n`: clean.
- `shellcheck` v0.10.0: clean (intentional SC2016 on jq `$pass`/`$fname` documented with
  targeted disables).
- Recovery-path defect found in review and fixed (see above).
- **Not** run end-to-end (no live tooling in this env).

## Resolved (2026-07-03, on workstation `glados`)

- **`BW_ITEM` = `dotfiles/ansible-vault-pass`**, **`BW_FIELD` = `notes`** — confirmed from the
  chezmoi template `private_dot_ansible/private_vault-pass.tmpl` in `repos/dotfiles`, which
  renders `~/.ansible/vault-pass` from `(bitwarden "item" "dotfiles/ansible-vault-pass").notes`.
  Run command: `BW_ITEM='dotfiles/ansible-vault-pass' BW_FIELD=notes ./rotate-vault-passphrase.sh`.
- `bw` is the **snap** build (`/snap/bin/bw`, 2026.6.0), currently *locked*. Unlock with
  `export BW_SESSION=$(bw unlock --raw)` before running.
- Env repaired: `.venv` was stale (shebangs pointed at old `ServerManagementScripts` path). It
  was deleted and rebuilt via `uv sync --locked`; current `~/.ansible/vault-pass` decrypts
  `vault.yml` cleanly.
- **Dry-run added + smoke test passed.** `VAULT_FILE`/`LIVE_PASS_FILE` are now env-overridable,
  and a new `--dry-run` flag rekeys+verifies throwaway *tmpfs copies* of the real vault/pass
  (generates the NEW passphrase locally, so no bw session needed) and stops before any
  Bitwarden/chezmoi mutation. Ran `./rotate-vault-passphrase.sh --dry-run` on `glados`:
  OLD→NEW rekey + NEW-decrypts-verify passed; real vault, Bitwarden, and `~/.ansible/vault-pass`
  untouched, tmpfs workspace shredded on exit. `--dry-run` does **not** exercise the Bitwarden
  publish or `chezmoi apply` steps (those can't run without mutating the real item).

## Open questions for next session
- Whether the dotfiles chezmoi template writes `vault-pass` with a trailing newline
  (ansible strips it, so decryption is fine — noted only so a checksum-style check is not
  reintroduced).
- Decision to actually commit `vault.yml` to the repo after rotation is a **separate**
  follow-up, not part of this branch.
