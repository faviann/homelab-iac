#!/bin/bash
# Quick-run script for ServerManagementScripts

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "Running Ansible playbook through uv: site.yml $*"
echo "────────────────────────────────────────"
uv run --locked ansible-playbook site.yml "$@"
