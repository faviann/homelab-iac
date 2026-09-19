#!/bin/bash
# Run tests that use shared host state exclusively, then distribute the rest.

set -euo pipefail

unset PYTEST_ADDOPTS

serial_status=0
uv run --locked pytest -n 0 -m serial "$@" || serial_status="$?"
# Exit 1 means test failures; run the other lane to preserve coverage.
if ((serial_status != 0 && serial_status != 1 && serial_status != 5)); then
    exit "$serial_status"
fi

parallel_status=0
uv run --locked pytest -n 2 \
    --dist=worksteal --max-worker-restart=0 -m "not serial" "$@" \
    || parallel_status="$?"
if ((parallel_status != 0 && parallel_status != 1 && parallel_status != 5)); then
    exit "$parallel_status"
fi
if ((serial_status == 1 || parallel_status == 1)); then
    exit 1
fi
if ((serial_status == 5 && parallel_status == 5)); then
    exit 5
fi
