#!/bin/bash
# Activate local Ansible environment (project-portable setup)
# Usage: source activate-env.sh

# Determine project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$PROJECT_ROOT/.ansible/venv"

if [ -f "$VENV_PATH/bin/activate" ]; then
    # Activate existing venv
    source "$VENV_PATH/bin/activate"
    echo "✓ Activated Ansible venv at $VENV_PATH"
    echo "  Python: $(which python3)"
    echo "  Ansible: $(ansible --version | head -n1)"
else
    echo "✗ Virtual environment not found at $VENV_PATH"
    echo "  Run 'ansible-playbook bootstrap.yml' to create it"
    return 1
fi
