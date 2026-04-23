# LXC GitHub SSH Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the owner's GitHub public SSH keys to all LXC containers so non-root SSH access works on every host.

**Architecture:** Extract key-fetch logic from `lxc_workstation_baseline` into a new standalone `config/lxc_github_keys` role. Wire it unconditionally into the configure play. `lxc_workstation_baseline` delegates to the new role instead of duplicating the logic.

**Tech Stack:** Ansible, `ansible.builtin.command` (curl), `ansible.builtin.copy`, pytest for regression test runners, YAML fixture playbooks.

---

## File Map

| Action | Path |
|--------|------|
| Create | `playbooks/roles/config/lxc_github_keys/defaults/main.yml` |
| Create | `playbooks/roles/config/lxc_github_keys/tasks/main.yml` |
| Create | `playbooks/roles/config/lxc_github_keys/meta/argument_specs.yml` |
| Create | `tests/regression/fixtures/lxc_github_keys_single_user_test.yml` |
| Create | `tests/regression/fixtures/lxc_github_keys_multi_user_dedup_test.yml` |
| Create | `tests/regression/fixtures/lxc_github_keys_empty_users_test.yml` |
| Create | `tests/regression/test_lxc_github_keys.py` |
| Modify | `playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml` |
| Modify | `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml` |
| Modify | `playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml` |
| Modify | `tests/regression/fixtures/workstation_baseline_github_keys_test.yml` |
| Modify | `tests/regression/fixtures/workstation_baseline_empty_github_keys_test.yml` |
| Modify | `tests/regression/test_workstation_baseline_github_keys.py` |
| Modify | `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml` |
| Modify | `inventory/group_vars/lxcs/vars.yml` |
| Modify | `inventory/host_vars/workstation.yml` |

---

## Task 1: Write failing tests for `config/lxc_github_keys`

**Files:**
- Create: `tests/regression/fixtures/lxc_github_keys_single_user_test.yml`
- Create: `tests/regression/fixtures/lxc_github_keys_multi_user_dedup_test.yml`
- Create: `tests/regression/fixtures/lxc_github_keys_empty_users_test.yml`
- Create: `tests/regression/test_lxc_github_keys.py`

- [ ] **Step 1: Write single-user fixture**

Create `tests/regression/fixtures/lxc_github_keys_single_user_test.yml`:

```yaml
---
- name: Test lxc_github_keys single user key population
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    lxc_ssh_user: faviann
    lxc_ssh_uid: "{{ lookup('pipe', 'id -u') | int }}"
    lxc_ssh_gid: "{{ lookup('pipe', 'id -g') | int }}"
    lxc_github_keys_home: "{{ temp_root }}/home/faviann"
    lxc_github_users:
      - faviann
  tasks:
    - name: Place mock curl on PATH
      ansible.builtin.copy:
        dest: "{{ temp_root }}/curl"
        mode: "0755"
        content: |
          #!/bin/sh
          printf '%s\n' 'ssh-ed25519 AAAATESTKEYONE faviann@laptop'

    - name: Include lxc_github_keys role with mock curl on PATH
      block:
        - ansible.builtin.include_role:
            name: config/lxc_github_keys
      environment:
        PATH: "{{ temp_root }}:{{ lookup('env', 'PATH') }}"

    - name: Stat SSH directory
      ansible.builtin.stat:
        path: "{{ lxc_github_keys_home }}/.ssh"
      register: ssh_dir_stat

    - name: Stat authorized_keys
      ansible.builtin.stat:
        path: "{{ lxc_github_keys_home }}/.ssh/authorized_keys"
      register: authorized_keys_stat

    - name: Read authorized_keys
      ansible.builtin.slurp:
        src: "{{ lxc_github_keys_home }}/.ssh/authorized_keys"
      register: authorized_keys_content

    - name: Assert keys written with correct ownership and modes
      ansible.builtin.assert:
        that:
          - ssh_dir_stat.stat.uid == lxc_ssh_uid
          - ssh_dir_stat.stat.gid == lxc_ssh_gid
          - ssh_dir_stat.stat.mode == "0700"
          - authorized_keys_stat.stat.uid == lxc_ssh_uid
          - authorized_keys_stat.stat.gid == lxc_ssh_gid
          - authorized_keys_stat.stat.mode == "0600"
          - (authorized_keys_content.content | b64decode) == "ssh-ed25519 AAAATESTKEYONE faviann@laptop\n"
        fail_msg: "lxc_github_keys did not write the expected keys with correct ownership and modes"
```

- [ ] **Step 2: Write multi-user dedup fixture**

Create `tests/regression/fixtures/lxc_github_keys_multi_user_dedup_test.yml`:

```yaml
---
- name: Test lxc_github_keys multi-user deduplication
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    lxc_ssh_user: faviann
    lxc_ssh_uid: "{{ lookup('pipe', 'id -u') | int }}"
    lxc_ssh_gid: "{{ lookup('pipe', 'id -g') | int }}"
    lxc_github_keys_home: "{{ temp_root }}/home/faviann"
    lxc_github_users:
      - faviann
      - aperture
  tasks:
    - name: Place mock curl on PATH
      ansible.builtin.copy:
        dest: "{{ temp_root }}/curl"
        mode: "0755"
        content: |
          #!/bin/sh
          url=""
          for arg in "$@"; do
            case "$arg" in
              http://*|https://*)
                url="$arg"
                ;;
            esac
          done
          case "$url" in
            *faviann.keys)
              printf '%s\n' \
                'ssh-ed25519 AAAATESTKEYONE faviann@laptop' \
                'ssh-ed25519 AAAATESTKEYONE faviann@laptop'
              ;;
            *aperture.keys)
              printf '%s\n' \
                'ssh-ed25519 AAAATESTKEYTWO faviann@phone'
              ;;
            *)
              echo "unexpected curl url: $url" >&2
              exit 1
              ;;
          esac

    - name: Include lxc_github_keys role with mock curl on PATH
      block:
        - ansible.builtin.include_role:
            name: config/lxc_github_keys
      environment:
        PATH: "{{ temp_root }}:{{ lookup('env', 'PATH') }}"

    - name: Read authorized_keys
      ansible.builtin.slurp:
        src: "{{ lxc_github_keys_home }}/.ssh/authorized_keys"
      register: authorized_keys_content

    - name: Assert keys from both users merged and deduplicated
      ansible.builtin.assert:
        that:
          - (authorized_keys_content.content | b64decode) == "ssh-ed25519 AAAATESTKEYONE faviann@laptop\nssh-ed25519 AAAATESTKEYTWO faviann@phone\n"
        fail_msg: "lxc_github_keys did not correctly merge and deduplicate keys from multiple users"
```

- [ ] **Step 3: Write empty-users fixture**

Create `tests/regression/fixtures/lxc_github_keys_empty_users_test.yml`:

```yaml
---
- name: Test lxc_github_keys fails fast with empty users list
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    lxc_ssh_user: faviann
    lxc_ssh_uid: "{{ lookup('pipe', 'id -u') | int }}"
    lxc_ssh_gid: "{{ lookup('pipe', 'id -g') | int }}"
    lxc_github_keys_home: "{{ temp_root }}/home/faviann"
    lxc_github_users: []
  tasks:
    - name: Include lxc_github_keys role with empty users list
      block:
        - ansible.builtin.include_role:
            name: config/lxc_github_keys
```

- [ ] **Step 4: Write test runner**

Create `tests/regression/test_lxc_github_keys.py`:

```python
#!/usr/bin/env python3
"""Regression tests for config/lxc_github_keys role."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SINGLE_USER_PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "lxc_github_keys_single_user_test.yml"
MULTI_USER_PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "lxc_github_keys_multi_user_dedup_test.yml"
EMPTY_USERS_PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "lxc_github_keys_empty_users_test.yml"
ANSIBLE_PLAYBOOK = REPO_ROOT / ".ansible" / "venv" / "bin" / "ansible-playbook"


def run_playbook(playbook: Path, temp_root: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ANSIBLE_PLAYBOOK), str(playbook), "-f", "1", "-e", f"temp_root={temp_root}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def main() -> int:
    if not ANSIBLE_PLAYBOOK.exists():
        print(f"missing ansible-playbook at {ANSIBLE_PLAYBOOK}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="lxc-github-keys-single-") as temp_root:
        single = run_playbook(SINGLE_USER_PLAYBOOK, temp_root)

    if single.returncode != 0:
        print("single-user playbook failed unexpectedly", file=sys.stderr)
        print(f"{single.stdout}\n{single.stderr}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="lxc-github-keys-multi-") as temp_root:
        multi = run_playbook(MULTI_USER_PLAYBOOK, temp_root)

    if multi.returncode != 0:
        print("multi-user dedup playbook failed unexpectedly", file=sys.stderr)
        print(f"{multi.stdout}\n{multi.stderr}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="lxc-github-keys-empty-") as temp_root:
        empty = run_playbook(EMPTY_USERS_PLAYBOOK, temp_root)

    empty_output = f"{empty.stdout}\n{empty.stderr}"
    if empty.returncode == 0:
        print("empty-users playbook succeeded unexpectedly", file=sys.stderr)
        print(empty_output, file=sys.stderr)
        return 1

    markers = ["lxc_github_keys_github_users", "non-empty"]
    missing = [m for m in markers if m not in empty_output]
    if missing:
        print(f"empty-users playbook output missed expected fragments: {missing}", file=sys.stderr)
        print(empty_output, file=sys.stderr)
        return 1

    print("ok: lxc_github_keys writes keys correctly and fails clearly on empty users")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests — confirm they fail**

```bash
python3 tests/regression/test_lxc_github_keys.py
```

Expected: non-zero exit, error mentioning role `config/lxc_github_keys` not found.

---

## Task 2: Create `config/lxc_github_keys` role

**Files:**
- Create: `playbooks/roles/config/lxc_github_keys/defaults/main.yml`
- Create: `playbooks/roles/config/lxc_github_keys/tasks/main.yml`
- Create: `playbooks/roles/config/lxc_github_keys/meta/argument_specs.yml`

- [ ] **Step 1: Write defaults**

Create `playbooks/roles/config/lxc_github_keys/defaults/main.yml`:

```yaml
---
lxc_github_keys_user: "{{ docker_user | default(lxc_ssh_user) }}"
lxc_github_keys_uid: "{{ docker_uid | default(lxc_ssh_uid) }}"
lxc_github_keys_gid: "{{ docker_gid | default(lxc_ssh_gid) }}"
lxc_github_keys_github_users: "{{ lxc_github_users }}"
lxc_github_keys_base_url: "https://github.com"
lxc_github_keys_home: "/home/{{ lxc_github_keys_user }}"
```

- [ ] **Step 2: Write tasks**

Create `playbooks/roles/config/lxc_github_keys/tasks/main.yml`:

```yaml
---
- name: Assert lxc_github_keys inputs are present
  ansible.builtin.assert:
    that:
      - lxc_github_keys_github_users | length > 0
    fail_msg: >-
      config/lxc_github_keys requires a non-empty lxc_github_keys_github_users list.
      Set lxc_github_users in group_vars/lxcs/ or override lxc_github_keys_github_users.

- name: Ensure SSH directory exists
  ansible.builtin.file:
    path: "{{ lxc_github_keys_home }}/.ssh"
    state: directory
    mode: "0700"
    owner: "{{ lxc_github_keys_uid | string }}"
    group: "{{ lxc_github_keys_gid | string }}"

- name: Fetch GitHub public keys
  ansible.builtin.command:
    argv:
      - curl
      - -fsSL
      - "{{ lxc_github_keys_base_url }}/{{ item }}.keys"
  loop: "{{ lxc_github_keys_github_users }}"
  register: lxc_github_keys_fetch
  changed_when: false
  when: not ansible_check_mode

- name: Build authorized SSH keys
  ansible.builtin.set_fact:
    lxc_github_keys_authorized: >-
      {{
        lxc_github_keys_fetch.results
        | map(attribute='stdout_lines')
        | flatten
        | map('trim')
        | reject('equalto', '')
        | unique
        | list
      }}
  when: not ansible_check_mode

- name: Fail if GitHub returned no SSH keys
  ansible.builtin.fail:
    msg: >-
      GitHub returned no SSH keys for lxc_github_keys_github_users={{ lxc_github_keys_github_users | to_json }}.
      Check the usernames and the configured lxc_github_keys_base_url.
  when:
    - not ansible_check_mode
    - lxc_github_keys_authorized | length == 0

- name: Write authorized_keys
  ansible.builtin.copy:
    dest: "{{ lxc_github_keys_home }}/.ssh/authorized_keys"
    content: "{{ lxc_github_keys_authorized | join('\n') ~ '\n' }}"
    owner: "{{ lxc_github_keys_uid | string }}"
    group: "{{ lxc_github_keys_gid | string }}"
    mode: "0600"
  when: not ansible_check_mode
```

- [ ] **Step 3: Write argument spec**

Create `playbooks/roles/config/lxc_github_keys/meta/argument_specs.yml`:

```yaml
---
argument_specs:
  main:
    short_description: Fetch GitHub public SSH keys and write authorized_keys for an LXC user
    options:
      lxc_github_keys_user:
        type: str
        required: false
        description: Username that should own the authorized_keys file. Defaults to docker_user, falls back to lxc_ssh_user.
      lxc_github_keys_uid:
        type: int
        required: false
        description: UID for the authorized_keys owner.
      lxc_github_keys_gid:
        type: int
        required: false
        description: GID for the authorized_keys owner.
      lxc_github_keys_github_users:
        type: list
        elements: str
        required: false
        description: GitHub usernames whose public SSH keys are merged into authorized_keys. Defaults to lxc_github_users.
      lxc_github_keys_base_url:
        type: str
        required: false
        description: Base URL for fetching GitHub public keys (default https://github.com).
      lxc_github_keys_home:
        type: str
        required: false
        description: Home directory for the user receiving the authorized_keys file.
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
python3 tests/regression/test_lxc_github_keys.py
```

Expected: `ok: lxc_github_keys writes keys correctly and fails clearly on empty users`

- [ ] **Step 5: Commit**

```bash
git add \
  playbooks/roles/config/lxc_github_keys/ \
  tests/regression/test_lxc_github_keys.py \
  tests/regression/fixtures/lxc_github_keys_single_user_test.yml \
  tests/regression/fixtures/lxc_github_keys_multi_user_dedup_test.yml \
  tests/regression/fixtures/lxc_github_keys_empty_users_test.yml
git commit -m "feat(lxc-github-keys): add config/lxc_github_keys role with tests"
```

---

## Task 3: Refactor `lxc_workstation_baseline` to delegate key logic

**Files:**
- Modify: `playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml`
- Modify: `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml`
- Modify: `playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml`

- [ ] **Step 1: Replace key fetch tasks in `tasks/main.yml`**

The full replacement for `playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml`:

```yaml
---
- name: Assert workstation baseline inputs are present
  ansible.builtin.assert:
    that:
      - docker_user is defined
      - docker_user | string | length > 0
      - docker_uid is defined
      - docker_gid is defined
      - workstation_username == docker_user
      - workstation_uid == docker_uid
      - workstation_gid == docker_gid
    fail_msg: >-
      config/lxc_workstation_baseline requires docker_user/docker_uid/docker_gid.
      Set docker_user to the daily login user.

- name: Install workstation baseline packages
  ansible.builtin.apt:
    name: "{{ workstation_packages }}"
    state: present
    update_cache: true
  when: workstation_packages | length > 0

- name: Configure GitHub SSH keys
  ansible.builtin.include_role:
    name: config/lxc_github_keys
```

- [ ] **Step 2: Clean up `defaults/main.yml`**

Remove `workstation_github_keys_base_url` (now owned by `lxc_github_keys`). Full replacement for `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml`:

```yaml
---
workstation_username: "{{ docker_user }}"
workstation_uid: "{{ docker_uid }}"
workstation_gid: "{{ docker_gid }}"
workstation_home: "/home/{{ workstation_username }}"
workstation_packages:
  - tmux
  - mosh
  - wget
  - jq
  - ripgrep
  - fd-find
  - fzf
  - htop
  - tree
  - zip
  - unzip
  - build-essential
  - pkg-config
  - python3-venv
  - python3-pip
  - pipx
  - gh
```

- [ ] **Step 3: Update `meta/argument_specs.yml`**

Remove `workstation_github_users` and `workstation_github_keys_base_url` (both now live in `lxc_github_keys`). Full replacement for `playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml`:

```yaml
---
argument_specs:
  main:
    short_description: Configure the workstation login and package baseline inside an LXC
    options:
      docker_user:
        type: str
        required: true
        description: Daily login username for the workstation account inherited from docker host vars.
      docker_uid:
        type: int
        required: true
        description: Numeric UID for the workstation account inherited from docker host vars.
      docker_gid:
        type: int
        required: true
        description: Numeric GID for the workstation account inherited from docker host vars.
      workstation_username:
        type: str
        required: false
        description: Username that should own the workstation login baseline.
      workstation_uid:
        type: int
        required: false
        description: UID that should own the workstation login baseline.
      workstation_gid:
        type: int
        required: false
        description: GID that should own the workstation login baseline.
      workstation_home:
        type: str
        required: false
        description: Filesystem home directory for the workstation login account.
      workstation_packages:
        type: list
        elements: str
        required: false
        description: Package list to install for the workstation baseline.
```

---

## Task 4: Update workstation test fixtures and runner

The existing `workstation_baseline_*` tests pass `workstation_github_users` to the role. After the refactor, the role no longer reads that var — it calls `lxc_github_keys` which reads `lxc_github_users`. Update the fixtures to set `lxc_github_users` instead, and update the test runner's error-message markers.

**Files:**
- Modify: `tests/regression/fixtures/workstation_baseline_github_keys_test.yml`
- Modify: `tests/regression/fixtures/workstation_baseline_empty_github_keys_test.yml`
- Modify: `tests/regression/test_workstation_baseline_github_keys.py`

- [ ] **Step 1: Update success fixture**

In `tests/regression/fixtures/workstation_baseline_github_keys_test.yml`, replace the `vars` block:

Old:
```yaml
  vars:
    workstation_username: faviann
    workstation_uid: "{{ lookup('pipe', 'id -u') | int }}"
    workstation_gid: "{{ lookup('pipe', 'id -g') | int }}"
    workstation_home: "{{ temp_root }}/home/faviann"
    workstation_packages: []
    workstation_github_users:
      - faviann
      - aperture
    docker_user: faviann
    docker_uid: "{{ lookup('pipe', 'id -u') | int }}"
    docker_gid: "{{ lookup('pipe', 'id -g') | int }}"
```

New:
```yaml
  vars:
    workstation_username: faviann
    workstation_uid: "{{ lookup('pipe', 'id -u') | int }}"
    workstation_gid: "{{ lookup('pipe', 'id -g') | int }}"
    workstation_home: "{{ temp_root }}/home/faviann"
    workstation_packages: []
    lxc_ssh_user: faviann
    lxc_ssh_uid: "{{ lookup('pipe', 'id -u') | int }}"
    lxc_ssh_gid: "{{ lookup('pipe', 'id -g') | int }}"
    lxc_github_keys_home: "{{ temp_root }}/home/faviann"
    lxc_github_users:
      - faviann
      - aperture
    docker_user: faviann
    docker_uid: "{{ lookup('pipe', 'id -u') | int }}"
    docker_gid: "{{ lookup('pipe', 'id -g') | int }}"
```

- [ ] **Step 2: Update empty fixture**

In `tests/regression/fixtures/workstation_baseline_empty_github_keys_test.yml`, replace the `vars` block:

Old:
```yaml
  vars:
    workstation_username: faviann
    workstation_uid: "{{ lookup('pipe', 'id -u') | int }}"
    workstation_gid: "{{ lookup('pipe', 'id -g') | int }}"
    workstation_home: "{{ temp_root }}/home/faviann"
    workstation_packages: []
    workstation_github_users:
      - faviann
    docker_user: faviann
    docker_uid: "{{ lookup('pipe', 'id -u') | int }}"
    docker_gid: "{{ lookup('pipe', 'id -g') | int }}"
```

New:
```yaml
  vars:
    workstation_username: faviann
    workstation_uid: "{{ lookup('pipe', 'id -u') | int }}"
    workstation_gid: "{{ lookup('pipe', 'id -g') | int }}"
    workstation_home: "{{ temp_root }}/home/faviann"
    workstation_packages: []
    lxc_ssh_user: faviann
    lxc_ssh_uid: "{{ lookup('pipe', 'id -u') | int }}"
    lxc_ssh_gid: "{{ lookup('pipe', 'id -g') | int }}"
    lxc_github_keys_home: "{{ temp_root }}/home/faviann"
    lxc_github_users:
      - faviann
    docker_user: faviann
    docker_uid: "{{ lookup('pipe', 'id -u') | int }}"
    docker_gid: "{{ lookup('pipe', 'id -g') | int }}"
```

- [ ] **Step 3: Update test runner markers**

In `tests/regression/test_workstation_baseline_github_keys.py`, update the `markers` list:

Old:
```python
    markers = ["GitHub", "returned no SSH keys", "workstation_github_users"]
```

New:
```python
    markers = ["GitHub", "returned no SSH keys", "lxc_github_keys_github_users"]
```

- [ ] **Step 4: Run workstation baseline tests — confirm they pass**

```bash
python3 tests/regression/test_workstation_baseline_github_keys.py
```

Expected: `ok: workstation baseline GitHub keys succeed when present and fail clearly when empty`

- [ ] **Step 5: Commit**

```bash
git add \
  playbooks/roles/config/lxc_workstation_baseline/ \
  tests/regression/fixtures/workstation_baseline_github_keys_test.yml \
  tests/regression/fixtures/workstation_baseline_empty_github_keys_test.yml \
  tests/regression/test_workstation_baseline_github_keys.py
git commit -m "refactor(workstation-baseline): delegate key fetch to lxc_github_keys role"
```

---

## Task 5: Wire into configure play and update inventory

**Files:**
- Modify: `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml`
- Modify: `inventory/group_vars/lxcs/vars.yml`
- Modify: `inventory/host_vars/workstation.yml`

- [ ] **Step 1: Add `lxc_github_keys` step to configure play**

In `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml`, add after `Configure base system` and before `Configure logging`:

Old:
```yaml
    - name: Configure base system
      ansible.builtin.include_role:
        name: config/lxc_base_system

    - name: Configure logging
```

New:
```yaml
    - name: Configure base system
      ansible.builtin.include_role:
        name: config/lxc_base_system

    - name: Configure GitHub SSH keys
      ansible.builtin.include_role:
        name: config/lxc_github_keys

    - name: Configure logging
```

- [ ] **Step 2: Add fallback identity and GitHub users to `group_vars/lxcs/vars.yml`**

Append to `inventory/group_vars/lxcs/vars.yml`:

```yaml

lxc_ssh_user: faviann
lxc_ssh_uid: 1000
lxc_ssh_gid: 1000
lxc_github_users:
  - faviann
```

- [ ] **Step 3: Remove `workstation_github_users` from workstation host_vars**

In `inventory/host_vars/workstation.yml`, remove the line:

```yaml
workstation_github_users:
  - faviann
```

The `docker_user: faviann`, `docker_uid: 1000`, and `docker_gid: 1000` overrides stay — they still define the workstation user identity correctly.

- [ ] **Step 4: Run all regression tests**

```bash
python3 tests/regression/test_lxc_github_keys.py && \
python3 tests/regression/test_workstation_baseline_github_keys.py
```

Expected: both print `ok: ...` and exit 0.

- [ ] **Step 5: Commit**

```bash
git add \
  playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml \
  inventory/group_vars/lxcs/vars.yml \
  inventory/host_vars/workstation.yml
git commit -m "feat(lxcs): wire lxc_github_keys into configure play for all LXCs"
```
