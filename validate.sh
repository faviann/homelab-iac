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
reporting both lifecycle and test results when either one fails.

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
trap 'rm -rf -- "$VALIDATION_CACHE_DIR"' EXIT
export ANSIBLE_CACHE_PLUGIN_CONNECTION="$VALIDATION_CACHE_DIR"

run_handoff() {
    local lifecycle_pid="" pytest_pid="" lifecycle_status=0 pytest_status=0

    interrupt_handoff() {
        local latest_pid="$!" signal_status="$1"
        trap - INT TERM
        [[ -z "$lifecycle_pid" ]] || kill -TERM -- "$lifecycle_pid" 2>/dev/null || true
        [[ -z "$lifecycle_pid" ]] || kill -TERM -- "-$lifecycle_pid" 2>/dev/null || true
        [[ -z "$pytest_pid" ]] || kill -TERM -- "$pytest_pid" 2>/dev/null || true
        [[ -z "$pytest_pid" ]] || kill -TERM -- "-$pytest_pid" 2>/dev/null || true
        [[ -z "$latest_pid" ]] || kill -TERM -- "$latest_pid" 2>/dev/null || true
        [[ -z "$latest_pid" ]] || kill -TERM -- "-$latest_pid" 2>/dev/null || true
        [[ -z "$lifecycle_pid" ]] || wait "$lifecycle_pid" 2>/dev/null || true
        [[ -z "$pytest_pid" ]] || wait "$pytest_pid" 2>/dev/null || true
        [[ -z "$latest_pid" ]] || wait "$latest_pid" 2>/dev/null || true
        exit "$signal_status"
    }

    trap 'interrupt_handoff 130' INT
    trap 'interrupt_handoff 143' TERM

    ANSIBLE_CACHE_PLUGIN_CONNECTION="$VALIDATION_CACHE_DIR/lifecycle-cache" \
        setsid --wait env --default-signal=INT,QUIT uv run --locked python \
        tests/regression/run_lxc_lifecycle_regressions.py --full \
        >"$VALIDATION_CACHE_DIR/lifecycle.log" 2>&1 &
    lifecycle_pid="$!"
    ANSIBLE_CACHE_PLUGIN_CONNECTION="$VALIDATION_CACHE_DIR/pytest-cache" \
        setsid --wait env --default-signal=INT,QUIT bash \
        tests/run_pytest.sh \
        >"$VALIDATION_CACHE_DIR/pytest.log" 2>&1 &
    pytest_pid="$!"

    wait "$lifecycle_pid" || lifecycle_status="$?"
    wait "$pytest_pid" || pytest_status="$?"
    trap - INT TERM

    if ((lifecycle_status == 0)); then
        printf 'validate.sh: lifecycle passed\n'
        cat "$VALIDATION_CACHE_DIR/lifecycle.log"
    else
        printf 'validate.sh: lifecycle failed (exit %s)\n' \
            "$lifecycle_status" >&2
        cat "$VALIDATION_CACHE_DIR/lifecycle.log" >&2
    fi
    if ((pytest_status == 0)); then
        printf 'validate.sh: pytest passed\n'
        cat "$VALIDATION_CACHE_DIR/pytest.log"
    else
        printf 'validate.sh: pytest failed (exit %s)\n' "$pytest_status" >&2
        cat "$VALIDATION_CACHE_DIR/pytest.log" >&2
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
        bash tests/run_pytest.sh ${test_targets[@]+"${test_targets[@]}"}
        ;;
    stack)
        uv run --locked python -B -m stack_update_policy validate \
            --repository-root . "${stack_paths[0]}"
        ;;
esac
