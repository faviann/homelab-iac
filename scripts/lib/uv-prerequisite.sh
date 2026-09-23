#!/bin/bash
# uv is a machine prerequisite: commands run it, and nothing here installs it.

require_uv() {
    command -v uv >/dev/null 2>&1 && return 0
    echo "${0##*/}: uv not found on PATH" >&2
    echo "uv is a machine prerequisite this repository does not install." >&2
    echo "Install uv (https://docs.astral.sh/uv/getting-started/installation/), then retry." >&2
    return 1
}
