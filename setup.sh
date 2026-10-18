#!/bin/bash
# Locked Python-environment synchronization and lock-file upgrades.

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$PROJECT_ROOT/scripts/lib/uv-prerequisite.sh"

usage() {
    cat <<'EOF'
Usage: ./setup.sh <operation>

Operations:
  sync       Synchronize the locked Python environment. Optional: every
             command that uses the environment reconciles it itself.
  upgrade    Upgrade the named packages in uv.lock to the newest versions
             pyproject.toml allows:
               upgrade <package>...

Options:
  --help     Show this help
EOF
}

usage_error() {
    echo "setup.sh: $1" >&2
    echo "Try './setup.sh --help' for usage." >&2
    exit 2
}

upgrades=()
case "${1-}" in
    --help | sync) (($# == 1)) || usage_error "$1 takes no arguments" ;;
    upgrade)
        (($# > 1)) || usage_error "upgrade needs at least one package name"
        for package in "${@:2}"; do
            [[ "$package" != -* ]] || usage_error "unknown option"
            upgrades+=(--upgrade-package "$package")
        done
        ;;
    "") usage_error "an operation is required" ;;
    -*) usage_error "unknown option" ;;
    *) usage_error "unknown operation" ;;
esac

if [[ "$1" == --help ]]; then
    usage
    exit 0
fi

require_uv || exit 1
cd "$PROJECT_ROOT" || exit 1
if [[ "$1" == sync ]]; then
    uv sync --locked || exit 1
else
    uv lock "${upgrades[@]}" || exit 1
fi
