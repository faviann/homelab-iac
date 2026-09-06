#!/bin/bash
# Transactional, non-disclosing vault operations.

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVOCATION_DIR="$PWD"
cd "$PROJECT_ROOT" || exit 1
VAULT_FILE="$PROJECT_ROOT/inventory/group_vars/all/vault.yml"
PASS_FILE="${ANSIBLE_VAULT_PASSWORD_FILE:-$HOME/.ansible/vault-pass}"
TRANSACTION_WORKSPACE=""
TRANSACTION_PUBLISH_TMP=""

usage() {
    cat <<'EOF'
Usage: ./vault.sh <operation>

Operations:
  configure  Create or update Proxmox API credentials
  edit       Edit the complete encrypted vault
  check      Verify the vault without disclosing its contents
  set        Transfer a UTF-8 text file into a top-level vault variable:
               set <key> --from-file <path> --create|--replace
                   [--strip-final-newline]
  rotate     Rotate the vault passphrase (interactive):
               rotate [--dry-run]
EOF
}

check_line() {
    local name="$1"
    local result="$2"
    printf '%s: %s\n' "$name" "$result"
    [[ "$result" == PASS ]] || CHECK_FAILED=1
}

report_content_failures() {
    check_line "YAML mapping" FAIL
    check_line "vault_proxmox_api_user" FAIL
    check_line "vault_proxmox_api_token_id" FAIL
    check_line "vault_proxmox_api_token_secret" FAIL
}

vault_file_is_encrypted() {
    local first_line
    [[ -f "$VAULT_FILE" ]] \
        && IFS= read -r first_line <"$VAULT_FILE" \
        && [[ "$first_line" =~ ^\$ANSIBLE_VAULT\;1\.[12]\;AES256($|\;) ]]
}

check_vault() {
    local workspace plaintext content_checks mode owner
    CHECK_FAILED=0

    if vault_file_is_encrypted; then
        check_line "vault header" PASS
    else
        check_line "vault header" FAIL
    fi

    if [[ -f "$PASS_FILE" ]]; then
        check_line "passphrase file" PASS
    else
        check_line "passphrase file" FAIL
    fi
    if [[ -s "$PASS_FILE" ]]; then
        check_line "passphrase nonempty" PASS
    else
        check_line "passphrase nonempty" FAIL
    fi
    owner="$(stat -c %u -- "$PASS_FILE" 2>/dev/null || true)"
    if [[ -n "$owner" && "$owner" == "$(id -u)" ]]; then
        check_line "passphrase ownership" PASS
    else
        check_line "passphrase ownership" FAIL
    fi
    mode="$(stat -c %a -- "$PASS_FILE" 2>/dev/null || true)"
    if [[ -n "$mode" ]] && (( (8#$mode & 077) == 0 )); then
        check_line "passphrase permissions" PASS
    else
        check_line "passphrase permissions" FAIL
    fi

    workspace="$(mktemp -d /dev/shm/homelab-vault.XXXXXX)" || {
        check_line "decryptability" FAIL
        report_content_failures
        return 1
    }
    arm_transaction_cleanup "$workspace"
    chmod 700 "$workspace"
    plaintext="$workspace/vault.yml"
    if uv run --locked ansible-vault view "$VAULT_FILE" >"$plaintext" 2>/dev/null; then
        check_line "decryptability" PASS
        content_checks="$workspace/checks"
        if uv run --locked python - "$plaintext" >"$content_checks" 2>/dev/null <<'PY'
import sys
from pathlib import Path

import yaml

try:
    value = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, yaml.YAMLError):
    value = None

is_mapping = isinstance(value, dict)
print(f"YAML mapping|{'PASS' if is_mapping else 'FAIL'}")
for key in (
    "vault_proxmox_api_user",
    "vault_proxmox_api_token_id",
    "vault_proxmox_api_token_secret",
):
    item = value.get(key) if is_mapping else None
    classification = item.strip() if isinstance(item, str) else None
    valid = (
        isinstance(item, str)
        and bool(item.strip())
        and classification not in ("REPLACE_ME", "<REPLACE_ME>")
        and not classification.startswith("REPLACE_WITH_")
    )
    print(f"{key}|{'PASS' if valid else 'FAIL'}")
PY
        then
            while IFS='|' read -r name result; do
                check_line "$name" "$result"
            done <"$content_checks"
        else
            report_content_failures
        fi
    else
        check_line "decryptability" FAIL
        report_content_failures
    fi
    local status=0
    (( CHECK_FAILED == 0 )) || status=1
    cleanup_transaction || status=1
    disarm_transaction_cleanup
    return "$status"
}

open_tty() {
    [[ -t 0 && -t 1 ]] || return 1
    exec 3<>/dev/tty
}

confirm_plaintext_conversion() {
    local answer
    printf 'Vault is unencrypted. Encrypt and replace it? [y/N] ' >&3
    IFS= read -r answer <&3 || return 1
    [[ "$answer" == y || "$answer" == Y || "$answer" == yes || "$answer" == YES ]]
}

required_credential_valid() {
    local value="$1"
    local classification
    classification="${value#"${value%%[![:space:]]*}"}"
    classification="${classification%"${classification##*[![:space:]]}"}"
    [[ "$value" =~ [^[:space:]] ]] \
        && [[ "$classification" != "REPLACE_ME" ]] \
        && [[ "$classification" != "<REPLACE_ME>" ]] \
        && [[ "$classification" != REPLACE_WITH_* ]]
}

stage_existing_vault() {
    local plaintext="$1"
    if [[ ! -e "$VAULT_FILE" ]]; then
        printf '%s\n' '---' >"$plaintext"
    elif IFS= read -r first_line <"$VAULT_FILE" \
        && [[ "$first_line" == '$ANSIBLE_VAULT;'* ]]; then
        if ! uv run --locked ansible-vault decrypt \
            --output "$plaintext" "$VAULT_FILE" >/dev/null 2>&1; then
            return 1
        fi
    else
        confirm_plaintext_conversion || return 1
        cp -- "$VAULT_FILE" "$plaintext"
    fi
    chmod 600 "$plaintext"
}

cleanup_transaction() {
    local target="$TRANSACTION_WORKSPACE"
    local status=0
    [[ -n "$target" ]] || return 0
    [[ "$(dirname "$target")" == /dev/shm \
        && "$(basename "$target")" == homelab-vault.* ]] || return 1
    rm -rf -- "$target" || status=1
    if [[ ! -e "$target" ]]; then
        TRANSACTION_WORKSPACE=""
    else
        status=1
    fi
    return "$status"
}

discard_pending_ciphertext() {
    local target="$TRANSACTION_PUBLISH_TMP"
    local status=0
    [[ -n "$target" ]] || return 0
    [[ "$(dirname "$target")" == "$(dirname "$VAULT_FILE")" \
        && "$(basename "$target")" == vault.yml.tmp.* ]] || return 1
    rm -f -- "$target" || status=1
    if [[ ! -e "$target" ]]; then
        TRANSACTION_PUBLISH_TMP=""
    else
        status=1
    fi
    return "$status"
}

disarm_transaction_cleanup() {
    if [[ -z "$TRANSACTION_WORKSPACE" && -z "$TRANSACTION_PUBLISH_TMP" ]]; then
        trap - EXIT HUP INT TERM
    fi
}

cleanup_transaction_on_exit() {
    local status=$?
    trap - EXIT HUP INT TERM
    rotation_recover
    cleanup_transaction || status=1
    discard_pending_ciphertext || status=1
    exit "$status"
}

interrupt_transaction() {
    exit 1
}

arm_transaction_cleanup() {
    TRANSACTION_WORKSPACE="$1"
    TRANSACTION_PUBLISH_TMP=""
    trap cleanup_transaction_on_exit EXIT
    trap interrupt_transaction HUP INT TERM
}

validate_plaintext() {
    uv run --locked python - "$1" >/dev/null 2>&1 <<'PY'
import sys
from pathlib import Path

import yaml

try:
    value = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, yaml.YAMLError):
    raise SystemExit(1)
raise SystemExit(0 if isinstance(value, dict) else 1)
PY
}

stage_ciphertext_for_publication() {
    local plaintext="$1"
    local encrypted="$2"

    validate_plaintext "$plaintext" || return 1
    cp -- "$plaintext" "$encrypted" || return 1
    chmod 600 "$encrypted"
    uv run --locked ansible-vault encrypt "$encrypted" >/dev/null 2>&1 || return 1
    uv run --locked ansible-vault view "$encrypted" >/dev/null 2>&1 || return 1

    mkdir -p "$(dirname "$VAULT_FILE")"
    TRANSACTION_PUBLISH_TMP="$(mktemp "${VAULT_FILE}.tmp.XXXXXX")" || return 1
    if ! install -m 600 -- "$encrypted" "$TRANSACTION_PUBLISH_TMP"; then
        discard_pending_ciphertext || true
        return 1
    fi
}

transfer_source_into_plaintext() {
    local workspace="$1"
    local plaintext="$2"
    local value_file="$workspace/value"

    cp -- "$SET_SOURCE" "$value_file" || return 1
    chmod 600 "$value_file"
    uv run --locked python - \
        "$plaintext" "$value_file" "$SET_KEY" "$SET_MODE" "$SET_STRIP" \
        >/dev/null 2>&1 <<'PY'
import sys
from pathlib import Path

import yaml

vault_path = Path(sys.argv[1])
value_path = Path(sys.argv[2])
key, mode, strip = sys.argv[3], sys.argv[4], sys.argv[5]
try:
    document = yaml.safe_load(vault_path.read_text(encoding="utf-8"))
except yaml.YAMLError:
    raise SystemExit(1)
if document is None:
    document = {}
if not isinstance(document, dict):
    raise SystemExit(1)
if (key in document) != (mode == "replace"):
    raise SystemExit(1)
try:
    value = value_path.read_bytes().decode("utf-8")
except (OSError, UnicodeDecodeError):
    raise SystemExit(1)
if strip == "1":
    value = value.removesuffix("\n")
document[key] = value
vault_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
PY
}

run_mutation() {
    local operation="$1"
    local label="${2-$1}"
    local workspace plaintext encrypted credentials editor_command
    workspace="$(mktemp -d /dev/shm/homelab-vault.XXXXXX)" || return 1
    arm_transaction_cleanup "$workspace"
    chmod 700 "$workspace"
    plaintext="$workspace/vault.yml"
    encrypted="$workspace/vault.encrypted"

    if ! stage_existing_vault "$plaintext"; then
        cleanup_transaction || true
        return 1
    fi

    if [[ "$operation" == configure ]]; then
        local api_user token_id token_secret
        printf 'Proxmox API user: ' >&3
        IFS= read -r api_user <&3 || { cleanup_transaction || true; return 1; }
        printf 'Proxmox API token ID: ' >&3
        IFS= read -r token_id <&3 || { cleanup_transaction || true; return 1; }
        printf 'Proxmox API token secret: ' >&3
        IFS= read -rs token_secret <&3 || { cleanup_transaction || true; return 1; }
        printf '\n' >&3
        if ! required_credential_valid "$api_user" \
            || ! required_credential_valid "$token_id" \
            || ! required_credential_valid "$token_secret"; then
            cleanup_transaction || true
            return 1
        fi
        credentials="$workspace/credentials"
        printf '%s\n%s\n%s\n' "$api_user" "$token_id" "$token_secret" >"$credentials"
        chmod 600 "$credentials"
        unset api_user token_id token_secret
        if ! uv run --locked python - "$plaintext" "$credentials" >/dev/null 2>&1 <<'PY'
import sys
from pathlib import Path

import yaml

vault_path = Path(sys.argv[1])
credentials = Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
try:
    value = yaml.safe_load(vault_path.read_text(encoding="utf-8"))
except yaml.YAMLError:
    raise SystemExit(1)
if value is None:
    value = {}
if not isinstance(value, dict) or len(credentials) != 3:
    raise SystemExit(1)
for key, credential in zip(
    (
        "vault_proxmox_api_user",
        "vault_proxmox_api_token_id",
        "vault_proxmox_api_token_secret",
    ),
    credentials,
    strict=True,
):
    value[key] = credential
vault_path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
PY
        then
            cleanup_transaction || true
            return 1
        fi
    elif [[ "$operation" == set ]]; then
        if ! transfer_source_into_plaintext "$workspace" "$plaintext"; then
            cleanup_transaction || true
            printf '%s: FAIL\n' "$label" >&2
            return 1
        fi
    else
        editor_command="${VISUAL:-${EDITOR:-vi}}"
        local -a editor_argv
        read -r -a editor_argv <<<"$editor_command"
        if (( ${#editor_argv[@]} == 0 )) || ! "${editor_argv[@]}" "$plaintext"; then
            cleanup_transaction || true
            return 1
        fi
    fi

    if stage_ciphertext_for_publication "$plaintext" "$encrypted"; then
        if ! cleanup_transaction; then
            discard_pending_ciphertext || true
            return 1
        fi
        trap '' HUP INT TERM
        if mv -f -- "$TRANSACTION_PUBLISH_TMP" "$VAULT_FILE"; then
            TRANSACTION_PUBLISH_TMP=""
            disarm_transaction_cleanup
            printf '%s: PASS\n' "$label"
            return 0
        fi
        trap interrupt_transaction HUP INT TERM
        discard_pending_ciphertext || true
        disarm_transaction_cleanup
    else
        cleanup_transaction || true
        discard_pending_ciphertext || true
        disarm_transaction_cleanup
    fi
    printf '%s: FAIL\n' "$label" >&2
    return 1
}

ROTATION_STATE=""
ROTATION_REHEARSAL=0
ROTATION_BACKUP=""
ROTATION_NEW_PASSPHRASE=""

rotation_fail() {
    printf 'rotate: FAIL (%s)\n' "$1" >&2
    return 1
}

rotation_step() {
    printf '%s: PASS\n' "$1"
}

# vault.yml is only ever consistent as OLD/OLD or NEW/NEW. Which way we recover
# depends on whether the live passphrase file may already hold NEW.
#   rekeyed          -> the live file is still OLD, so roll BACK to the OLD ciphertext.
#   live-may-be-new  -> Bitwarden already holds NEW and OLD survives nowhere, so
#                       roll FORWARD by forcing the live file to NEW.
# Runs from the exit trap, before the workspace holding the only NEW copy is removed.
rotation_recover() {
    local state="$ROTATION_STATE"
    local subject="the vault"
    ROTATION_STATE=""
    (( ROTATION_REHEARSAL == 0 )) || subject="the rehearsal copy"
    case "$state" in
        rekeyed)
            if [[ -f "$ROTATION_BACKUP" ]] \
                && cp -f -- "$ROTATION_BACKUP" "$VAULT_FILE"; then
                printf 'rotate: recovered (%s restored to the old passphrase)\n' \
                    "$subject" >&2
            else
                printf 'rotate: CRITICAL (restore %s from %s by hand)\n' \
                    "$VAULT_FILE" "$ROTATION_BACKUP" >&2
            fi
            ;;
        live-may-be-new)
            if [[ -f "$ROTATION_NEW_PASSPHRASE" ]] \
                && cp -f -- "$ROTATION_NEW_PASSPHRASE" "$PASS_FILE" \
                && chmod 600 "$PASS_FILE"; then
                printf 'rotate: recovered (live passphrase file rolled forward)\n' >&2
            else
                printf 'rotate: CRITICAL (run chezmoi apply %s, then verify)\n' \
                    "$PASS_FILE" >&2
            fi
            ;;
    esac
    return 0
}

rotation_preflight() {
    local dry_run="$1"
    local required requirement status
    required="uv"
    [[ "$dry_run" == 1 ]] || required="bw jq chezmoi uv"
    for requirement in $required; do
        command -v "$requirement" >/dev/null 2>&1 || {
            rotation_fail "required command not found: $requirement"
            return 1
        }
    done
    [[ -s "$PASS_FILE" ]] || {
        rotation_fail "live passphrase file missing or empty: $PASS_FILE"
        return 1
    }
    # A real rotation publishes through Bitwarden and chezmoi, which regenerate
    # the standard path that ansible.cfg names. Rotating a passphrase file the
    # fleet does not read would report success while that standard file stays
    # OLD, so refuse before anything mutates. A rehearsal repoints internally.
    [[ "$dry_run" == 1 || "$PASS_FILE" == "$HOME/.ansible/vault-pass" ]] || {
        rotation_fail \
            "rotate requires the standard live passphrase file, not $PASS_FILE"
        return 1
    }
    vault_file_is_encrypted || {
        rotation_fail "vault file missing or not encrypted: $VAULT_FILE"
        return 1
    }
    [[ "$dry_run" == 1 ]] && return 0
    # The script never handles the master password: on a locked vault it delegates
    # to `bw unlock`, which prompts on the tty and returns only a session token.
    status="$(bw status 2>/dev/null | jq -r '.status')"
    if [[ "$status" == locked ]]; then
        BW_SESSION="$(bw unlock --raw)" || {
            rotation_fail "bitwarden unlock failed"
            return 1
        }
        export BW_SESSION
        status="$(bw status 2>/dev/null | jq -r '.status')"
    fi
    [[ "$status" == unlocked ]] || {
        rotation_fail "bitwarden is not unlocked (status: $status)"
        return 1
    }
}

# Generates into a mode-600 tmpfs file; the passphrase is never echoed or passed
# as a process argument.
generate_new_passphrase() {
    local dry_run="$1"
    (umask 077 && : >"$ROTATION_NEW_PASSPHRASE") || return 1
    chmod 600 "$ROTATION_NEW_PASSPHRASE"
    if [[ "$dry_run" == 1 ]]; then
        LC_ALL=C tr -dc 'A-Za-z0-9!@#%*_-' < <(head -c 512 /dev/urandom) \
            | cut -c1-32 >"$ROTATION_NEW_PASSPHRASE" || return 1
    else
        bw generate -ulns --length 32 >"$ROTATION_NEW_PASSPHRASE" || return 1
    fi
    [[ -s "$ROTATION_NEW_PASSPHRASE" ]] || return 1
    (( $(tr -d '\n' <"$ROTATION_NEW_PASSPHRASE" | wc -c) == 32 ))
}

publish_to_bitwarden() {
    # The chezmoi template that regenerates the live passphrase file reads the
    # notes of this item, so rotation publishes to exactly that item and field.
    local item="dotfiles/ansible-vault-pass"
    local item_json item_id
    # The rekey can take minutes; the session may have timed out since preflight.
    [[ "$(bw status 2>/dev/null | jq -r '.status')" == unlocked ]] || return 1
    item_json="$(bw get item "$item" 2>/dev/null)" || return 1
    # `bw get item` resolves a name, but `bw edit item` requires the object id.
    item_id="$(printf '%s' "$item_json" | jq -r '.id // empty')"
    [[ -n "$item_id" ]] || return 1
    # The secret reaches jq through --rawfile, never argv.
    printf '%s' "$item_json" \
        | jq --rawfile pass "$ROTATION_NEW_PASSPHRASE" \
            '.notes = ($pass | rtrimstr("\n"))' \
        | bw encode \
        | bw edit item "$item_id" >/dev/null 2>&1
}

rotate_passphrase() {
    local dry_run="$1"
    local workspace answer

    ROTATION_REHEARSAL="$dry_run"
    rotation_preflight "$dry_run" || return 1

    if [[ "$dry_run" == 0 ]]; then
        printf "Rotate the vault passphrase? Type 'yes' to continue: " >&3
        IFS= read -r answer <&3 || answer=""
        if [[ "$answer" != yes ]]; then
            printf 'rotate: ABORTED (nothing changed)\n'
            return 0
        fi
    fi

    workspace="$(mktemp -d /dev/shm/homelab-vault.XXXXXX)" || {
        rotation_fail "could not create the tmpfs workspace"
        return 1
    }
    arm_transaction_cleanup "$workspace"
    chmod 700 "$workspace"
    ROTATION_NEW_PASSPHRASE="$workspace/new-passphrase"

    # A rehearsal repoints both paths at throwaway copies, so every step below
    # runs exactly as it would for real without touching real state.
    if [[ "$dry_run" == 1 ]]; then
        (umask 077 && cp -- "$VAULT_FILE" "$workspace/vault.yml" \
            && cp -- "$PASS_FILE" "$workspace/old-passphrase") || {
            rotation_fail "could not stage the rehearsal copies"
            return 1
        }
        VAULT_FILE="$workspace/vault.yml"
        PASS_FILE="$workspace/old-passphrase"
        ROTATION_BACKUP="$workspace/vault.yml.bak"
    else
        ROTATION_BACKUP="$HOME/.ansible/vault.yml.bak.$(date +%Y%m%d-%H%M%S)"
    fi

    generate_new_passphrase "$dry_run" || {
        rotation_fail "could not generate a 32-character passphrase"
        return 1
    }
    rotation_step "new passphrase"

    # Kept outside the working tree so it can never be swept into a commit.
    (umask 077 && cp -- "$VAULT_FILE" "$ROTATION_BACKUP") || {
        rotation_fail "could not back up the vault ciphertext"
        return 1
    }
    chmod 600 "$ROTATION_BACKUP"
    rotation_step "ciphertext backup"

    # Rekey locally and verify BEFORE publishing: Bitwarden is what the chezmoi
    # template reads, so mutating it first would leave the live passphrase NEW
    # while the vault is still OLD.
    uv run --locked ansible-vault rekey \
        --vault-password-file="$PASS_FILE" \
        --new-vault-password-file="$ROTATION_NEW_PASSPHRASE" \
        "$VAULT_FILE" >/dev/null 2>&1 || {
        rotation_fail "ansible-vault rekey failed (vault unchanged)"
        return 1
    }
    ROTATION_STATE="rekeyed"
    rotation_step "rekey"

    uv run --locked ansible-vault view \
        --vault-password-file="$ROTATION_NEW_PASSPHRASE" \
        "$VAULT_FILE" >/dev/null 2>&1 || {
        rotation_fail "the new passphrase does not decrypt the vault"
        return 1
    }
    rotation_step "new passphrase decrypts the vault"

    if [[ "$dry_run" == 1 ]]; then
        ROTATION_STATE=""
        printf 'rotate --dry-run: PASS\n'
        return 0
    fi

    publish_to_bitwarden || {
        rotation_fail "could not publish the new passphrase to bitwarden"
        return 1
    }
    rotation_step "bitwarden publish"

    # Apply ONLY the live passphrase file's target: a bare `chezmoi apply` would
    # also run every unrelated run_ script as a side effect of a rotation.
    ROTATION_STATE="live-may-be-new"
    chezmoi apply "$PASS_FILE" >/dev/null 2>&1 || {
        rotation_fail "chezmoi apply failed"
        return 1
    }
    rotation_step "chezmoi apply"

    # Authoritative check: no password-file flag, so this resolves the live
    # passphrase file the way a fleet run does. Preflight already refused any
    # non-standard ANSIBLE_VAULT_PASSWORD_FILE, so that is the file ansible.cfg
    # names.
    uv run --locked ansible-vault view "$VAULT_FILE" >/dev/null 2>&1 || {
        rotation_fail "the live passphrase file cannot decrypt the vault"
        return 1
    }
    ROTATION_STATE=""
    rotation_step "live passphrase decrypts the vault"

    printf 'rotate: PASS\n'
    printf 'Backup of the old ciphertext retained at %s\n' "$ROTATION_BACKUP"
    return 0
}

source_file_authorized() {
    local path="$1"
    local owner mode
    [[ ! -L "$path" && -f "$path" ]] || return 1
    [[ ! "$path" -ef "$VAULT_FILE" ]] || return 1
    owner="$(stat -c %u -- "$path" 2>/dev/null || true)"
    [[ -n "$owner" && "$owner" == "$(id -u)" ]] || return 1
    mode="$(stat -c %a -- "$path" 2>/dev/null || true)"
    [[ -n "$mode" ]] && (( (8#$mode & 077) == 0 ))
}

parse_set_arguments() {
    SET_KEY=""
    SET_SOURCE=""
    SET_MODE=""
    SET_STRIP=0
    (( $# >= 1 )) && [[ -n "$1" && "$1" != -* ]] || return 1
    SET_KEY="$1"
    shift
    while (( $# > 0 )); do
        case "$1" in
            --from-file)
                (( $# >= 2 )) && [[ -n "$2" ]] || return 1
                SET_SOURCE="$2"
                [[ "$SET_SOURCE" == /* ]] || SET_SOURCE="$INVOCATION_DIR/$SET_SOURCE"
                shift 2
                ;;
            --strip-final-newline)
                SET_STRIP=1
                shift
                ;;
            --create|--replace)
                [[ -z "$SET_MODE" ]] || return 1
                SET_MODE="${1#--}"
                shift
                ;;
            *)
                return 1
                ;;
        esac
    done
    [[ -n "$SET_SOURCE" && -n "$SET_MODE" ]]
}

if (( $# == 0 )); then
    usage >&2
    exit 2
fi

case "$1" in
    --help|-h)
        (( $# == 1 )) || exit 2
        usage
        exit 0
        ;;
    check)
        (( $# == 1 )) || exit 2
        check_vault
        exit $?
        ;;
    set)
        shift
        if ! parse_set_arguments "$@"; then
            usage >&2
            exit 2
        fi
        if ! source_file_authorized "$SET_SOURCE"; then
            printf 'set %s: FAIL\n' "$SET_KEY" >&2
            exit 1
        fi
        # fd 3 is the prompt channel the interactive operations open on a tty.
        # A transfer is non-interactive, so it reads EOF and declines instead
        # of prompting to convert an unencrypted vault.
        exec 3<>/dev/null
        run_mutation set "set $SET_KEY"
        exit $?
        ;;
    rotate)
        shift
        ROTATE_DRY_RUN=0
        while (( $# > 0 )); do
            case "$1" in
                --dry-run)
                    (( ROTATE_DRY_RUN == 0 )) || { usage >&2; exit 2; }
                    ROTATE_DRY_RUN=1
                    shift
                    ;;
                *)
                    usage >&2
                    exit 2
                    ;;
            esac
        done
        if (( ROTATE_DRY_RUN == 0 )); then
            open_tty || {
                printf 'rotate: FAIL\n' >&2
                exit 1
            }
        fi
        rotate_passphrase "$ROTATE_DRY_RUN"
        exit $?
        ;;
    configure|edit)
        (( $# == 1 )) || exit 2
        open_tty || {
            printf '%s: FAIL\n' "$1" >&2
            exit 1
        }
        run_mutation "$1"
        exit $?
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
