# Design: uv-based Python Environment Setup

**Date**: 2026-04-28  
**Status**: Approved

## Goal

Reduce cognitive load for workstation onboarding. After this change, the only prerequisite a fresh workstation needs before running `./setup.sh` is `~/.ansible/vault-pass` (provisioned by chezmoi+Bitwarden — outside this repo's scope). The Python environment is fully self-bootstrapping.

Secondary goal: agents find the correct Python interpreter without special-casing.

## What Changes

### 1. Python environment tooling

Replace pip+venv with `uv`. Dependencies move from `requirements/pip.txt` to `pyproject.toml`.

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

`requirements/pip.txt` is deleted.

The venv moves from `.ansible/venv/` to `.venv/` — the conventional location auto-discovered by VS Code, pytest, and agents without configuration.

### 2. `.envrc`

```bash
layout uv
```

`layout uv` (direnv ≥ 2.33) calls `uv sync` automatically on `cd` and exports `PATH`/`VIRTUAL_ENV` as real environment variables, so both interactive shells and spawned subprocesses inherit the environment. Agents running in the user's shell context and tools that auto-discover `.venv/` both benefit.

### 3. `setup.sh`

- **Remove** `python3-venv` and `python3-pip` from required system packages.
- **Add** uv self-installation: check `command -v uv`; if missing, install via `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Replace** the manual venv creation + `pip install` block with a single `uv sync` call.
- All other steps (vault password check, Proxmox credential prompts, vault encryption, skills linking, VS Code config, direnv shell hook) are unchanged.

### 4. `bootstrap.yml` and `control_node_bootstrap` role

`bootstrap.yml` is documented as a standalone recovery command. To preserve this:

- Add a `uv sync` shell task at the top of `bootstrap.yml`, before the role runs.
- Remove pip/venv installation tasks from the `control_node_bootstrap` role (redundant — uv handles this).
- Update hardcoded `.ansible/venv/` path references in the role to `.venv/`.
- Keep everything else: directory creation, Ansible collections install, SSH key generation, vault password verification.

## What Does Not Change

- Secrets management stays in chezmoi+Bitwarden dotfiles. This repo expects `~/.ansible/vault-pass` to exist and fails loudly if it doesn't. No duplication of secrets logic.
- Proxmox API credential prompts in `setup.sh` are unchanged.
- direnv remains a system prerequisite.

## Agent Experience

| Before | After |
|--------|-------|
| Venv at `.ansible/venv/` — non-standard, not auto-discovered | Venv at `.venv/` — conventional, auto-discovered |
| Agent had to "switch to workspace Python" | Agent finds correct interpreter first try |
| `source activate` only affects current shell | `layout uv` exports PATH to all subprocesses |
