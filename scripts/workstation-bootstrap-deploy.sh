#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${WORKSTATION_BOOTSTRAP_LOG_DIR:-$REPO_ROOT/.ansible/logs}"
LOG_PATH="${WORKSTATION_BOOTSTRAP_LOG:-$LOG_DIR/workstation-bootstrap.log}"
API_ITEM="${WORKSTATION_BW_API_ITEM:-dotfiles/workstation-bitwarden-api-key}"

cleanup() {
  unset BW_SESSION
  unset BW_PASSWORD
  unset WORKSTATION_BW_CLIENTID
  unset WORKSTATION_BW_CLIENTSECRET
  unset WORKSTATION_BW_PASSWORD
}
trap cleanup EXIT

fail() {
  printf 'workstation-bootstrap-deploy: %s\n' "$*" >&2
  exit 1
}

status_from_json() {
  python3 -c 'import json,sys; print(json.load(sys.stdin).get("status", ""))'
}

command -v bw >/dev/null 2>&1 || fail "bw CLI is required on the controller"
command -v uv >/dev/null 2>&1 || fail "uv is required on the controller"

install -d -m 0700 "$LOG_DIR"
test ! -L "$LOG_PATH" || fail "Refusing symlink log path: $LOG_PATH"
: > "$LOG_PATH"
chmod 0600 "$LOG_PATH"

read -rsp 'Bitwarden master password: ' BW_PASSWORD
printf '\n'

case "$BW_PASSWORD" in
  *$'\n'*) fail "Bitwarden password must not contain newlines" ;;
esac

status_json="$(bw status)"
status="$(printf '%s' "$status_json" | status_from_json)"

if [ "$status" = "unauthenticated" ] || [ -z "$status" ]; then
  fail "Controller Bitwarden CLI is not logged in. Run 'bw login' once on this controller."
fi

if [ "$status" = "locked" ]; then
  BW_SESSION="$(BW_PASSWORD="$BW_PASSWORD" bw unlock --passwordenv BW_PASSWORD --raw)"
  export BW_SESSION
fi

status_json="$(bw status)"
status="$(printf '%s' "$status_json" | status_from_json)"
test "$status" = "unlocked" || fail "Controller Bitwarden vault is not unlocked"

api_item_json="$(bw get item "$API_ITEM")" || fail "Missing Bitwarden item: $API_ITEM"

WORKSTATION_BW_CLIENTID="$(printf '%s' "$api_item_json" | python3 -c 'import json,sys; item=json.load(sys.stdin); print(next((field.get("value", "") for field in item.get("fields", []) if field.get("name") == "client_id"), ""))')"
WORKSTATION_BW_CLIENTSECRET="$(printf '%s' "$api_item_json" | python3 -c 'import json,sys; item=json.load(sys.stdin); print(next((field.get("value", "") for field in item.get("fields", []) if field.get("name") == "client_secret"), ""))')"
WORKSTATION_BW_PASSWORD="$BW_PASSWORD"

test -n "$WORKSTATION_BW_CLIENTID" || fail "client_id custom field missing in $API_ITEM"
test -n "$WORKSTATION_BW_CLIENTSECRET" || fail "client_secret custom field missing in $API_ITEM"

case "$WORKSTATION_BW_CLIENTID$WORKSTATION_BW_CLIENTSECRET$WORKSTATION_BW_PASSWORD" in
  *$'\n'*) fail "bootstrap values must not contain newlines" ;;
esac

export WORKSTATION_BW_CLIENTID WORKSTATION_BW_CLIENTSECRET WORKSTATION_BW_PASSWORD

cd "$REPO_ROOT"
printf 'Writing private deploy log to %s\n' "$LOG_PATH"
uv run --locked ansible-playbook site.yml --limit workstation -e workstation_bootstrap_unattended=true "$@" > "$LOG_PATH" 2>&1