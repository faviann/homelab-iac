#!/bin/bash
# Shared live-playbook execution boundary. Callers own their command grammar.

readonly LIVE_EXECUTION_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly LIVE_EXECUTION_LOCK_FILE="${HOME}/.ansible/homelab-iac-lifecycle.lock"
readonly LIVE_EXECUTION_HOLDER_DIR="${LIVE_EXECUTION_LOCK_FILE}.holders"
readonly LIVE_EXECUTION_METADATA_LOCK_FILE="${LIVE_EXECUTION_LOCK_FILE}.metadata"
readonly LIVE_EXECUTION_METADATA_LOCK_WAIT_SECONDS=0.1
readonly LIVE_EXECUTION_WRAPPER_MARKER="HOMELAB_IAC_LIFECYCLE_WRAPPER"
# Must match proxmox_api_host; a test pins it.
readonly LIVE_EXECUTION_FLEET_LOCK_HOST="proxmox.lan"
readonly LIVE_EXECUTION_FLEET_LOCK_FILE="/run/homelab-lifecycle.lock"
readonly LIVE_EXECUTION_FLEET_HOLDER_FILE="/run/homelab-lifecycle.holder"
readonly LIVE_EXECUTION_FLEET_LOCK_TIMEOUT_SECONDS=30

source "$LIVE_EXECUTION_PROJECT_ROOT/scripts/lib/uv-prerequisite.sh"

use_live_vault_password() {
    if [[ -z "${ANSIBLE_VAULT_PASSWORD_FILE:-}" && -f "$HOME/.ansible/vault-pass" ]]; then
        export ANSIBLE_VAULT_PASSWORD_FILE="$HOME/.ansible/vault-pass"
    fi
}

write_live_holder_record() {
    local holder_file="$1"
    local holder_pid="$2"
    local parent_pid="${3:-$holder_pid}"
    local temporary_record="${holder_file}.tmp"
    printf 'pid=%s parent_pid=%s worktree=%s\n' \
        "$holder_pid" "$parent_pid" "$LIVE_EXECUTION_PROJECT_ROOT" >"$temporary_record"
    mv "$temporary_record" "$holder_file"
}

process_has_live_file_descriptor() {
    local holder_pid="$1"
    local expected_path="$2"
    local descriptor
    local descriptor_target
    [[ "$holder_pid" =~ ^[0-9]+$ ]] && [[ -d "/proc/$holder_pid/fd" ]] || return 1
    for descriptor in "/proc/$holder_pid/fd/"*; do
        descriptor_target="$(readlink "$descriptor" 2>/dev/null)" || continue
        if [[ "$descriptor_target" == "$expected_path" ]]; then
            return 0
        fi
    done
    return 1
}

process_holds_metadata_lock() {
    local holder_pid="$1"
    local descriptor
    local descriptor_target
    local descriptor_info
    [[ "$holder_pid" =~ ^[0-9]+$ ]] && [[ -d "/proc/$holder_pid/fd" ]] || return 1
    for descriptor in "/proc/$holder_pid/fd/"*; do
        descriptor_target="$(readlink "$descriptor" 2>/dev/null)" || continue
        [[ "$descriptor_target" == "$LIVE_EXECUTION_METADATA_LOCK_FILE" ]] || continue
        while IFS= read -r descriptor_info; do
            [[ "$descriptor_info" == lock:*FLOCK*WRITE* ]] && return 0
        done <"/proc/$holder_pid/fdinfo/${descriptor##*/}" 2>/dev/null
    done
    return 1
}

live_holder_is_active() {
    process_has_live_file_descriptor "$1" "$LIVE_EXECUTION_LOCK_FILE"
}

write_live_metadata_holder_record() {
    printf 'pid=%s worktree=%s\n' "$$" "$LIVE_EXECUTION_PROJECT_ROOT" \
        >"$LIVE_EXECUTION_METADATA_LOCK_FILE"
}

report_live_metadata_holder() {
    local holder_record
    local holder_pid
    local holder_worktree
    local attempt
    for attempt in {1..3}; do
        holder_record="$(sed -n '1p' "$LIVE_EXECUTION_METADATA_LOCK_FILE")"
        holder_pid="${holder_record%% *}"
        holder_pid="${holder_pid#pid=}"
        holder_worktree="${holder_record#* worktree=}"
        if process_holds_metadata_lock "$holder_pid"; then
            echo "pid=$holder_pid worktree=$holder_worktree" >&2
            return 0
        fi
        sleep 0.005
    done
    return 1
}

acquire_live_metadata_lock() {
    local metadata_lock_fd="$1"
    if flock --exclusive \
        --wait "$LIVE_EXECUTION_METADATA_LOCK_WAIT_SECONDS" \
        "$metadata_lock_fd"; then
        write_live_metadata_holder_record
        return 0
    fi

    # The timed attempt can lose a release race. Recheck once before reporting
    # the coordinator whose active descriptor authenticates its record.
    if flock --exclusive --nonblock "$metadata_lock_fd"; then
        write_live_metadata_holder_record
        return 0
    fi
    echo \
        "Another machine-local live operation coordinates $LIVE_EXECUTION_LOCK_FILE metadata:" \
        >&2
    report_live_metadata_holder || echo "active metadata holder identity unavailable" >&2
    return 75
}

report_live_lock_holder() {
    local holder_file
    local holder_record
    local holder_pid
    local parent_pid
    local holder_worktree
    for holder_file in "$LIVE_EXECUTION_HOLDER_DIR/"*.holder; do
        [[ -f "$holder_file" ]] || continue
        holder_record="$(sed -n '1p' "$holder_file")"
        holder_pid="${holder_record%% *}"
        holder_pid="${holder_pid#pid=}"
        parent_pid="${holder_record#* parent_pid=}"
        parent_pid="${parent_pid%% *}"
        holder_worktree="${holder_record#* worktree=}"
        if live_holder_is_active "$holder_pid"; then
            echo "pid=$holder_pid worktree=$holder_worktree" >&2
            return
        fi
        if live_holder_is_active "$parent_pid"; then
            echo "pid=$parent_pid worktree=$holder_worktree" >&2
            return
        fi
    done
    sed -n '1p' "$LIVE_EXECUTION_LOCK_FILE" >&2
}

acquire_fleet_lease() {
    local holder remote
    holder="$(hostname) pid $$ since $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    remote="flock --nonblock --conflict-exit-code 75 $LIVE_EXECUTION_FLEET_LOCK_FILE"
    remote+=" sh -c 'echo \"\$1\" >$LIVE_EXECUTION_FLEET_HOLDER_FILE; echo acquired; exec cat >/dev/null' sh '$holder'"
    remote+=" || { s=\$?; cat $LIVE_EXECUTION_FLEET_HOLDER_FILE 2>/dev/null; exit \$s; }"
    # The coproc drops the machine-local lock's fd, so a hung ssh cannot keep
    # that lock. Bash drops a coproc's variables and pipe the moment it exits, so the
    # trailing cat keeps it alive, ssh's exit status reported in-band, until
    # this shell closes its stdin.
    coproc fleet_lease {
        exec {live_execution_lock_fd}>&-
        ssh_exit=0
        ssh -F none -i "$HOME/.ansible/ssh/proxmox_lxc" -p 22 \
            -o BatchMode=yes -o ConnectTimeout=10 \
            -o StrictHostKeyChecking=accept-new \
            -o UserKnownHostsFile="$HOME/.ansible/known_hosts" \
            -o IdentitiesOnly=yes -o PreferredAuthentications=publickey \
            -o AddressFamily=inet -o LogLevel=ERROR \
            "root@$LIVE_EXECUTION_FLEET_LOCK_HOST" "$remote" \
            2>&1 || ssh_exit=$?
        echo "ssh exited $ssh_exit"
        exec cat >/dev/null
    }
    local lease_in=${fleet_lease[1]} lease_out=${fleet_lease[0]} lease_pid=$fleet_lease_PID
    local line reason="" ssh_status=""
    while IFS= read -r -t "$LIVE_EXECUTION_FLEET_LOCK_TIMEOUT_SECONDS" -u "$lease_out" line; do
        case "$line" in
            acquired)
                # A reopen, not a dup: bash marks a dup of a coproc fd close-on-exec.
                exec {live_execution_lease_fd}>"/proc/self/fd/$lease_in" {lease_in}>&-
                return 0
                ;;
            "ssh exited "*)
                ssh_status=${line#ssh exited }
                break
                ;;
            *) reason=$line ;;
        esac
    done
    exec {lease_in}>&-
    case "$ssh_status" in
        75)
            echo "Deferred by busy checks:" >&2
            echo "proxmox: busy (a lifecycle run from ${reason:-an unrecorded holder} is in flight); this run not started" >&2
            return 3
            ;;
        "")
            kill "$lease_pid" 2>/dev/null
            reason="no answer within ${LIVE_EXECUTION_FLEET_LOCK_TIMEOUT_SECONDS}s"
            ;;
        *)
            reason="${reason:-ssh exited $ssh_status}"
            case "$reason" in
                *"Host key"*|*"HOST IDENTIFICATION"*|*"Permission denied"*)
                    reason+="; run ./recover.sh proxmox-host-ssh"
                    ;;
            esac
            ;;
    esac
    echo "proxmox: lock check failed ($reason); this run not started" >&2
    return 1
}

run_live_playbook() {
    local lock_class="$1"
    local playbook="$2"
    shift 2

    local flock_mode use_fleet_lease
    case "$lock_class" in
        shared) flock_mode=--shared use_fleet_lease=false ;;
        exclusive) flock_mode=--exclusive use_fleet_lease=true ;;
        exclusive-local) flock_mode=--exclusive use_fleet_lease=false ;;
        *)
            echo "Unsupported live lock class: $lock_class" >&2
            return 2
            ;;
    esac

    require_uv || return 1
    mkdir -p "$(dirname "$LIVE_EXECUTION_LOCK_FILE")" "$LIVE_EXECUTION_HOLDER_DIR"
    exec {live_execution_metadata_lock_fd}>>"$LIVE_EXECUTION_METADATA_LOCK_FILE"
    if ! acquire_live_metadata_lock "$live_execution_metadata_lock_fd"; then
        exec {live_execution_metadata_lock_fd}>&-
        return 75
    fi
    exec {live_execution_lock_fd}>>"$LIVE_EXECUTION_LOCK_FILE"
    if ! flock "$flock_mode" --nonblock "$live_execution_lock_fd"; then
        echo "Another machine-local live operation holds $LIVE_EXECUTION_LOCK_FILE:" >&2
        report_live_lock_holder
        exec {live_execution_lock_fd}>&-
        exec {live_execution_metadata_lock_fd}>&-
        return 75
    fi

    local holder_file="${LIVE_EXECUTION_HOLDER_DIR}/$$.holder"
    write_live_holder_record "$holder_file" "$$"
    exec {live_execution_metadata_lock_fd}>&-
    export "$LIVE_EXECUTION_WRAPPER_MARKER=1"
    cd "$LIVE_EXECUTION_PROJECT_ROOT"

    local status=0
    if $use_fleet_lease; then
        acquire_fleet_lease || status=$?
    fi

    # Reconciling under the held locks keeps contention fail-fast: a caller
    # that cannot run must not spend a download first.
    if ((status == 0)); then
        uv run --locked python -m scripts.live_dependencies \
            --playbook "$playbook" || status=$?
    fi
    if ((status == 0)); then
        echo "Running Ansible playbook through uv: $playbook"
        echo "────────────────────────────────────────"
        (
            write_live_holder_record "$holder_file" "$BASHPID" "$$"
            case "$playbook" in
                playbooks/lab-connectivity.yml|playbooks/add-ssh-keys-to-lxcs.yml|playbooks/enroll-proxmox-host-ssh.yml|playbooks/service-probe.yml)
                    unset ANSIBLE_VAULT_PASSWORD_FILE ANSIBLE_VAULT_IDENTITY_LIST
                    ;;
                *) use_live_vault_password ;;
            esac
            exec uv run --locked ansible-playbook "$playbook" "$@"
        ) || status=1
    fi
    exec {live_execution_metadata_lock_fd}>>"$LIVE_EXECUTION_METADATA_LOCK_FILE"
    if flock --exclusive \
        --wait "$LIVE_EXECUTION_METADATA_LOCK_WAIT_SECONDS" \
        "$live_execution_metadata_lock_fd"; then
        write_live_metadata_holder_record
    fi
    if [[ -n "${live_execution_lease_fd:-}" ]]; then
        exec {live_execution_lease_fd}>&-
    fi
    exec {live_execution_lock_fd}>&-
    rm -f -- "$holder_file"
    exec {live_execution_metadata_lock_fd}>&-
    return "$status"
}
