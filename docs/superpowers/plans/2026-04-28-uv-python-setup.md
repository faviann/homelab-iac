# uv Python Environment Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pip+venv with uv so the Python environment is zero-thought for humans and auto-discoverable by agents.

**Architecture:** `pyproject.toml` declares all dependencies. `uv sync` creates `.venv/` at the project root — the conventional location auto-discovered by most tooling. `setup.sh` self-installs uv if missing. `bootstrap.yml` runs `uv sync` as a pre-task so it works as a standalone recovery command. The `control_node_bootstrap` role drops its now-redundant pip install tasks. `direnv` uses `layout uv` to activate the env and sync dependencies automatically on `cd`.

**Tech Stack:** uv ≥ 0.5, direnv ≥ 2.33, pyproject.toml (PEP 517/621)

---

## File Map

| Action | Path |
|--------|------|
| Create | `pyproject.toml` |
| Delete | `requirements/pip.txt` |
| Modify | `.envrc` |
| Modify | `setup.sh` |
| Modify | `bootstrap.yml` |
| Modify | `playbooks/roles/base/control_node_bootstrap/tasks/main.yml` |
| Modify | `playbooks/roles/base/control_node_bootstrap/defaults/main.yml` |
| Modify | `activate-env.sh` |
| Modify | `run.sh` |
| Modify | `AGENTS.md` |
| Modify | `README.md` |

---

### Task 1: Add pyproject.toml and generate lockfile

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "server-management-scripts"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "ansible>=13.5.0",
    "ansible-lint>=24.0.0",
    "yamllint>=1.32.0",
    "requests>=1.1",
    "proxmoxer>=2.0",
]

[dependency-groups]
dev = ["pytest>=8.0"]
```

- [ ] **Step 2: Run uv sync to verify and generate lockfile**

```bash
uv sync
```

Expected: uv creates `.venv/` and installs all packages. A `uv.lock` file is created.

- [ ] **Step 3: Verify key binaries are present**

```bash
.venv/bin/ansible --version | head -n1
.venv/bin/pytest --version
```

Expected: ansible and pytest version lines printed without error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(bootstrap): add pyproject.toml and uv lockfile"
```

---

### Task 2: Update .envrc to use layout uv

**Files:**
- Modify: `.envrc`

- [ ] **Step 1: Replace the venv activation line**

Current content of `.envrc`:
```bash
source .ansible/venv/bin/activate
```

New content:
```bash
layout uv
```

- [ ] **Step 2: Allow and verify**

```bash
direnv allow
which python
```

Expected: path shows `.venv/bin/python` in the project directory.

- [ ] **Step 3: Verify ansible is on PATH via direnv**

```bash
which ansible
```

Expected: `.venv/bin/ansible`

- [ ] **Step 4: Commit**

```bash
git add .envrc
git commit -m "feat(bootstrap): switch direnv to layout uv"
```

---

### Task 3: Update setup.sh

**Files:**
- Modify: `setup.sh`

- [ ] **Step 1: Remove python3-venv and python3-pip from the prerequisites check**

Find this block in `setup.sh` (around the MISSING_PACKAGES section):

```bash
if ! dpkg -l | grep -q python3-venv; then
    print_warning "python3-venv not installed"
    MISSING_PACKAGES+=("python3-venv")
fi

if ! dpkg -l | grep -q python3-pip; then
    print_warning "python3-pip not installed"
    MISSING_PACKAGES+=("python3-pip")
fi
```

Delete both `if` blocks entirely. Leave the `python3`, `sshpass`, and `direnv` checks untouched.

- [ ] **Step 2: Add uv self-installation after the system prerequisites block**

After the system packages `apt install` block (end of Step 1 in setup.sh), add:

```bash
# Install uv if not present
if ! command -v uv &> /dev/null; then
    print_info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    print_status "uv installed"
else
    print_status "uv already installed ($(uv --version))"
fi
```

- [ ] **Step 3: Replace the entire Step 5 venv block with uv sync**

Find and delete this entire block in setup.sh (Step 5):

```bash
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
```

Replace with:

```bash
echo
echo "Step 5: Installing Python dependencies..."
echo "─────────────────────────────────────────"

print_info "Running uv sync..."
uv sync
print_status "Python dependencies installed"
```

- [ ] **Step 4: Update the bootstrap.yml invocation to not rely on venv activate**

In Step 6 (Running bootstrap playbook), the `ansible-playbook` call now works because `uv sync` put ansible in `.venv/bin/` and setup.sh runs after `layout uv` would have activated it. But setup.sh runs outside direnv context, so explicitly use the venv binary:

Find:
```bash
ansible-playbook bootstrap.yml
```

Replace with:
```bash
.venv/bin/ansible-playbook bootstrap.yml
```

- [ ] **Step 5: Verify setup.sh has no remaining references to .ansible/venv**

```bash
grep -n "ansible/venv\|python3-venv\|python3-pip" setup.sh
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add setup.sh
git commit -m "feat(bootstrap): migrate setup.sh to uv"
```

---

### Task 4: Update bootstrap.yml and control_node_bootstrap role

**Files:**
- Modify: `bootstrap.yml`
- Modify: `playbooks/roles/base/control_node_bootstrap/tasks/main.yml`
- Modify: `playbooks/roles/base/control_node_bootstrap/defaults/main.yml`
- Delete: `requirements/pip.txt`

- [ ] **Step 1: Add uv sync pre-task to bootstrap.yml**

Current `bootstrap.yml`:
```yaml
---
# Bootstrap playbook for preparing the Ansible control node on localhost.
- name: Bootstrap Ansible control node
  hosts: localhost
  connection: local
  gather_facts: true
  become: false  # Run as regular user; system packages must be pre-installed
  tags:
    - always
    - bootstrap
  collections:
    - community.crypto
  vars:
    control_node_project_root: "{{ playbook_dir }}"
    control_node_pip_requirements: "{{ [playbook_dir, 'requirements', 'pip.txt'] | path_join }}"
    control_node_collection_requirements: "{{ [playbook_dir, 'collections', 'requirements.yml'] | path_join }}"
  roles:
    - base/control_node_bootstrap
```

Replace with:
```yaml
---
# Bootstrap playbook for preparing the Ansible control node on localhost.
- name: Bootstrap Ansible control node
  hosts: localhost
  connection: local
  gather_facts: true
  become: false  # Run as regular user; system packages must be pre-installed
  tags:
    - always
    - bootstrap
  collections:
    - community.crypto
  vars:
    control_node_project_root: "{{ playbook_dir }}"
    control_node_collection_requirements: "{{ [playbook_dir, 'collections', 'requirements.yml'] | path_join }}"
  pre_tasks:
    - name: Ensure Python dependencies are installed via uv
      ansible.builtin.command:
        cmd: uv sync
        chdir: "{{ playbook_dir }}"
      changed_when: false
  roles:
    - base/control_node_bootstrap
```

- [ ] **Step 2: Remove pip-related tasks from control_node_bootstrap role**

In `playbooks/roles/base/control_node_bootstrap/tasks/main.yml`, remove these four task blocks entirely:

1. The `Derive control node Python tooling paths` task:
```yaml
- name: Derive control node Python tooling paths
  ansible.builtin.set_fact:
    control_node_pip_virtualenv: "{{ control_node_pip_virtualenv | default(([control_node_project_root, '.ansible', 'venv'] | path_join), true) }}"
    control_node_pip_virtualenv_command: "{{ control_node_pip_virtualenv_command | default('python3 -m venv', true) }}"
```

2. The `control_node_pip_requirements` line inside `Derive control node paths` (leave the rest of that task intact):
```yaml
    control_node_pip_requirements: "{{ control_node_pip_requirements | default(([control_node_project_root, 'requirements', 'pip.txt'] | path_join)) }}"
```

3. The `Check pip requirements file` task and its companion `Fail when pip requirements file is missing` task:
```yaml
- name: Check pip requirements file
  ansible.builtin.stat:
    path: "{{ control_node_pip_requirements }}"
  register: control_node_pip_requirements_stat

- name: Fail when pip requirements file is missing
  ansible.builtin.fail:
    msg: "Pip requirements file {{ control_node_pip_requirements }} is missing."
  when: not control_node_pip_requirements_stat.stat.exists
```

4. The entire `Install Python dependencies for control node` task:
```yaml
- name: Install Python dependencies for control node
  vars:
    control_node_pip_use_virtualenv: "{{ (control_node_pip_executable | default('', true)) | length == 0 }}"
    control_node_pip_virtualenv_python_required: "{{ control_node_pip_virtualenv_python is defined and (control_node_pip_virtualenv_python | default('', true)) | length > 0 and control_node_pip_virtualenv_command is defined and 'virtualenv' in control_node_pip_virtualenv_command }}"
  ansible.builtin.pip:
    requirements: "{{ control_node_pip_requirements }}"
    extra_args: "{{ control_node_pip_extra_args | default(omit, true) }}"
    executable: "{{ control_node_pip_executable | default(omit, true) }}"
    virtualenv: "{{ control_node_pip_virtualenv if control_node_pip_use_virtualenv else omit }}"
    virtualenv_command: "{{ control_node_pip_virtualenv_command | default(omit, true) if control_node_pip_use_virtualenv else omit }}"
    virtualenv_python: "{{ control_node_pip_virtualenv_python if control_node_pip_use_virtualenv and control_node_pip_virtualenv_python_required else omit }}"
    virtualenv_site_packages: "{{ control_node_pip_virtualenv_site_packages | default(omit, true) if control_node_pip_use_virtualenv else omit }}"
  become: "{{ control_node_pip_become }}"
```

- [ ] **Step 3: Clean up pip-related defaults**

In `playbooks/roles/base/control_node_bootstrap/defaults/main.yml`, replace the full file with:

```yaml
---
control_node_packages:
  - sshpass  # Required for initial SSH key setup to Proxmox hosts
control_node_package_become: true
control_node_skip_system_packages: true  # Skip by default; pre-install packages on workstation
control_node_collection_force: false
control_node_collection_install_options: ""
control_node_ssh_key_type: ed25519
control_node_ssh_key_size: null  # ed25519 has fixed size, no size parameter needed
control_node_ssh_key_comment: ansible-control
```

- [ ] **Step 4: Delete requirements/pip.txt**

```bash
git rm requirements/pip.txt
```

- [ ] **Step 5: Verify bootstrap.yml runs cleanly**

```bash
.venv/bin/ansible-playbook bootstrap.yml
```

Expected: playbook completes with no failures. The `uv sync` pre-task reports `ok`.

- [ ] **Step 6: Commit**

```bash
git add bootstrap.yml playbooks/roles/base/control_node_bootstrap/tasks/main.yml playbooks/roles/base/control_node_bootstrap/defaults/main.yml
git commit -m "feat(bootstrap): replace pip install with uv in bootstrap role"
```

---

### Task 5: Update helper scripts

**Files:**
- Modify: `activate-env.sh`
- Modify: `run.sh`

- [ ] **Step 1: Update activate-env.sh**

Replace the full file content:

```bash
#!/bin/bash
# Activate local Ansible environment (project-portable setup)
# Usage: source activate-env.sh

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$PROJECT_ROOT/.venv"

if [ -f "$VENV_PATH/bin/activate" ]; then
    source "$VENV_PATH/bin/activate"
    echo "✓ Activated Ansible venv at $VENV_PATH"
    echo "  Python: $(which python3)"
    echo "  Ansible: $(ansible --version | head -n1)"
else
    echo "✗ Virtual environment not found at $VENV_PATH"
    echo "  Run './setup.sh' to initialize the project"
    return 1
fi
```

- [ ] **Step 2: Update run.sh**

Replace the venv path block:

Find:
```bash
# Activate venv
VENV_PATH=".ansible/venv"
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo "✗ Virtual environment not found at $VENV_PATH"
    echo "  Run ./setup.sh first to initialize the project"
    exit 1
fi

source "$VENV_PATH/bin/activate"
```

Replace with:
```bash
# Activate venv
VENV_PATH=".venv"
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo "✗ Virtual environment not found at $VENV_PATH"
    echo "  Run ./setup.sh first to initialize the project"
    exit 1
fi

source "$VENV_PATH/bin/activate"
```

- [ ] **Step 3: Verify no remaining .ansible/venv references in scripts**

```bash
grep -n "ansible/venv" activate-env.sh run.sh
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add activate-env.sh run.sh
git commit -m "feat(bootstrap): update helper scripts to .venv path"
```

---

### Task 6: Update documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`

- [ ] **Step 1: Update AGENTS.md venv path and bootstrap command**

Find in `AGENTS.md`:
```
| Venv | `.ansible/venv/` (project-relative, gitignored) |
```
Replace with:
```
| Venv | `.venv/` (project-relative, gitignored) |
```

Find in `AGENTS.md`:
```
- The venv is on `PATH` automatically. If it doesn't exist yet, run `ansible-playbook bootstrap.yml` to create it.
```
Replace with:
```
- The venv is on `PATH` automatically via direnv (`layout uv`). If it doesn't exist yet, run `./setup.sh` to initialize the project, or `uv sync` if setup has already been run.
```

Find in `AGENTS.md` command table:
```
| `ansible-playbook bootstrap.yml` | Recreate venv + SSH keys after clean install |
```
Replace with:
```
| `uv sync && ansible-playbook bootstrap.yml` | Recreate venv + SSH keys after clean install |
```

- [ ] **Step 2: Update README.md**

Apply these replacements throughout `README.md`:

1. Replace all occurrences of `.ansible/venv` with `.venv`

2. Replace the manual venv creation block (in the manual setup section):
```bash
python3 -m venv .ansible/venv
source .ansible/venv/bin/activate
```
With:
```bash
uv sync
```

3. Replace references to `python3-venv` and `python3-pip` as required packages with `uv`. Find lines like:
```
sudo apt install -y python3-venv python3-pip sshpass
```
Replace with:
```
sudo apt install -y sshpass
curl -LsSf https://astral.sh/uv/install.sh | sh
```

4. Replace `requirements/pip.txt` references with `pyproject.toml`.

5. Update the `pip.txt` line in the directory tree (if present):
```
|   `-- pip.txt                        # Python package dependencies
```
Replace with:
```
|   `-- pyproject.toml                 # Python package dependencies
```

- [ ] **Step 3: Verify no remaining stale references**

```bash
grep -n "ansible/venv\|pip\.txt\|python3-venv\|python3-pip\|m venv" AGENTS.md README.md
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md README.md
git commit -m "docs: update venv path and bootstrap instructions for uv migration"
```
