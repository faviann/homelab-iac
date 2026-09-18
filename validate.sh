#!/bin/bash
# Deterministic, non-live repository validation.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

usage() {
    cat <<'EOF'
Usage: ./validate.sh [operation] [options]

With no operation, run the comprehensive non-live handoff validation:
repo-wide lint, the full lifecycle regression set, and the whole test suite,
stopping at the first failure.

Operations:
  lint                        Run repo-wide production-profile lint only
  lifecycle [--full] [--only <launcher.py>]... [--fail-fast]
                              Run the lifecycle regression set
  tests [<target>...]         Run the test suite, optionally restricted to
                              targets inside tests/ (a path, optionally with a
                              ::node-id suffix)
  stack <path>                Validate one repo-managed stack update policy;
                              schema-versioned JSON on stdout, diagnostics on
                              stderr

Options:
  --full                      Run the full lifecycle regression set
  --only <launcher.py>        Run only this registered launcher (repeatable)
  --fail-fast                 Stop the lifecycle set after the first failure
  --help                      Show this help
EOF
}

usage_error() {
    echo "validate.sh: $1" >&2
    echo "Try './validate.sh --help' for usage." >&2
    exit 2
}

operation="handoff"
case "${1:-}" in
    --help)
        usage
        exit 0
        ;;
    "") ;;
    lint | lifecycle | tests | stack)
        operation="$1"
        shift
        ;;
    -*)
        usage_error "unknown option"
        ;;
    *)
        usage_error "unknown operation"
        ;;
esac

lifecycle_arguments=()
lifecycle_full=false
lifecycle_only=false
test_targets=()
stack_paths=()

in_test_tree() {
    local resolved
    resolved="$(realpath -m -- "$1" 2>/dev/null)" || return 1
    [[ "$resolved" == "$PROJECT_ROOT/tests" ]] ||
        [[ "$resolved" == "$PROJECT_ROOT/tests/"* ]]
}

lifecycle_option() {
    [[ "$operation" == "lifecycle" ]] || usage_error "unknown option"
}

while (($#)); do
    case "$1" in
        --help)
            usage
            exit 0
            ;;
        --full)
            lifecycle_option
            lifecycle_full=true
            lifecycle_arguments+=("--full")
            shift
            ;;
        --fail-fast)
            lifecycle_option
            lifecycle_arguments+=("--fail-fast")
            shift
            ;;
        --only)
            lifecycle_option
            (($# >= 2)) && [[ -n "$2" ]] && [[ "$2" != -* ]] ||
                usage_error "$1 requires a value"
            lifecycle_only=true
            lifecycle_arguments+=("--only" "$2")
            shift 2
            ;;
        -*)
            usage_error "unknown option"
            ;;
        *)
            case "$operation" in
                tests)
                    in_test_tree "${1%%::*}" ||
                        usage_error "test target outside tests/: $1"
                    test_targets+=("$1")
                    ;;
                stack)
                    stack_paths+=("$1")
                    ;;
                *)
                    usage_error "$operation takes no arguments"
                    ;;
            esac
            shift
            ;;
    esac
done

if [[ "$operation" == "lifecycle" ]] && $lifecycle_full && $lifecycle_only; then
    usage_error "--only cannot be combined with --full"
fi
if [[ "$operation" == "stack" ]] && ((${#stack_paths[@]} != 1)); then
    usage_error "stack requires exactly one stack path"
fi

# Keep every validation child on repository-owned, credential-free Ansible
# inputs. Individual regression launchers inherit the same boundary.
export ANSIBLE_INVENTORY="$PROJECT_ROOT/tests/fixtures/ansible/inventory.yml"
export ANSIBLE_VAULT_PASSWORD_FILE="$PROJECT_ROOT/tests/fixtures/ansible/vault-pass"

# Isolate non-live validation from the operator's live fact cache (issue #89).
VALIDATION_CACHE_DIR="$(mktemp -d)"
HANDOFF_TEMP_DIR=""
cleanup_validation() {
    rm -rf -- "$VALIDATION_CACHE_DIR"
    if [[ -n "$HANDOFF_TEMP_DIR" ]]; then
        rm -rf -- "$HANDOFF_TEMP_DIR"
    fi
}
trap cleanup_validation EXIT
export ANSIBLE_CACHE_PLUGIN_CONNECTION="$VALIDATION_CACHE_DIR"

run_handoff() {
    local lifecycle_cache pytest_cache lifecycle_log pytest_log
    local phase phase_log reason other_phase finished_pid wait_status first_failure=0
    local handoff_signal=0 lifecycle_pid="" pytest_pid=""
    local lifecycle_status="" pytest_status=""
    local lifecycle_supervision="" pytest_supervision=""
    local -a active_pids=()

    HANDOFF_TEMP_DIR="$(mktemp -d)"
    lifecycle_cache="$HANDOFF_TEMP_DIR/lifecycle-cache"
    pytest_cache="$HANDOFF_TEMP_DIR/pytest-cache"
    lifecycle_log="$HANDOFF_TEMP_DIR/lifecycle.log"
    pytest_log="$HANDOFF_TEMP_DIR/pytest.log"

    phase_is_running() {
        local pid="$1" running_pid
        [[ -n "$pid" ]] || return 1
        while read -r running_pid; do
            [[ "$running_pid" == "$pid" ]] && return 0
        done < <(jobs -pr)
        return 1
    }

    reap_phase_group() {
        local pid="$1"
        [[ -n "$pid" ]] || return 0
        kill -0 -- "-$pid" 2>/dev/null || return 0
        kill -KILL -- "-$pid" 2>/dev/null || true
        for _ in {1..20}; do
            kill -0 -- "-$pid" 2>/dev/null || return 0
            sleep 0.05
        done
    }

    supervise_phase() {
        local name="$1" reason="$2" pid
        if [[ "$name" == lifecycle ]]; then
            pid="$lifecycle_pid"
        else
            pid="$pytest_pid"
        fi
        phase_is_running "$pid" || return 1
        if [[ "$name" == lifecycle ]]; then
            lifecycle_supervision="$reason"
        else
            pytest_supervision="$reason"
        fi
        kill -TERM "$pid" 2>/dev/null || true
        kill -TERM -- "-$pid" 2>/dev/null || true
        for _ in {1..20}; do
            phase_is_running "$pid" || return 0
            sleep 0.05
        done
        kill -KILL "$pid" 2>/dev/null || true
        kill -KILL -- "-$pid" 2>/dev/null || true
        return 0
    }

    handle_handoff_signal() {
        handoff_signal="$1"
        [[ -n "$lifecycle_pid" ]] && supervise_phase lifecycle interrupted || true
        [[ -n "$pytest_pid" ]] && supervise_phase pytest interrupted || true
    }

    trap 'handle_handoff_signal 2' INT
    trap 'handle_handoff_signal 15' TERM

    if ((handoff_signal == 0)); then
        ANSIBLE_CACHE_PLUGIN_CONNECTION="$lifecycle_cache" setsid --wait \
            env --default-signal=INT,QUIT uv run --locked python \
            tests/regression/run_lxc_lifecycle_regressions.py --full \
            >"$lifecycle_log" 2>&1 &
        lifecycle_pid="$!"
        if ((handoff_signal != 0)); then
            supervise_phase lifecycle interrupted || true
        fi
    fi
    if ((handoff_signal == 0)); then
        ANSIBLE_CACHE_PLUGIN_CONNECTION="$pytest_cache" setsid --wait \
            env --default-signal=INT,QUIT uv run --locked pytest \
            >"$pytest_log" 2>&1 &
        pytest_pid="$!"
        if ((handoff_signal != 0)); then
            supervise_phase pytest interrupted || true
        fi
    fi

    while :; do
        active_pids=()
        [[ -n "$lifecycle_pid" && -z "$lifecycle_status" ]] &&
            active_pids+=("$lifecycle_pid")
        [[ -n "$pytest_pid" && -z "$pytest_status" ]] &&
            active_pids+=("$pytest_pid")
        ((${#active_pids[@]})) || break

        finished_pid=""
        if wait -n -p finished_pid "${active_pids[@]}"; then
            wait_status=0
        else
            wait_status="$?"
        fi
        [[ -n "${finished_pid:-}" ]] || break
        if [[ "$finished_pid" == "$lifecycle_pid" ]]; then
            phase=lifecycle
            lifecycle_status="$wait_status"
        else
            phase=pytest
            pytest_status="$wait_status"
        fi

        if ((wait_status != 0 && first_failure == 0)); then
            first_failure="$wait_status"
            if [[ "$phase" == lifecycle && -n "$pytest_pid" && -z "$pytest_status" ]]; then
                supervise_phase pytest after-lifecycle-failure || true
            elif [[ "$phase" == pytest && -n "$lifecycle_pid" && -z "$lifecycle_status" ]]; then
                supervise_phase lifecycle after-pytest-failure || true
            fi
        fi
    done

    if [[ -n "$lifecycle_pid" && -z "$lifecycle_status" ]]; then
        if wait "$lifecycle_pid"; then
            lifecycle_status=0
        else
            lifecycle_status="$?"
        fi
    fi
    if [[ -n "$pytest_pid" && -z "$pytest_status" ]]; then
        if wait "$pytest_pid"; then
            pytest_status=0
        else
            pytest_status="$?"
        fi
    fi
    if [[ -n "$lifecycle_pid" ]]; then
        ((lifecycle_status == 0 || first_failure != 0)) || first_failure="$lifecycle_status"
        reap_phase_group "$lifecycle_pid"
    fi
    if [[ -n "$pytest_pid" ]]; then
        ((pytest_status == 0 || first_failure != 0)) || first_failure="$pytest_status"
        reap_phase_group "$pytest_pid"
    fi

    trap - INT TERM
    for phase in lifecycle pytest; do
        if [[ "$phase" == lifecycle ]]; then
            phase_log="$lifecycle_log"
            wait_status="$lifecycle_status"
            reason="$lifecycle_supervision"
        else
            phase_log="$pytest_log"
            wait_status="$pytest_status"
            reason="$pytest_supervision"
        fi
        [[ -n "$wait_status" ]] || continue
        if [[ "$reason" == interrupted ]]; then
            printf 'validate.sh: %s interrupted by signal (exit %s)\n' \
                "$phase" "$wait_status" >&2
            cat "$phase_log" >&2
        elif [[ "$reason" == after-* ]]; then
            other_phase="${reason#after-}"
            other_phase="${other_phase%-failure}"
            printf 'validate.sh: %s terminated after %s failure (exit %s)\n' \
                "$phase" "$other_phase" "$wait_status" >&2
            cat "$phase_log" >&2
        elif ((wait_status == 0)); then
            printf 'validate.sh: %s passed\n' "$phase"
            cat "$phase_log"
        else
            printf 'validate.sh: %s failed (exit %s)\n' "$phase" "$wait_status" >&2
            cat "$phase_log" >&2
        fi
    done

    if ((handoff_signal != 0)); then
        return $((128 + handoff_signal))
    fi
    return "$first_failure"
}

case "$operation" in
    handoff)
        uv run --locked ansible-lint
        run_handoff
        ;;
    lint)
        uv run --locked ansible-lint
        ;;
    lifecycle)
        uv run --locked python \
            tests/regression/run_lxc_lifecycle_regressions.py \
            ${lifecycle_arguments[@]+"${lifecycle_arguments[@]}"}
        ;;
    tests)
        uv run --locked pytest ${test_targets[@]+"${test_targets[@]}"}
        ;;
    stack)
        uv run --locked python -B -m stack_update_policy validate \
            --repository-root . "${stack_paths[0]}"
        ;;
esac
