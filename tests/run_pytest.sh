#!/bin/bash
# Run tests that use shared host state exclusively, then distribute the rest.

set -euo pipefail

serial_report_args=()
parallel_report_args=()
if [[ -n "${VALIDATE_JUNIT_REPORT_DIR:-}" ]]; then
    mkdir -p -- "$VALIDATE_JUNIT_REPORT_DIR"
    serial_report_args=("--junitxml=$VALIDATE_JUNIT_REPORT_DIR/serial.xml")
    parallel_report_args=("--junitxml=$VALIDATE_JUNIT_REPORT_DIR/parallel.xml")
fi

unset PYTEST_ADDOPTS

case "${VALIDATE_TESTS_SERIAL:-0}" in
    1)
        uv run --locked pytest -n 0 \
            "${serial_report_args[@]}" "$@"
        ;;
    0)
        serial_status=0
        uv run --locked pytest -n 0 -m serial \
            "${serial_report_args[@]}" "$@" || serial_status="$?"
        if ((serial_status != 0 && serial_status != 5)); then
            exit "$serial_status"
        fi

        parallel_status=0
        uv run --locked pytest -n 2 \
            --dist=worksteal --max-worker-restart=0 -m "not serial" \
            "${parallel_report_args[@]}" "$@" || parallel_status="$?"
        if ((parallel_status != 0 && parallel_status != 5)); then
            exit "$parallel_status"
        fi
        if ((serial_status == 5 && parallel_status == 5)); then
            exit 5
        fi
        ;;
    *)
        echo "run_pytest.sh: VALIDATE_TESTS_SERIAL must be 0 or 1" >&2
        exit 2
        ;;
esac
