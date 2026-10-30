#!/bin/bash
# Locked entry point for enrollment.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$PROJECT_ROOT/scripts/lib/live-execution.sh"

usage() {
    cat <<'EOF'
Usage: ./recover.sh <operation> [options]

Operations:
  proxmox-host-ssh             Enroll the fleet key on the Proxmox host
  ssh-keys [--limit <targets>]
                              Enroll the fleet key in existing LXCs

Options:
  --limit <targets>           Select hosts with Ansible limit grammar
  --help                      Show this help
EOF
}

usage_error() {
    echo "recover.sh: $1" >&2
    echo "Try './recover.sh --help' for usage." >&2
    exit 2
}

operation="${1:-}"
case "$operation" in
    --help)
        usage
        exit 0
        ;;
    "")
        usage_error "an operation is required"
        ;;
    ssh-keys)
        supports_limit=true
        playbook="playbooks/add-ssh-keys-to-lxcs.yml"
        lock_class="exclusive"
        shift
        ;;
    proxmox-host-ssh)
        # Enrollment runs before Proxmox trusts the fleet key the fleet lease needs.
        supports_limit=false
        playbook="playbooks/enroll-proxmox-host-ssh.yml"
        lock_class="exclusive-local"
        shift
        ;;
    *)
        usage_error "unknown operation"
        ;;
esac

limit_pattern=""
while (($#)); do
    case "$1" in
        --limit)
            $supports_limit || usage_error "--limit is not valid for this operation"
            (($# >= 2)) && [[ -n "$2" ]] && [[ "$2" != -* ]] || \
                usage_error "$1 requires a value"
            limit_pattern="$2"
            shift 2
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            usage_error "unknown option"
            ;;
    esac
done

arguments=()
if [[ "$operation" == "proxmox-host-ssh" ]]; then
    prerequisite_target_pattern="proxmox_api"
elif [[ -n "$limit_pattern" ]]; then
    arguments+=("--limit" "$limit_pattern")
    prerequisite_target_pattern="$limit_pattern"
else
    prerequisite_target_pattern="lxcs"
fi
arguments+=("-e" "prerequisite_target_pattern=$prerequisite_target_pattern")

run_live_playbook \
    "$lock_class" \
    "$playbook" \
    "${arguments[@]}"
