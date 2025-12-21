#!/bin/bash
# Quick-run script for ServerManagementScripts
# Activates venv and runs the main Ansible orchestration

set -e

# Determine project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Activate venv
VENV_PATH=".ansible/venv"
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo "✗ Virtual environment not found at $VENV_PATH"
    echo "  Run ./setup.sh first to initialize the project"
    exit 1
fi

source "$VENV_PATH/bin/activate"

# Run the main playbook with any arguments passed to the script
echo "Running Ansible playbook: site.yml $*"
echo "────────────────────────────────────────"
ansible-playbook site.yml "$@"
