#!/bin/bash
# Automated workstation setup for ServerManagementScripts
# This script prepares a fresh workstation to run Ansible playbooks

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Determine project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  ServerManagementScripts - Workstation Setup              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo

# Function to print status
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    print_error "Do not run this script as root. It will request sudo when needed."
    exit 1
fi

echo "Step 1: Checking system prerequisites..."
echo "─────────────────────────────────────────"

# Check for required commands
MISSING_PACKAGES=()

if ! command -v python3 &> /dev/null; then
    print_error "python3 not found"
    MISSING_PACKAGES+=("python3")
fi

if ! dpkg -l | grep -q python3-venv; then
    print_warning "python3-venv not installed"
    MISSING_PACKAGES+=("python3-venv")
fi

if ! dpkg -l | grep -q python3-pip; then
    print_warning "python3-pip not installed"
    MISSING_PACKAGES+=("python3-pip")
fi

if ! dpkg -l | grep -q sshpass; then
    print_warning "sshpass not installed"
    MISSING_PACKAGES+=("sshpass")
fi

# Install missing packages
if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
    echo
    print_info "Installing missing packages: ${MISSING_PACKAGES[*]}"
    echo "This requires sudo access..."
    sudo apt update
    sudo apt install -y "${MISSING_PACKAGES[@]}"
    print_status "Packages installed"
else
    print_status "All system prerequisites satisfied"
fi

echo
echo "Step 2: Setting up project structure..."
echo "─────────────────────────────────────────"

# Create .ansible directory if it doesn't exist
mkdir -p .ansible/ssh
mkdir -p .ansible/cp
mkdir -p .ansible/cache
print_status "Created .ansible directories"

echo
echo "Step 3: Vault password configuration..."
echo "─────────────────────────────────────────"

# Generate or prompt for vault password
VAULT_PASS_FILE=".ansible/vault-pass.txt"

if [ -f "$VAULT_PASS_FILE" ]; then
    print_warning "Vault password file already exists at $VAULT_PASS_FILE"
    read -p "Do you want to keep it? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        rm "$VAULT_PASS_FILE"
        print_info "Removed existing vault password file"
    else
        print_status "Keeping existing vault password"
    fi
fi

if [ ! -f "$VAULT_PASS_FILE" ]; then
    echo
    echo "Choose vault password method:"
    echo "  1) Generate secure random password (recommended)"
    echo "  2) Enter your own password"
    read -p "Choice (1/2): " -n 1 -r PASS_CHOICE
    echo
    
    if [ "$PASS_CHOICE" == "1" ]; then
        # Generate a secure random password
        VAULT_PASS=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-32)
        echo "$VAULT_PASS" > "$VAULT_PASS_FILE"
        chmod 600 "$VAULT_PASS_FILE"
        print_status "Generated secure vault password"
        echo
        print_warning "IMPORTANT: Save this password securely!"
        echo -e "${YELLOW}Vault password: ${GREEN}${VAULT_PASS}${NC}"
        echo
        read -p "Press Enter after you've saved the password..." -r
    else
        # Prompt for password
        echo
        read -sp "Enter vault password: " VAULT_PASS
        echo
        read -sp "Confirm vault password: " VAULT_PASS_CONFIRM
        echo
        
        if [ "$VAULT_PASS" != "$VAULT_PASS_CONFIRM" ]; then
            print_error "Passwords do not match"
            exit 1
        fi
        
        echo "$VAULT_PASS" > "$VAULT_PASS_FILE"
        chmod 600 "$VAULT_PASS_FILE"
        print_status "Vault password saved"
    fi
else
    print_status "Using existing vault password"
fi

echo
echo "Step 4: Proxmox API credentials..."
echo "─────────────────────────────────────────"

# Prompt for Proxmox credentials
echo
print_info "Enter your Proxmox API credentials"
echo "These will be stored in an encrypted vault file."
echo

# Proxmox API host
read -p "Proxmox API host [proxmox.lan]: " PROXMOX_HOST
PROXMOX_HOST=${PROXMOX_HOST:-proxmox.lan}

# Proxmox API user
echo
print_info "API user format: username@realm (e.g., root@pam, ansible@pve)"
read -p "Proxmox API user [root@pam]: " PROXMOX_USER
PROXMOX_USER=${PROXMOX_USER:-root@pam}

# Proxmox API token ID
echo
print_info "Token ID is the name you gave the token (e.g., ansible-automation)"
read -p "Proxmox API token ID: " PROXMOX_TOKEN_ID

while [ -z "$PROXMOX_TOKEN_ID" ]; do
    print_warning "Token ID cannot be empty"
    read -p "Proxmox API token ID: " PROXMOX_TOKEN_ID
done

# Proxmox API token secret
echo
print_info "Token secret is the UUID shown when creating the token"
read -sp "Proxmox API token secret: " PROXMOX_TOKEN_SECRET
echo

while [ -z "$PROXMOX_TOKEN_SECRET" ]; do
    print_warning "Token secret cannot be empty"
    read -sp "Proxmox API token secret: " PROXMOX_TOKEN_SECRET
    echo
done

print_status "Credentials captured"

echo
echo "Step 5: Creating Python virtual environment..."
echo "─────────────────────────────────────────"

VENV_PATH=".ansible/venv"

if [ -d "$VENV_PATH" ]; then
    print_warning "Virtual environment already exists"
    read -p "Recreate it? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$VENV_PATH"
        print_info "Removed existing venv"
    fi
fi

if [ ! -d "$VENV_PATH" ]; then
    python3 -m venv "$VENV_PATH"
    print_status "Created virtual environment"
    
    # Activate and upgrade pip
    source "$VENV_PATH/bin/activate"
    pip install --quiet --upgrade pip
    print_status "Upgraded pip"
    
    # Install ansible
    print_info "Installing Ansible (this may take a moment)..."
    pip install --quiet ansible
    print_status "Installed Ansible"
else
    source "$VENV_PATH/bin/activate"
    print_status "Using existing virtual environment"
fi

echo
echo "Step 6: Running bootstrap playbook..."
echo "─────────────────────────────────────────"

if [ ! -f "bootstrap.yml" ]; then
    print_error "bootstrap.yml not found in $PROJECT_ROOT"
    exit 1
fi

ansible-playbook bootstrap.yml
print_status "Bootstrap completed"

echo
echo "Step 7: Creating and encrypting vault..."
echo "─────────────────────────────────────────"

VAULT_FILE="inventory/group_vars/all/vault.yml"

if [ -f "$VAULT_FILE" ]; then
    # Check if already encrypted
    if head -n1 "$VAULT_FILE" | grep -q '$ANSIBLE_VAULT'; then
        print_status "Vault file already exists and is encrypted"
        print_info "To update credentials, run: ./configure-vault.sh"
    else
        print_warning "Vault file exists but is NOT encrypted"
        read -p "Replace with new credentials and encrypt? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm "$VAULT_FILE"
        else
            print_info "Keeping existing unencrypted vault"
            echo
            read -p "Encrypt existing vault? (y/n): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                ansible-vault encrypt "$VAULT_FILE"
                print_status "Vault encrypted"
            fi
        fi
    fi
fi

if [ ! -f "$VAULT_FILE" ]; then
    print_info "Creating vault.yml with your credentials..."
    
    # Create vault file with captured credentials
    cat > "$VAULT_FILE" << EOF
---
# Proxmox API authentication details
# Generated by setup.sh on $(date)

vault_proxmox_api_user: "$PROXMOX_USER"
vault_proxmox_api_token_id: "$PROXMOX_TOKEN_ID"
vault_proxmox_api_token_secret: "$PROXMOX_TOKEN_SECRET"
EOF
    
    print_status "Created vault.yml"
    
    # Encrypt the vault file
    print_info "Encrypting vault.yml..."
    ansible-vault encrypt "$VAULT_FILE"
    print_status "Vault encrypted and ready to use"
fi

echo
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Setup Complete!                                          ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo
echo "Project is ready to use. Quick reference:"
echo
echo "  • Activate environment:    ${BLUE}source activate-env.sh${NC}"
echo "  • Test connectivity:       ${BLUE}ansible-playbook site.yml --tags validation${NC}"
echo "  • Update credentials:      ${BLUE}./configure-vault.sh${NC}"
echo "  • View vault password:     ${BLUE}cat .ansible/vault-pass.txt${NC}"
echo "  • Edit encrypted vault:    ${BLUE}ansible-vault edit inventory/group_vars/all/vault.yml${NC}"
echo
echo "Documentation:"
echo "  • Main README:             ${BLUE}README.md${NC}"
echo "  • Agent instructions:      ${BLUE}AGENTS.md${NC}"
echo

# Deactivate venv for clean exit
deactivate 2>/dev/null || true
