# OpenClaw Workstation Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenClaw to the workstation LXC via the official `nix-openclaw` Home Manager module, with a persistent `~/.openclaw` state directory and an auto-starting systemd user gateway service.

**Architecture:** Two repos change. In `ServerManagementScripts`: add `~/.openclaw` to the Ansible persistent bind-mount list, update all tests, and add `openclaw --version` to the workstation-setup validation. In `~/repos/dotfiles`: wire `github:openclaw/nix-openclaw` as a flake input, import the Home Manager module, and declare `programs.openclaw` with a headless-safe `WantedBy` override in `home/workstation.nix`.

**Tech Stack:** Nix/Home Manager, `nix-openclaw` flake (`github:openclaw/nix-openclaw`), Ansible YAML, systemd user services, pytest + Ansible regression fixtures

---

## File Map

| Repo | File | Change |
|------|------|--------|
| ServerManagementScripts | `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml` | Add `openclaw` entry to `workstation_persistent_home_links` |
| ServerManagementScripts | `tests/unit/test_workstation_baseline_role.py` | Add openclaw to expected `workstation_persistent_home_links` list |
| ServerManagementScripts | `tests/regression/fixtures/workstation_persistent_home_success.yml` | Add openclaw to vars list + stat task + assertion |
| ServerManagementScripts | `tests/regression/fixtures/workstation_persistent_home_idempotency.yml` | Add openclaw to vars list |
| ServerManagementScripts | `tests/regression/fixtures/workstation_persistent_home_conflict.yml` | Add openclaw to vars list |
| ServerManagementScripts | `tests/regression/fixtures/workstation_persistent_home_disabled.yml` | Add openclaw to vars list |
| ServerManagementScripts | `tests/regression/fixtures/workstation_persistent_home_symlink_migration.yml` | Add openclaw to vars list |
| ServerManagementScripts | `tests/regression/fixtures/workstation_first_login_setup_contract.yml` | Add `openclaw --version` assertion |
| ServerManagementScripts | `playbooks/roles/config/lxc_workstation_baseline/templates/workstation-setup.sh.j2` | Add `openclaw --version >/dev/null` to `validate_environment` |
| dotfiles | `flake.nix` | Add `nix-openclaw` input; pass module to `modules` list |
| dotfiles | `home/workstation.nix` | Add `programs.openclaw` block + `systemd.user.services.openclaw-gateway` WantedBy override |

---

## Task 1: Extend unit test to expect openclaw (TDD — write failing test first)

**Files:**
- Modify: `tests/unit/test_workstation_baseline_role.py`

- [ ] **Step 1: Add openclaw to the expected `workstation_persistent_home_links` list in the unit test**

In `tests/unit/test_workstation_baseline_role.py`, find the `assertEqual` call that checks `workstation_persistent_home_links` (currently ends after the `repos` entry around line 77–84). Insert the openclaw entry before `repos` (after `hermes`):

```python
                {
                    "name": "openclaw",
                    "type": "bind_mount",
                    "path": "{{ workstation_home }}/.openclaw",
                    "target": "{{ workstation_persistent_home_root }}/.openclaw",
                    "mode": "0700",
                },
```

The final expected list order must be: `claude`, `codex`, `agent_of_empires`, `hermes`, `openclaw`, `repos`.

- [ ] **Step 2: Run the unit test — verify it FAILS**

```bash
cd /home/aperture/ServerManagementScripts && uv run --locked pytest tests/unit/test_workstation_baseline_role.py -v
```

Expected: `FAILED` — `AssertionError` because defaults don't have `openclaw` yet.

---

## Task 2: Add openclaw to Ansible persistent home defaults

**Files:**
- Modify: `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml`

- [ ] **Step 1: Add the openclaw entry to `workstation_persistent_home_links`**

In `defaults/main.yml`, insert after the `hermes` entry (line 30–34) and before `repos`:

```yaml
  - name: openclaw
    type: bind_mount
    path: "{{ workstation_home }}/.openclaw"
    target: "{{ workstation_persistent_home_root }}/.openclaw"
    mode: "0700"
```

- [ ] **Step 2: Run the unit test — verify it PASSES**

```bash
cd /home/aperture/ServerManagementScripts && uv run --locked pytest tests/unit/test_workstation_baseline_role.py -v
```

Expected: `PASSED`.

- [ ] **Step 3: Commit**

```bash
cd /home/aperture/ServerManagementScripts
git add playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml tests/unit/test_workstation_baseline_role.py
git commit -m "feat(workstation): add ~/.openclaw to persistent home bind mounts"
```

---

## Task 3: Update regression fixtures — persistent home

**Files:**
- Modify: 5 regression fixtures in `tests/regression/fixtures/`

Each fixture defines `workstation_persistent_home_links` in its `vars:` block. Add the openclaw entry (same shape as hermes) after the hermes entry in every fixture. The `success` fixture also needs a stat task and assertion.

- [ ] **Step 1: Update `workstation_persistent_home_success.yml` vars list**

Find the `hermes` entry block and add after it:

```yaml
      - name: openclaw
        type: bind_mount
        path: "{{ workstation_home }}/.openclaw"
        target: "{{ workstation_persistent_home_root }}/.openclaw"
        mode: "0700"
```

- [ ] **Step 2: Add stat task for openclaw in `workstation_persistent_home_success.yml`**

After the `Stat Hermes persistent home directory` task, add:

```yaml
    - name: Stat OpenClaw persistent home directory
      ansible.builtin.stat:
        path: "{{ temp_root }}/ephemeral/workstation/home/.openclaw"
      register: openclaw_state_dir_stat

    - name: Stat OpenClaw home path
      ansible.builtin.stat:
        path: "{{ workstation_home }}/.openclaw"
      register: openclaw_home_path_stat
```

- [ ] **Step 3: Add assertions for openclaw in `workstation_persistent_home_success.yml`**

Inside the existing `ansible.builtin.assert` task's `that:` list, add after the hermes assertions:

```yaml
          - openclaw_state_dir_stat.stat.isdir
          - openclaw_state_dir_stat.stat.uid == workstation_uid
          - openclaw_state_dir_stat.stat.gid == workstation_gid
          - openclaw_state_dir_stat.stat.mode == "0700"
          - openclaw_home_path_stat.stat.isdir
          - not (openclaw_home_path_stat.stat.islnk | default(false))
```

- [ ] **Step 4: Add openclaw to the remaining 4 fixtures' vars lists**

In each of these files, find the `hermes` entry under `workstation_persistent_home_links:` and add the openclaw entry immediately after:

```yaml
      - name: openclaw
        type: bind_mount
        path: "{{ workstation_home }}/.openclaw"
        target: "{{ workstation_persistent_home_root }}/.openclaw"
        mode: "0700"
```

Files to update:
- `tests/regression/fixtures/workstation_persistent_home_idempotency.yml`
- `tests/regression/fixtures/workstation_persistent_home_conflict.yml`
- `tests/regression/fixtures/workstation_persistent_home_disabled.yml`
- `tests/regression/fixtures/workstation_persistent_home_symlink_migration.yml`

- [ ] **Step 5: Run regression tests — verify they PASS**

```bash
cd /home/aperture/ServerManagementScripts && uv run --locked pytest tests/regression/ -v -k "persistent_home"
```

Expected: all persistent home regression tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/aperture/ServerManagementScripts
git add tests/regression/fixtures/
git commit -m "test(workstation): add openclaw to persistent home regression fixtures"
```

---

## Task 4: Add openclaw to workstation-setup validation

**Files:**
- Modify: `playbooks/roles/config/lxc_workstation_baseline/templates/workstation-setup.sh.j2`
- Modify: `tests/regression/fixtures/workstation_first_login_setup_contract.yml`

- [ ] **Step 1: Add `openclaw --version` check to the login-contract test (TDD — fail first)**

In `tests/regression/fixtures/workstation_first_login_setup_contract.yml`, find the `assert` block that checks `(setup_command_raw.content | b64decode) is search('hermes version')` (line ~122). Add after it:

```yaml
          - (setup_command_raw.content | b64decode) is search('openclaw --version')
```

- [ ] **Step 2: Run the contract test — verify it FAILS**

```bash
cd /home/aperture/ServerManagementScripts && uv run --locked pytest tests/regression/ -v -k "first_login"
```

Expected: `FAILED` — `openclaw --version` not yet in the rendered script.

- [ ] **Step 3: Add openclaw check to `workstation-setup.sh.j2`**

In `workstation-setup.sh.j2`, find `validate_environment()`. After the `hermes version >/dev/null` line (line ~147), add:

```bash
  openclaw --version >/dev/null
```

- [ ] **Step 4: Run the contract test — verify it PASSES**

```bash
cd /home/aperture/ServerManagementScripts && uv run --locked pytest tests/regression/ -v -k "first_login"
```

Expected: `PASSED`.

- [ ] **Step 5: Run the full test suite to catch regressions**

```bash
cd /home/aperture/ServerManagementScripts && uv run --locked pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/aperture/ServerManagementScripts
git add playbooks/roles/config/lxc_workstation_baseline/templates/workstation-setup.sh.j2 \
        tests/regression/fixtures/workstation_first_login_setup_contract.yml
git commit -m "feat(workstation): add openclaw to workstation-setup environment validation"
```

---

## Task 5: Add nix-openclaw flake input (dotfiles repo)

**Files:**
- Modify: `~/repos/dotfiles/flake.nix`

- [ ] **Step 1: Add `nix-openclaw` input and wire the module**

Replace the contents of `~/repos/dotfiles/flake.nix` with:

```nix
{
  description = "Personal workstation Home Manager configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager/master";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    hermes-agent.url = "github:NousResearch/hermes-agent";
    nix-openclaw.url = "github:openclaw/nix-openclaw";
  };

  outputs =
    {
      nixpkgs,
      home-manager,
      hermes-agent,
      nix-openclaw,
      ...
    }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
      };
    in
    {
      homeConfigurations.workstation = home-manager.lib.homeManagerConfiguration {
        inherit pkgs;
        extraSpecialArgs = {
          hermesPackage = hermes-agent.packages.${system}.default;
        };
        modules = [
          nix-openclaw.homeManagerModules.openclaw
          ./home/workstation.nix
        ];
      };
    };
}
```

- [ ] **Step 2: Verify the flake evaluates and builds (fetches nix-openclaw, updates flake.lock)**

```bash
cd ~/repos/dotfiles && nix build .#homeConfigurations.workstation.activationPackage --no-link 2>&1 | tail -20
```

Expected: build succeeds (exit 0). `flake.lock` will be updated to pin `nix-openclaw`.

- [ ] **Step 3: Commit flake.nix and the updated flake.lock**

```bash
cd ~/repos/dotfiles
git add flake.nix flake.lock
git commit -m "feat(workstation): add nix-openclaw flake input"
```

---

## Task 6: Declare programs.openclaw in workstation.nix (dotfiles repo)

**Files:**
- Modify: `~/repos/dotfiles/home/workstation.nix`

- [ ] **Step 1: Add the `programs.openclaw` block and WantedBy override**

In `~/repos/dotfiles/home/workstation.nix`, add after the `hermes-dashboard` service block (before the closing `}`):

```nix
  programs.openclaw = {
    enable = true;
    stateDir = "~/.openclaw";
    systemd.enable = true;
    systemd.unitName = "openclaw-gateway";
  };

  # The nix-openclaw module targets graphical-session.target by default.
  # Override to default.target for headless LXC (same pattern as hermes-gateway).
  systemd.user.services.openclaw-gateway = {
    Install.WantedBy = lib.mkForce [ "default.target" ];
  };
```

The `lib` argument is already in scope (`{ pkgs, lib, hermesPackage, ... }:`).

- [ ] **Step 2: Verify the build still passes**

```bash
cd ~/repos/dotfiles && nix build .#homeConfigurations.workstation.activationPackage --no-link 2>&1 | tail -20
```

Expected: build succeeds (exit 0).

- [ ] **Step 3: Commit**

```bash
cd ~/repos/dotfiles
git add home/workstation.nix
git commit -m "feat(workstation): enable openclaw gateway via nix-openclaw Home Manager module"
```

---

## Verification (after applying to live LXC)

```bash
# 1. Apply Ansible changes (adds persistent bind mount)
uv run --locked ansible-playbook site.yml --limit workstation

# 2. SSH into workstation and run setup
ssh -l faviann workstation.faviann.vms
workstation-setup        # home-manager switch installs openclaw + starts service

# 3. Check binary
openclaw --version

# 4. Check service
systemctl --user status openclaw-gateway

# 5. First-time onboarding (run once; state persists in ~/.openclaw)
openclaw onboard

# 6. Verify gateway
openclaw gateway status
openclaw doctor
```
