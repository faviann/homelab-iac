# Authentik Blueprint Apply Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate `authentik_blueprint_sync.py apply` as part of `site.yml` so every deploy enforces the repo's blueprint state in authentik without a manual follow-up step.

**Architecture:** A new role `config/authentik_blueprint_sync` runs on the controller after `config/lxc_docker_environment` deploys blueprint files. It waits for authentik's health endpoint, writes a vault-sourced token to a tempfile, calls the existing apply script, and removes the tempfile. A bootstrap token env var ensures the token exists on first deploy without manual UI interaction.

**Tech Stack:** Ansible (`ansible.builtin.uri`, `ansible.builtin.tempfile`, `ansible.builtin.command`), existing `scripts/authentik_blueprint_sync.py`, Ansible Vault.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `playbooks/roles/config/authentik_blueprint_sync/defaults/main.yml` | Role defaults (url, token, enabled flag) |
| Create | `playbooks/roles/config/authentik_blueprint_sync/tasks/main.yml` | Healthcheck wait → tempfile → apply script → cleanup |
| Modify | `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml` | Wire new role in after `lxc_docker_environment` |
| Modify | `inventory/host_vars/auth.yml` | Enable role, bind vault token, add stack_var |
| Modify | `stacks/auth/auth/.env.j2` | Inject `AUTHENTIK_BOOTSTRAP_TOKEN` for first-deploy |
| Modify | `inventory/group_vars/all/vault.yml` | Add `vault_auth_blueprint_api_token` (encrypted) |

---

## Task 1: Add vault token

**Files:**
- Modify: `inventory/group_vars/all/vault.yml`

- [ ] **Step 1: Generate a token value**

```bash
openssl rand -hex 32
```

Copy the output. This is your token value — treat it as a secret.

- [ ] **Step 2: Add it to vault**

```bash
ansible-vault edit inventory/group_vars/all/vault.yml
```

Add this line at the end of the file (replace `<token>` with the value from step 1):

```yaml
vault_auth_blueprint_api_token: "<token>"
```

Save and close. The file stays encrypted on disk.

- [ ] **Step 3: Verify vault can read it**

```bash
ansible -i inventory/hosts.yml localhost -m debug \
  -a "var=vault_auth_blueprint_api_token" \
  -e "@inventory/group_vars/all/vault.yml"
```

Expected: the decrypted token value prints. If you see `VARIABLE IS NOT DEFINED`, the key name is wrong.

- [ ] **Step 4: Commit**

```bash
git add inventory/group_vars/all/vault.yml
git commit -m "feat(auth): add vault_auth_blueprint_api_token for blueprint automation"
```

---

## Task 2: Wire bootstrap token into auth stack

**Files:**
- Modify: `stacks/auth/auth/.env.j2` (add one line)
- Modify: `inventory/host_vars/auth.yml` (add to `lxc_docker_env_stack_vars.auth`)

- [ ] **Step 1: Add bootstrap token to `.env.j2`**

Open `stacks/auth/auth/.env.j2`. Add this line at the end:

```
AUTHENTIK_BOOTSTRAP_TOKEN={{ stack_vars.blueprint_api_token | replace('$', '$$') }}
```

- [ ] **Step 2: Add `blueprint_api_token` to auth stack_vars in `inventory/host_vars/auth.yml`**

In `lxc_docker_env_stack_vars.auth`, add one entry alongside the existing keys:

```yaml
lxc_docker_env_stack_vars:
  auth:
    # ... existing entries ...
    blueprint_api_token: "{{ vault_auth_blueprint_api_token }}"
```

- [ ] **Step 3: Verify template renders**

```bash
ansible -i inventory/hosts.yml auth -m debug \
  -a "var=lxc_docker_env_stack_vars.auth.blueprint_api_token"
```

Expected: the decrypted token value. If you see `None` or undefined, check the vault key name matches exactly.

- [ ] **Step 4: Commit**

```bash
git add stacks/auth/auth/.env.j2 inventory/host_vars/auth.yml
git commit -m "feat(auth): inject AUTHENTIK_BOOTSTRAP_TOKEN for first-deploy automation"
```

---

## Task 3: Create `config/authentik_blueprint_sync` role

**Files:**
- Create: `playbooks/roles/config/authentik_blueprint_sync/defaults/main.yml`
- Create: `playbooks/roles/config/authentik_blueprint_sync/tasks/main.yml`

- [ ] **Step 1: Create defaults**

Create `playbooks/roles/config/authentik_blueprint_sync/defaults/main.yml`:

```yaml
---
authentik_blueprint_sync_enabled: false
authentik_blueprint_sync_url: "http://auth.faviann.vms:9000"
authentik_blueprint_api_token: ""
```

- [ ] **Step 2: Create tasks**

Create `playbooks/roles/config/authentik_blueprint_sync/tasks/main.yml`:

```yaml
---
- name: Wait for Authentik API to be ready
  ansible.builtin.uri:
    url: "{{ authentik_blueprint_sync_url }}/api/v3/-/healthcheck/"
    status_code: 200
  register: _authentik_health
  delegate_to: localhost
  become: false
  retries: 30
  delay: 10
  until: _authentik_health is not failed

- name: Apply Authentik blueprints
  block:
    - name: Create temporary token file
      ansible.builtin.tempfile:
        state: file
        suffix: .token
      register: _authentik_token_file
      delegate_to: localhost
      become: false

    - name: Write token to tempfile
      ansible.builtin.copy:
        content: "{{ authentik_blueprint_api_token }}"
        dest: "{{ _authentik_token_file.path }}"
        mode: '0600'
      delegate_to: localhost
      become: false
      no_log: true

    - name: Run blueprint apply script
      ansible.builtin.command:
        cmd: >-
          python3 {{ playbook_dir }}/scripts/authentik_blueprint_sync.py
          apply --token-file {{ _authentik_token_file.path }}
          --base-url {{ authentik_blueprint_sync_url }}
      delegate_to: localhost
      become: false
      changed_when: true

  always:
    - name: Remove temporary token file
      ansible.builtin.file:
        path: "{{ _authentik_token_file.path }}"
        state: absent
      delegate_to: localhost
      become: false
      when: _authentik_token_file.path is defined
```

- [ ] **Step 3: Syntax-check the role**

```bash
ansible-playbook site.yml --limit auth --syntax-check
```

Expected: `playbook: site.yml` with no errors. Any YAML parse error will show here.

- [ ] **Step 4: Commit**

```bash
git add playbooks/roles/config/authentik_blueprint_sync/
git commit -m "feat(auth): add authentik_blueprint_sync role"
```

---

## Task 4: Wire role into configure.yml and enable on auth host

**Files:**
- Modify: `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml` (line 50–54)
- Modify: `inventory/host_vars/auth.yml`

- [ ] **Step 1: Add role call to `configure.yml`**

In `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml`, after the `Configure Docker environment` block (currently ends around line 54), add:

```yaml
    - name: Apply Authentik blueprints
      ansible.builtin.include_role:
        name: config/authentik_blueprint_sync
      when: authentik_blueprint_sync_enabled | default(false)
```

The resulting sequence should be:

```yaml
    - name: Configure Docker environment
      ansible.builtin.include_role:
        name: config/lxc_docker_environment
      when: docker_enabled | default(false)

    - name: Apply Authentik blueprints
      ansible.builtin.include_role:
        name: config/authentik_blueprint_sync
      when: authentik_blueprint_sync_enabled | default(false)

    - name: Configure workstation baseline
```

- [ ] **Step 2: Enable role on auth host in `inventory/host_vars/auth.yml`**

Add two top-level host vars (outside `lxc_docker_env_stack_vars`):

```yaml
authentik_blueprint_sync_enabled: true
authentik_blueprint_api_token: "{{ vault_auth_blueprint_api_token }}"
```

- [ ] **Step 3: Verify the var resolves**

```bash
ansible -i inventory/hosts.yml auth -m debug \
  -a "var=authentik_blueprint_sync_enabled"
```

Expected: `"authentik_blueprint_sync_enabled": true`

- [ ] **Step 4: Syntax-check again with all changes wired**

```bash
ansible-playbook site.yml --limit auth --syntax-check
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml \
        inventory/host_vars/auth.yml
git commit -m "feat(auth): wire authentik_blueprint_sync into configure lifecycle"
```

---

## Task 5: Deploy and verify

- [ ] **Step 1: Dry-run against auth host**

```bash
ansible-playbook site.yml --limit auth --check
```

Expected: plan output showing the new `Apply Authentik blueprints` tasks. The healthcheck and apply steps will show as skipped or `changed` in check mode — that's fine, they can't actually run without authentik being live. No errors in the role wiring.

- [ ] **Step 2: Deploy for real**

```bash
ansible-playbook site.yml --limit auth
```

Expected: all tasks complete. Look for:
- `Wait for Authentik API to be ready` → `ok`
- `Run blueprint apply script` → `changed` (always marks changed)

If the healthcheck times out (30 retries × 10s = 5 min), authentik is not reachable. Check `http://auth.faviann.vms:9000/api/v3/-/healthcheck/` from the workstation directly.

If the apply script fails, the full error is in the task output — the script exits non-zero with a descriptive message.

- [ ] **Step 3: Verify blueprints in authentik**

Open `https://auth.faviann.com/if/admin/#/core/blueprints` and confirm all `repo-auth-*` blueprint instances show status `Successful`.

- [ ] **Step 4: Verify drift correction works**

In the authentik UI, rename any group or disable any application. Then:

```bash
ansible-playbook site.yml --limit auth
```

Reload the authentik UI — the change should be reverted to match the repo state.

- [ ] **Step 5: Final commit (if any fixes needed)**

```bash
git add -p
git commit -m "fix(auth): <describe any adjustments made during verification>"
```

---

## Self-Review Checklist

- [x] **Vault token** — Task 1 generates and vaults it
- [x] **Bootstrap token in .env.j2** — Task 2 injects `AUTHENTIK_BOOTSTRAP_TOKEN`
- [x] **Role defaults** — Task 3 defines `authentik_blueprint_sync_enabled: false` so other hosts are unaffected
- [x] **Role tasks** — Task 3 covers healthcheck, tempfile, apply, always-cleanup
- [x] **`--base-url` flag** — passed to script so it doesn't auto-discover, uses the configured URL
- [x] **`no_log: true`** — on the token copy task to prevent vault values in output
- [x] **configure.yml wiring** — Task 4 adds include_role after lxc_docker_environment
- [x] **auth.yml host vars** — Task 4 sets enabled flag and token binding
- [x] **Drift verification** — Task 5 step 4 explicitly tests drift correction
- [x] **First-deploy path** — bootstrap token means no manual UI step ever
