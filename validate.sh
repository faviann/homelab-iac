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
    local phase phase_log wait_status
    local handoff_signal=0 lifecycle_pid="" pytest_pid=""
    local lifecycle_status="" pytest_status=""

    HANDOFF_TEMP_DIR="$(mktemp -d)"
    lifecycle_cache="$HANDOFF_TEMP_DIR/lifecycle-cache"
    pytest_cache="$HANDOFF_TEMP_DIR/pytest-cache"
    lifecycle_log="$HANDOFF_TEMP_DIR/lifecycle.log"
    pytest_log="$HANDOFF_TEMP_DIR/pytest.log"

    reap_phase_group() {
        local pid="$1"
        [[ -n "$pid" ]] || return 0
        kill -KILL -- "-$pid" 2>/dev/null || true
        for _ in {1..20}; do
            kill -0 -- "-$pid" 2>/dev/null || return 0
            sleep 0.05
        done
    }

    cleanup_phase() {
        local pid="$1"
        [[ -n "$pid" ]] || return 0
        kill -TERM "$pid" 2>/dev/null || true
        kill -TERM -- "-$pid" 2>/dev/null || true
        reap_phase_group "$pid"
    }

    handle_handoff_signal() {
        handoff_signal="$1"
        cleanup_phase "$lifecycle_pid"
        cleanup_phase "$pytest_pid"
    }

    trap 'handle_handoff_signal 2' INT
    trap 'handle_handoff_signal 15' TERM

    if ((handoff_signal == 0)); then
        ANSIBLE_CACHE_PLUGIN_CONNECTION="$lifecycle_cache" setsid --wait \
            env --default-signal=INT,QUIT uv run --locked python \
            tests/regression/run_lxc_lifecycle_regressions.py --full \
            >"$lifecycle_log" 2>&1 &
        lifecycle_pid="$!"
        ((handoff_signal == 0)) || cleanup_phase "$lifecycle_pid"
    fi
    if ((handoff_signal == 0)); then
        ANSIBLE_CACHE_PLUGIN_CONNECTION="$pytest_cache" setsid --wait \
            env --default-signal=INT,QUIT uv run --locked pytest \
            >"$pytest_log" 2>&1 &
        pytest_pid="$!"
        ((handoff_signal == 0)) || cleanup_phase "$pytest_pid"
    fi

    if [[ -n "$lifecycle_pid" ]]; then
        if wait "$lifecycle_pid"; then
            lifecycle_status=0
        else
            lifecycle_status="$?"
        fi
    fi
    if [[ -n "$pytest_pid" ]]; then
        if wait "$pytest_pid"; then
            pytest_status=0
        else
            pytest_status="$?"
        fi
    fi
    trap - INT TERM
    for phase in lifecycle pytest; do
        if [[ "$phase" == lifecycle ]]; then
            phase_log="$lifecycle_log"
            wait_status="$lifecycle_status"
        else
            phase_log="$pytest_log"
            wait_status="$pytest_status"
        fi
        [[ -n "$wait_status" ]] || continue
        if ((handoff_signal != 0)); then
            printf 'validate.sh: %s interrupted by signal (exit %s)\n' \
                "$phase" "$wait_status" >&2
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
    if ((lifecycle_status != 0)); then
        return "$lifecycle_status"
    fi
    return "$pytest_status"
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
