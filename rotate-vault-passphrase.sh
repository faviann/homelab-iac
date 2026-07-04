#!/bin/bash
# Rotate the Ansible Vault passphrase protecting inventory/group_vars/all/vault.yml.
#
# Flow (rekey-then-publish): re-encrypt vault.yml OLD->NEW locally and verify it, and
# ONLY THEN mutate Bitwarden and regenerate the live ~/.ansible/vault-pass via
# `chezmoi apply`. Bitwarden is the source of truth the chezmoi template reads; touching
# it before the local rekey would leave the live password file NEW while vault.yml is
# still OLD, breaking decryption. See:
#   docs/superpowers/specs/2026-07-03-vault-passphrase-rotation-design.md
#
# Security: no passphrase (old or new) is ever echoed, logged, or passed as a process
# argument. Plaintext lives only in mode-600 files on tmpfs (/dev/shm) inside a mode-700
# dir, shredded on exit. See the spec's "Security constraints" section.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Determine project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Helper functions
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# ─────────────────────────────────────────────────────────────────────────────
# Configuration — OPEN ITEMS (confirm against the faviann/dotfiles chezmoi template)
# ─────────────────────────────────────────────────────────────────────────────
# The chezmoi template that regenerates ~/.ansible/vault-pass reads the passphrase from
# a Bitwarden item. Two things must match that template exactly:
#   1. BW_ITEM  — the item id (or name) the template's `bw get` targets.
#   2. BW_FIELD — which field holds the value: "password", "notes", or a custom field name.
#
# These are OPEN ITEMS in the design spec. Confirm both by reading the dotfiles template
# (the file under faviann/dotfiles that renders ~/.ansible/vault-pass via `bw get ...`).
# Until confirmed here, the defaults below are PLACEHOLDERS and the script will refuse to
# publish rather than clobber the wrong field.
#
# Override without editing the file:
#   BW_ITEM=<id> BW_FIELD=password ./rotate-vault-passphrase.sh
#   ./rotate-vault-passphrase.sh --item <id> --field password
BW_ITEM="${BW_ITEM:-<REPLACE_ME_BITWARDEN_ITEM_ID>}"   # PLACEHOLDER — set to the real item id
BW_FIELD="${BW_FIELD:-auto}"                            # auto | password | notes | <custom-field-name>

# Paths (env-overridable so a --dry-run can point at a throwaway vault/pass pair).
# NOTE: overriding these is intended for --dry-run ONLY. In a real rotation, Step 7
# (`chezmoi apply`) and Step 8 (verify via ansible.cfg) always target the REAL
# ~/.ansible/vault-pass regardless of LIVE_PASS_FILE, so overriding it for a real run would
# rekey/verify against a throwaway file while chezmoi rewrites the real one — an OLD/NEW split.
VAULT_FILE="${VAULT_FILE:-inventory/group_vars/all/vault.yml}"
LIVE_PASS_FILE="${LIVE_PASS_FILE:-$HOME/.ansible/vault-pass}"

# Dry run: exercise the OLD->NEW rekey + verify cycle on throwaway tmpfs COPIES of the vault
# and pass file, then stop. Never touches the real files, Bitwarden, or chezmoi. Does NOT
# exercise the Bitwarden publish or `chezmoi apply` steps (those cannot run without mutating
# the real item). Generates the NEW passphrase locally, so no unlocked bw session is needed.
DRY_RUN=false

# ─────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --item)
            BW_ITEM="${2:-}"
            shift 2
            ;;
        --field)
            BW_FIELD="${2:-}"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            cat <<EOF
Usage: ./rotate-vault-passphrase.sh [--item <bitwarden-item-id>] [--field <name>]

Rotates the Ansible Vault passphrase for $VAULT_FILE.

Options:
  --item <id>     Bitwarden item id the chezmoi template reads (env: BW_ITEM)
  --field <name>  Field holding the passphrase: auto|password|notes|<custom>
                  (env: BW_FIELD; default: auto)
  --dry-run       Rekey + verify a throwaway COPY of the vault only. No bw session,
                  no Bitwarden write, no chezmoi apply. Safe to run against defaults.
  -h, --help      Show this help

Paths are env-overridable: VAULT_FILE, LIVE_PASS_FILE.

A real (non --dry-run) rotation requires a pre-unlocked Bitwarden session
(export BW_SESSION before running). The script never handles the master password.
EOF
            exit 0
            ;;
        *)
            print_error "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# ─────────────────────────────────────────────────────────────────────────────
# Workspace + cleanup trap
# ─────────────────────────────────────────────────────────────────────────────
# tmpfs (/dev/shm) so plaintext never lands on the journaled ext4 working tree, where
# `shred` is unreliable. Mode 700 dir; the NEW passphrase file inside is mode 600.
WORKDIR=""
NEW=""
BACKUP=""
REKEYED=false          # true once vault.yml has been re-encrypted to NEW (steps 4–8 window)
LIVE_MAY_BE_NEW=false  # true once `chezmoi apply` may have overwritten the live pass file
ROTATION_COMPLETE=false # true only after the final end-to-end verify passes

# Recovery invariant. vault.yml is only ever consistent as OLD/OLD or NEW/NEW. Which way we
# recover depends on whether `chezmoi apply` may already have switched the live pass file to
# NEW:
#   * Before chezmoi apply (LIVE_MAY_BE_NEW=false): live is still OLD, so roll BACK — restore
#     vault.yml from the OLD backup. System returns to OLD/OLD.
#   * After chezmoi apply (LIVE_MAY_BE_NEW=true): live may be NEW and OLD no longer exists
#     anywhere (Bitwarden already holds NEW). Rolling vault.yml back to OLD would strand it
#     (OLD backup becomes undecryptable). vault.yml is verified-NEW and untouched since the
#     rekey, so roll FORWARD instead — force the live file to NEW from the still-present tmpfs
#     copy. System converges to NEW/NEW.
# Called from every post-rekey error path BEFORE the trap shreds the only NEW copy.
recover() {
    [ "$ROTATION_COMPLETE" = true ] && return 0
    [ "$REKEYED" = true ] || return 0
    if [ "$LIVE_MAY_BE_NEW" = true ]; then
        # Roll forward: vault.yml is NEW, Bitwarden is NEW; make the live file NEW too.
        if [ -n "$NEW" ] && [ -f "$NEW" ] && cp -f "$NEW" "$LIVE_PASS_FILE" && chmod 600 "$LIVE_PASS_FILE"; then
            ROTATION_COMPLETE=true
            print_warning "Recovery: set $LIVE_PASS_FILE to the NEW passphrase (vault.yml is already NEW)."
            print_info "System is consistent on NEW. Bitwarden also holds NEW."
        else
            print_error "CRITICAL: could not write NEW to $LIVE_PASS_FILE. vault.yml and Bitwarden"
            print_error "both hold NEW. Recover manually: run 'chezmoi apply' to regenerate"
            print_error "$LIVE_PASS_FILE from Bitwarden, then 'ansible-vault view $VAULT_FILE'."
        fi
    else
        # Roll back: live is still OLD, restore vault.yml to OLD.
        if [ -n "$BACKUP" ] && [ -f "$BACKUP" ] && cp -f "$BACKUP" "$VAULT_FILE"; then
            REKEYED=false
            print_warning "Recovery: restored $VAULT_FILE to the OLD passphrase from backup."
            print_info "The live $LIVE_PASS_FILE (still OLD) can decrypt it again."
        else
            print_error "CRITICAL: failed to restore $VAULT_FILE from backup: $BACKUP"
            print_error "vault.yml may be NEW while the live password file is OLD. Do NOT run"
            print_error "chezmoi apply. Manually restore: cp '$BACKUP' '$VAULT_FILE'"
        fi
    fi
}

cleanup() {
    # Recover first (invariant), then shred + remove the tmpfs workspace.
    recover
    if [ -n "$WORKDIR" ] && [ -d "$WORKDIR" ]; then
        # Shred every plaintext file, then remove the dir.
        find "$WORKDIR" -type f -exec shred -u {} + 2>/dev/null || true
        rm -rf "$WORKDIR"
    fi
}
trap 'cleanup' EXIT INT TERM HUP

# Fail with recovery. Recovers (via the explicit path, not just the trap) then exits; the
# EXIT trap still runs cleanup (recover is a no-op the second time).
die() {
    print_error "$1"
    recover
    exit 1
}

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Rotate Ansible Vault Passphrase                           ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Preflight
# ─────────────────────────────────────────────────────────────────────────────
echo "Step 1: Preflight checks..."
echo "─────────────────────────────────────────"

# A dry run rekeys a throwaway copy and generates the passphrase locally, so it needs neither
# bw/jq/chezmoi nor an unlocked session.
if $DRY_RUN; then
    REQUIRED_CMDS="uv shred"
else
    REQUIRED_CMDS="bw jq chezmoi uv shred"
fi
for cmd in $REQUIRED_CMDS; do
    if ! command -v "$cmd" &> /dev/null; then
        die "Required command not found: $cmd"
    fi
done
print_status "Required tools present ($REQUIRED_CMDS)"

# Bitwarden session must be unlocked; the script never handles the master password.
if ! $DRY_RUN && [ "$(bw status 2>/dev/null | jq -r '.status')" != "unlocked" ]; then
    print_error "Bitwarden is not unlocked."
    print_info "Unlock and export the session, then rerun:"
    echo "  export BW_SESSION=\$(bw unlock --raw)"
    exit 1
fi
$DRY_RUN || print_status "Bitwarden session is unlocked"

# Live password file = OLD passphrase, used directly as --vault-password-file (no temp copy).
if [ ! -s "$LIVE_PASS_FILE" ]; then
    die "Live vault password file missing or empty: $LIVE_PASS_FILE"
fi
print_status "Old passphrase available at $LIVE_PASS_FILE"

# vault.yml must exist and be encrypted.
if [ ! -f "$VAULT_FILE" ]; then
    die "Vault file not found: $VAULT_FILE"
fi
# shellcheck disable=SC2016  # literal grep pattern; $ANSIBLE_VAULT must NOT expand
if ! head -n1 "$VAULT_FILE" | grep -q '\$ANSIBLE_VAULT'; then
    die "Vault file is not encrypted (missing \$ANSIBLE_VAULT header): $VAULT_FILE"
fi
print_status "Vault file present and encrypted"

# Resolve the Bitwarden item + field (skipped for --dry-run, which never publishes).
if ! $DRY_RUN; then
if [ -z "$BW_ITEM" ] || [ "$BW_ITEM" = "<REPLACE_ME_BITWARDEN_ITEM_ID>" ]; then
    print_error "Bitwarden item id is not configured (still the placeholder)."
    print_info "Set the real item id and rerun. Confirm it against the faviann/dotfiles"
    print_info "chezmoi template that renders $LIVE_PASS_FILE via 'bw get ...':"
    echo "  BW_ITEM=<id> BW_FIELD=<field> ./rotate-vault-passphrase.sh"
    echo "  # or: ./rotate-vault-passphrase.sh --item <id> --field <field>"
    exit 1
fi

# Pull the item JSON once to validate the reference and (if needed) auto-resolve the field.
ITEM_JSON="$(bw get item "$BW_ITEM" 2>/dev/null)" || die "Bitwarden item not found: $BW_ITEM"

# Determine which field holds the passphrase.
#   BW_FIELD=auto → detect: prefer a non-empty login.password, else a non-empty notes,
#   else fail as ambiguous (a custom field must be named explicitly).
resolve_field() {
    local has_password has_notes
    has_password="$(printf '%s' "$ITEM_JSON" | jq -r '((.login.password // "") | length) > 0')"
    has_notes="$(printf '%s' "$ITEM_JSON" | jq -r '((.notes // "") | length) > 0')"
    if [ "$has_password" = "true" ] && [ "$has_notes" = "true" ]; then
        die "Ambiguous field: item has BOTH a password and notes populated. Re-run with an explicit --field (password|notes|<custom-field-name>)."
    elif [ "$has_password" = "true" ]; then
        BW_FIELD="password"
    elif [ "$has_notes" = "true" ]; then
        BW_FIELD="notes"
    else
        die "Cannot auto-detect the passphrase field (neither password nor notes populated). Re-run with an explicit --field. Confirm against the dotfiles chezmoi template."
    fi
}

case "$BW_FIELD" in
    auto)
        resolve_field
        print_info "Auto-detected Bitwarden field: $BW_FIELD"
        ;;
    password|notes)
        print_info "Using Bitwarden field: $BW_FIELD"
        ;;
    *)
        # Treat as a custom field name; verify it exists on the item.
        if [ "$(printf '%s' "$ITEM_JSON" | jq -r --arg f "$BW_FIELD" '[.fields[]? | select(.name == $f)] | length')" != "1" ]; then
            die "Custom field '$BW_FIELD' not found (or not unique) on Bitwarden item $BW_ITEM."
        fi
        print_info "Using custom Bitwarden field: $BW_FIELD"
        ;;
esac
print_status "Bitwarden item and field resolved"
fi  # ! DRY_RUN
echo

# ─────────────────────────────────────────────────────────────────────────────
# Confirmation — explicit yes required before any mutation
# ─────────────────────────────────────────────────────────────────────────────
if $DRY_RUN; then
    print_warning "DRY RUN — exercises the rekey + verify cycle on a throwaway COPY only."
    echo "  1. Copy $VAULT_FILE and $LIVE_PASS_FILE into a tmpfs workspace."
    echo "  2. Generate a new 32-char passphrase locally (no bw)."
    echo "  3. Re-encrypt the COPY from OLD to NEW and verify NEW decrypts it."
    echo "  Skipped: Bitwarden publish, chezmoi apply, live-file verify."
    print_info "The real vault, Bitwarden, and $LIVE_PASS_FILE are never touched."
    echo
else
    echo "This will rotate the Ansible Vault passphrase. Steps:"
    echo "  1. Generate a new 32-char passphrase (bw generate)."
    echo "  2. Back up $VAULT_FILE to ~/.ansible/vault.yml.bak.<timestamp> (outside the repo)."
    echo "  3. Re-encrypt $VAULT_FILE from the OLD to the NEW passphrase (local)."
    echo "  4. Verify the NEW passphrase decrypts the vault."
    echo "  5. Publish the NEW passphrase to Bitwarden item '$BW_ITEM' (field: $BW_FIELD)."
    echo "  6. Run 'chezmoi apply $LIVE_PASS_FILE' to regenerate just that file (no other scripts)."
    echo "  7. Verify end-to-end via the live password file."
    echo
    print_warning "Bitwarden is mutated LAST, only after the local rekey verifies."
    print_warning "No passphrase (old or new) will be printed."
    echo
    read -r -p "Proceed with rotation? Type 'yes' to continue: " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        print_info "Aborted by user. Nothing changed."
        exit 0
    fi
    echo
fi

# ─────────────────────────────────────────────────────────────────────────────
# Workspace (create only after confirmation)
# ─────────────────────────────────────────────────────────────────────────────
WORKDIR="$(mktemp -d -p /dev/shm rotate-vault.XXXXXX)" || die "Failed to create tmpfs workspace in /dev/shm"
chmod 700 "$WORKDIR"
NEW="$WORKDIR/new-passphrase"

# Dry run operates on throwaway copies so the rekey can never touch the real vault/pass file.
# Repoint the path vars at the copies; every step below then works on them transparently.
if $DRY_RUN; then
    (umask 077 && cp "$VAULT_FILE" "$WORKDIR/test-vault.yml" && cp "$LIVE_PASS_FILE" "$WORKDIR/test-old-pass") \
        || die "Failed to stage dry-run copies in the tmpfs workspace"
    VAULT_FILE="$WORKDIR/test-vault.yml"
    LIVE_PASS_FILE="$WORKDIR/test-old-pass"
    print_status "Staged throwaway copies of the vault and pass file (tmpfs)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Generate the new passphrase
# ─────────────────────────────────────────────────────────────────────────────
echo "Step 2: Generating new passphrase..."
echo "─────────────────────────────────────────"
# Capture directly into the tmpfs file; create mode-600 first so it is never briefly readable.
(umask 077 && : > "$NEW")
chmod 600 "$NEW"
if $DRY_RUN; then
    # Local generation — no bw session. Read a fixed 512 random bytes (no SIGPIPE on the
    # source), filter to the charset, take 32. 512 bytes yields ~130 in-charset chars on
    # average, so falling short of 32 is astronomically unlikely.
    LC_ALL=C tr -dc 'A-Za-z0-9!@#%*_-' < <(head -c 512 /dev/urandom) | cut -c1-32 > "$NEW" \
        || die "local passphrase generation failed"
else
    bw generate -ulns --length 32 > "$NEW" || die "bw generate failed"
fi
if [ ! -s "$NEW" ]; then
    die "Generated passphrase file is empty"
fi
# Guard against a short passphrase (e.g. a truncated random draw), not just an empty one.
# rtrimstr on the trailing newline both generators append; expect exactly 32 chars.
if [ "$(tr -d '\n' < "$NEW" | wc -c)" -ne 32 ]; then
    die "Generated passphrase is not 32 characters — refusing to proceed"
fi
print_status "New passphrase generated (not shown)"
echo

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Back up vault.yml OUTSIDE the repo
# ─────────────────────────────────────────────────────────────────────────────
echo "Step 3: Backing up vault.yml..."
echo "─────────────────────────────────────────"
# Kept outside the working tree so it can never be swept into a commit. Note: .gitignore's
# '*.bak' glob does NOT match 'vault.yml.bak.<ts>', which is another reason to keep it out.
# Dry run keeps the backup inside the tmpfs workspace so it does not litter ~/.ansible.
if $DRY_RUN; then
    BACKUP="$WORKDIR/test-vault.bak"
else
    BACKUP="$HOME/.ansible/vault.yml.bak.$(date +%Y%m%d-%H%M%S)"
fi
(umask 077 && cp "$VAULT_FILE" "$BACKUP") || die "Failed to back up vault.yml"
chmod 600 "$BACKUP"
print_status "Backed up to $BACKUP (mode 600, old-passphrase ciphertext)"
echo

# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Rekey locally (OLD -> NEW)
# ─────────────────────────────────────────────────────────────────────────────
echo "Step 4: Re-encrypting vault.yml (this may take a minute)..."
echo "─────────────────────────────────────────"
# From here on, any failure must restore vault.yml to OLD before the trap fires.
if uv run --locked ansible-vault rekey \
        --vault-password-file="$LIVE_PASS_FILE" \
        --new-vault-password-file="$NEW" \
        "$VAULT_FILE"; then
    REKEYED=true
    print_status "vault.yml re-encrypted with the new passphrase"
else
    die "ansible-vault rekey failed — vault.yml unchanged"
fi
echo

# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Verify the NEW passphrase decrypts the vault
# ─────────────────────────────────────────────────────────────────────────────
echo "Step 5: Verifying new passphrase decrypts vault..."
echo "─────────────────────────────────────────"
if uv run --locked ansible-vault view \
        --vault-password-file="$NEW" \
        "$VAULT_FILE" > /dev/null 2>&1; then
    print_status "New passphrase decrypts vault.yml"
else
    die "New passphrase failed to decrypt vault.yml — Bitwarden untouched"
fi
echo

# Dry run ends here: the OLD->NEW rekey + verify cycle succeeded on the throwaway copy.
if $DRY_RUN; then
    ROTATION_COMPLETE=true  # nothing real to recover; the trap shreds the tmpfs workspace
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  Dry Run Complete — rekey + verify cycle OK                ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo
    print_info "Ran on throwaway copies. Real vault, Bitwarden, and live pass file untouched."
    print_warning "Not exercised: Bitwarden publish and 'chezmoi apply' (need the real item)."
    print_info "For the real rotation, drop --dry-run and unlock bw first:"
    echo "  export BW_SESSION=\$(bw unlock --raw)"
    echo "  BW_ITEM='dotfiles/ansible-vault-pass' BW_FIELD=notes ./rotate-vault-passphrase.sh"
    exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Re-check session, then publish to Bitwarden
# ─────────────────────────────────────────────────────────────────────────────
echo "Step 6: Publishing new passphrase to Bitwarden..."
echo "─────────────────────────────────────────"
# The rekey can take minutes; the session may have timed out. Re-check before mutating.
# Locked here is still fully recoverable (vault.yml gets restored to OLD).
if [ "$(bw status 2>/dev/null | jq -r '.status')" != "unlocked" ]; then
    die "Bitwarden session locked before publish. Re-unlock (export BW_SESSION=\$(bw unlock --raw)) and rerun the whole script."
fi

# Re-fetch the item immediately before edit (fresh revision; avoids clobbering).
ITEM_JSON="$(bw get item "$BW_ITEM" 2>/dev/null)" || die "Bitwarden item not found at publish time: $BW_ITEM"

# `bw get item` resolves a name/search term, but `bw edit item` requires the object id (GUID).
# Passing a name to `bw edit` returns "Not found." — so resolve the real id from the JSON.
BW_ITEM_ID="$(printf '%s' "$ITEM_JSON" | jq -r '.id // empty')"
[ -n "$BW_ITEM_ID" ] || die "Could not resolve the Bitwarden item id for '$BW_ITEM'."

# Build the jq filter that writes the NEW passphrase into the resolved field. The secret is
# passed via --rawfile (read from the tmpfs file), never --arg or string interpolation, so
# it never appears in this process's argv (/proc/<pid>/cmdline). rtrimstr strips the single
# trailing newline `bw generate` appends.
# shellcheck disable=SC2016  # $pass/$fname are jq variables (from --rawfile/--arg), not shell
case "$BW_FIELD" in
    password)
        JQ_FILTER='.login.password = ($pass | rtrimstr("\n"))'
        ;;
    notes)
        JQ_FILTER='.notes = ($pass | rtrimstr("\n"))'
        ;;
    *)
        JQ_FILTER='(.fields[] | select(.name == $fname)).value = ($pass | rtrimstr("\n"))'
        ;;
esac

# Pipe item JSON -> jq (inject secret) -> bw encode -> bw edit item. No `bw sync`: `bw edit`
# updates the local cache that chezmoi's `bw get` reads.
if printf '%s' "$ITEM_JSON" \
        | jq --rawfile pass "$NEW" --arg fname "$BW_FIELD" "$JQ_FILTER" \
        | bw encode \
        | bw edit item "$BW_ITEM_ID" > /dev/null; then
    print_status "Bitwarden item updated (field: $BW_FIELD)"
else
    die "Failed to publish to Bitwarden. vault.yml restored to OLD; Bitwarden edit did not complete."
fi
echo

# ─────────────────────────────────────────────────────────────────────────────
# Step 7: chezmoi apply — regenerate the live password file
# ─────────────────────────────────────────────────────────────────────────────
echo "Step 7: Regenerating live password file via chezmoi apply..."
echo "─────────────────────────────────────────"
# From here on the live pass file may be NEW, so recovery rolls FORWARD to NEW/NEW (see
# recover()): vault.yml is verified-NEW and Bitwarden holds NEW, so on any failure we make
# the live file NEW rather than stranding vault.yml on an OLD backup we can no longer decrypt.
#
# Apply ONLY the live pass file's target, not the whole tree. A bare `chezmoi apply` would
# also run every unrelated run_ script (package/tool installs, etc.) as a side effect of
# rotating a passphrase — scoping to the single path regenerates just this file and runs none.
LIVE_MAY_BE_NEW=true
if ! chezmoi apply "$LIVE_PASS_FILE"; then
    # recover() forces the live file to NEW from the tmpfs copy — no manual step needed in
    # the common case. If that write also fails, recover() prints the manual chezmoi path.
    die "chezmoi apply failed. Attempting forward recovery to the NEW passphrase."
fi
print_status "chezmoi apply completed (live pass file only)"
echo

# ─────────────────────────────────────────────────────────────────────────────
# Step 8: End-to-end verify via the LIVE password file (authoritative check)
# ─────────────────────────────────────────────────────────────────────────────
echo "Step 8: Verifying end-to-end via live password file..."
echo "─────────────────────────────────────────"
# No override flags: uses ansible.cfg's vault_password_file = ~/.ansible/vault-pass.
# This is the single source of truth that rotation succeeded. No checksum comparison.
if uv run --locked ansible-vault view "$VAULT_FILE" > /dev/null 2>&1; then
    ROTATION_COMPLETE=true
    print_status "Live password file decrypts vault.yml — rotation verified"
else
    die "End-to-end verification failed: live password file cannot decrypt vault.yml. Forcing the live file to the NEW passphrase; if this persists, the chezmoi template may read a different Bitwarden field than the one written (see BW_FIELD)."
fi
echo

# ─────────────────────────────────────────────────────────────────────────────
# Step 9: Report (cleanup runs via the trap)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Passphrase Rotation Complete!                             ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo
print_warning "Backup retained at: $BACKUP"
print_info "It holds vault.yml ciphertext under the OLD passphrase. Delete it once satisfied:"
echo "  shred -u '$BACKUP'"
echo
