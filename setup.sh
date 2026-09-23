#!/bin/bash
# Optional locked Python-environment synchronization.

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$PROJECT_ROOT/scripts/lib/uv-prerequisite.sh"

usage() {
    cat <<'EOF'
Usage: ./setup.sh <operation>

Operations:
  sync       Synchronize the locked Python environment. Optional: every
             command that uses the environment reconciles it itself.

Options:
  --help     Show this help
EOF
}

usage_error() {
    echo "setup.sh: $1" >&2
    echo "Try './setup.sh --help' for usage." >&2
    exit 2
}

case "${1-}" in
    --help | sync) ;;
    "") usage_error "an operation is required" ;;
    -*) usage_error "unknown option" ;;
    *) usage_error "unknown operation" ;;
esac
(($# == 1)) || usage_error "$1 takes no arguments"

if [[ "$1" == --help ]]; then
    usage
    exit 0
fi

require_uv || exit 1
cd "$PROJECT_ROOT" || exit 1
uv sync --locked || exit 1
