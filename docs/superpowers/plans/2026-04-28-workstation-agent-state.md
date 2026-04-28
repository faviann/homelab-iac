# Workstation Agent State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist selected Claude/Codex CLI comfort state across intentional `workstation` LXC rebuilds without persisting the whole home directory.

**Architecture:** Extend `playbooks/roles/config/lxc_workstation_baseline` with a gated agent-state setup block. The role creates `/ephemeral/workstation/agent-state/{claude,codex}` with `0700`, then links `~/.claude` and `~/.codex` to those persistent directories. Existing real files/directories at managed home paths fail clearly; disabling the feature skips management and does not clean up.

**Tech Stack:** Ansible role defaults/tasks/argument specs, Python `unittest` contract tests, Ansible regression fixtures run through `uv run --locked ansible-playbook`.

---

## File Structure

- Modify `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml`  
  Add `workstation_agent_state_enabled`, `workstation_agent_state_root`, and `workstation_agent_state_links`.

- Modify `playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml`  
  Document the new role inputs.

- Modify `playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml`  
  Include the agent-state task file after package installation.

- Create `playbooks/roles/config/lxc_workstation_baseline/tasks/agent_state.yml`  
  Add validation, directory creation, conflict detection, and symlink creation for agent state.

- Modify `tests/unit/test_workstation_baseline_role.py`  
  Add static contract coverage for defaults, argument specs, and task names/fragments.

- Create `tests/regression/test_workstation_agent_state.py`  
  Run success, disabled, and conflict fixtures.

- Create `tests/regression/fixtures/workstation_agent_state_success.yml`  
  Verify directories, permissions, ownership, and symlink targets.

- Create `tests/regression/fixtures/workstation_agent_state_disabled.yml`  
  Verify disabling skips directory/link creation.

- Create `tests/regression/fixtures/workstation_agent_state_conflict.yml`  
  Verify an existing real `~/.claude` path fails clearly instead of being overwritten.

- Create `tests/regression/fixtures/workstation_agent_state_idempotency.yml`  
  Verify the focused agent-state task file reports `changed=0` when correct directories and symlinks already exist.

---

### Task 1: Add Unit Contract Tests

**Files:**
- Modify: `tests/unit/test_workstation_baseline_role.py`

- [ ] **Step 1: Write failing defaults and task contract assertions**

Edit `tests/unit/test_workstation_baseline_role.py`. In `test_role_defaults_contract()`, after the existing `workstation_gid` assertion, add:

```python
        self.assertEqual(defaults["workstation_home"], "/home/{{ workstation_username }}")
        self.assertTrue(defaults["workstation_agent_state_enabled"])
        self.assertEqual(defaults["workstation_agent_state_root"], "/ephemeral/workstation/agent-state")
        self.assertEqual(
            defaults["workstation_agent_state_links"],
            [
                {
                    "name": "claude",
                    "path": "{{ workstation_home }}/.claude",
                    "target": "{{ workstation_agent_state_root }}/claude",
                },
                {
                    "name": "codex",
                    "path": "{{ workstation_home }}/.codex",
                    "target": "{{ workstation_agent_state_root }}/codex",
                },
            ],
        )
```

In `test_role_tasks_contract()`, after the existing `Install bw CLI` assertion, add:

```python
        self.assertIn("Configure workstation agent state", task_names)
```

Still in `test_role_tasks_contract()`, after `rendered_tasks = yaml.safe_dump(tasks, sort_keys=True)`, add:

```python
        agent_state_tasks = load_yaml(
            REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/tasks/agent_state.yml"
        )
        agent_state_task_names = [t.get("name") for t in agent_state_tasks]
        self.assertIn("Validate workstation agent state paths", agent_state_task_names)
        self.assertIn("Ensure workstation agent state directories exist", agent_state_task_names)
        self.assertIn("Inspect workstation agent state home links", agent_state_task_names)
        self.assertIn("Fail when workstation agent state home path is not the managed symlink", agent_state_task_names)
        self.assertIn("Link workstation agent state into home directory", agent_state_task_names)
```

Still in `test_role_tasks_contract()`, after the loop checking removed fragments, add:

```python
        rendered_agent_state_tasks = yaml.safe_dump(agent_state_tasks, sort_keys=True)
        expected_fragments = (
            "workstation_agent_state_enabled",
            "workstation_agent_state_root",
            "workstation_agent_state_links",
            "islnk",
            "lnk_source",
            "state: link",
            "mode: \"0700\"",
        )
        for expected_fragment in expected_fragments:
            self.assertIn(expected_fragment, rendered_agent_state_tasks)
```

- [ ] **Step 2: Add failing argument spec assertions**

Add this test method to `WorkstationBaselineRoleTests`:

```python
    def test_role_argument_specs_contract(self) -> None:
        specs = load_yaml(REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml")
        options = specs["argument_specs"]["main"]["options"]

        self.assertEqual(options["workstation_agent_state_enabled"]["type"], "bool")
        self.assertFalse(options["workstation_agent_state_enabled"]["required"])
        self.assertEqual(options["workstation_agent_state_root"]["type"], "str")
        self.assertFalse(options["workstation_agent_state_root"]["required"])
        self.assertEqual(options["workstation_agent_state_links"]["type"], "list")
        self.assertEqual(options["workstation_agent_state_links"]["elements"], "dict")
        self.assertFalse(options["workstation_agent_state_links"]["required"])
```

- [ ] **Step 3: Run unit test and verify failure**

Run:

```bash
uv run --locked python tests/unit/test_workstation_baseline_role.py
```

Expected: FAIL because `workstation_agent_state_*` defaults, task names, and argument specs do not exist yet.

---

### Task 2: Add Role Defaults and Argument Specs

**Files:**
- Modify: `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml`
- Modify: `playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml`

- [ ] **Step 1: Add workstation agent-state defaults**

In `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml`, after `workstation_home`, add:

```yaml
workstation_agent_state_enabled: true
workstation_agent_state_root: /ephemeral/workstation/agent-state
workstation_agent_state_links:
  - name: claude
    path: "{{ workstation_home }}/.claude"
    target: "{{ workstation_agent_state_root }}/claude"
  - name: codex
    path: "{{ workstation_home }}/.codex"
    target: "{{ workstation_agent_state_root }}/codex"
```

- [ ] **Step 2: Add argument spec entries**

In `playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml`, after `workstation_home`, add:

```yaml
      workstation_agent_state_enabled:
        type: bool
        required: false
        description: Whether to manage persistent Claude/Codex comfort-state links for the workstation user.
      workstation_agent_state_root:
        type: str
        required: false
        description: Persistent local path used for selected agent CLI state directories.
      workstation_agent_state_links:
        type: list
        elements: dict
        required: false
        description: Agent state symlinks to create from the workstation home into workstation_agent_state_root.
```

- [ ] **Step 3: Run unit test and verify partial failure**

Run:

```bash
uv run --locked python tests/unit/test_workstation_baseline_role.py
```

Expected: FAIL only on missing task names/fragments from `test_role_tasks_contract()`.

- [ ] **Step 4: Leave the red state uncommitted**

Run:

```bash
git status --short
```

Expected: the unit test, defaults, and argument spec files are modified but not
committed yet. The first commit happens after the role implementation turns this
test green.

---

### Task 3: Implement Agent-State Role Tasks

**Files:**
- Modify: `playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml`
- Create: `playbooks/roles/config/lxc_workstation_baseline/tasks/agent_state.yml`

- [ ] **Step 1: Include the focused agent-state task file from main**

In `playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml`, insert this task after `Install workstation baseline packages` and before `Configure GitHub SSH keys`:

```yaml
- name: Configure workstation agent state
  ansible.builtin.include_tasks: agent_state.yml
  when: workstation_agent_state_enabled | bool
```

- [ ] **Step 2: Create the agent-state task file**

Create `playbooks/roles/config/lxc_workstation_baseline/tasks/agent_state.yml`:

```yaml
---
- name: Validate workstation agent state paths
  ansible.builtin.assert:
    that:
      - workstation_agent_state_root is defined
      - workstation_agent_state_root | string | length > 0
      - workstation_agent_state_links is defined
      - workstation_agent_state_links | length > 0
      - workstation_agent_state_links | selectattr('path', 'defined') | list | length == workstation_agent_state_links | length
      - workstation_agent_state_links | selectattr('target', 'defined') | list | length == workstation_agent_state_links | length
      - workstation_agent_state_links | map(attribute='path') | map('string') | select('match', '^' ~ workstation_home ~ '/\\.[^/]+$') | list | length == workstation_agent_state_links | length
      - workstation_agent_state_links | map(attribute='target') | map('string') | select('match', '^' ~ workstation_agent_state_root ~ '/[^/]+$') | list | length == workstation_agent_state_links | length
    fail_msg: >-
      workstation_agent_state_links must map direct hidden paths under workstation_home
      to direct children under workstation_agent_state_root.

- name: Ensure workstation agent state directories exist
  ansible.builtin.file:
    path: "{{ item }}"
    state: directory
    owner: "{{ workstation_uid }}"
    group: "{{ workstation_gid }}"
    mode: "0700"
  loop: "{{ [workstation_agent_state_root] + (workstation_agent_state_links | map(attribute='target') | list) }}"

- name: Inspect workstation agent state home links
  ansible.builtin.stat:
    path: "{{ item.path }}"
  loop: "{{ workstation_agent_state_links }}"
  register: _workstation_agent_state_home_paths

- name: Fail when workstation agent state home path is not the managed symlink
  ansible.builtin.assert:
    that:
      - >-
        (not item.stat.exists)
        or
        (
          item.stat.islnk | default(false)
          and item.stat.lnk_source == item.item.target
        )
    fail_msg: >-
      {{ item.item.path }} exists and is not the managed symlink to
      {{ item.item.target }}. Move or migrate it manually before enabling
      workstation agent state.
  loop: "{{ _workstation_agent_state_home_paths.results }}"

- name: Link workstation agent state into home directory
  ansible.builtin.file:
    src: "{{ item.target }}"
    dest: "{{ item.path }}"
    state: link
    owner: "{{ workstation_uid }}"
    group: "{{ workstation_gid }}"
    force: false
  loop: "{{ workstation_agent_state_links }}"
```

- [ ] **Step 3: Run unit test and verify pass**

Run:

```bash
uv run --locked python tests/unit/test_workstation_baseline_role.py
```

Expected: PASS.

- [ ] **Step 4: Commit role implementation**

Run:

```bash
git add playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml playbooks/roles/config/lxc_workstation_baseline/tasks/agent_state.yml tests/unit/test_workstation_baseline_role.py
git add playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml
git commit -m "feat(workstation): manage selected agent state links"
```

Expected: commit succeeds.

---

### Task 4: Add Regression Fixtures

**Files:**
- Create: `tests/regression/test_workstation_agent_state.py`
- Create: `tests/regression/fixtures/workstation_agent_state_success.yml`
- Create: `tests/regression/fixtures/workstation_agent_state_disabled.yml`
- Create: `tests/regression/fixtures/workstation_agent_state_conflict.yml`
- Create: `tests/regression/fixtures/workstation_agent_state_idempotency.yml`

- [ ] **Step 1: Create the regression runner**

Create `tests/regression/test_workstation_agent_state.py`:

```python
#!/usr/bin/env python3
"""Regression tests for workstation agent-state persistence links."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "regression" / "fixtures"
SUCCESS_PLAYBOOK = FIXTURE_ROOT / "workstation_agent_state_success.yml"
DISABLED_PLAYBOOK = FIXTURE_ROOT / "workstation_agent_state_disabled.yml"
CONFLICT_PLAYBOOK = FIXTURE_ROOT / "workstation_agent_state_conflict.yml"
IDEMPOTENCY_PLAYBOOK = FIXTURE_ROOT / "workstation_agent_state_idempotency.yml"
ANSIBLE_PLAYBOOK = "uv run --locked ansible-playbook".split()


def run_playbook(playbook: Path, temp_root: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*ANSIBLE_PLAYBOOK, str(playbook), "-f", "1", "-e", f"temp_root={temp_root}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="workstation-agent-state-success-") as temp_root:
        success = run_playbook(SUCCESS_PLAYBOOK, temp_root)

    success_output = f"{success.stdout}\n{success.stderr}"
    if success.returncode != 0:
        print("success playbook failed unexpectedly", file=sys.stderr)
        print(success_output, file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="workstation-agent-state-disabled-") as temp_root:
        disabled = run_playbook(DISABLED_PLAYBOOK, temp_root)

    disabled_output = f"{disabled.stdout}\n{disabled.stderr}"
    if disabled.returncode != 0:
        print("disabled playbook failed unexpectedly", file=sys.stderr)
        print(disabled_output, file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="workstation-agent-state-conflict-") as temp_root:
        conflict = run_playbook(CONFLICT_PLAYBOOK, temp_root)

    conflict_output = f"{conflict.stdout}\n{conflict.stderr}"
    if conflict.returncode == 0:
        print("conflict playbook succeeded unexpectedly", file=sys.stderr)
        print(conflict_output, file=sys.stderr)
        return 1

    expected_markers = [
        "exists and is not the managed symlink",
        "Move or migrate it manually",
        ".claude",
    ]
    if not all(marker in conflict_output for marker in expected_markers):
        print("conflict failure did not explain the unsafe existing path", file=sys.stderr)
        print(conflict_output, file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="workstation-agent-state-idempotency-") as temp_root:
        first_idempotency = run_playbook(IDEMPOTENCY_PLAYBOOK, temp_root)
        second_idempotency = run_playbook(IDEMPOTENCY_PLAYBOOK, temp_root)

    first_idempotency_output = f"{first_idempotency.stdout}\n{first_idempotency.stderr}"
    if first_idempotency.returncode != 0:
        print("idempotency setup playbook failed unexpectedly", file=sys.stderr)
        print(first_idempotency_output, file=sys.stderr)
        return 1

    second_idempotency_output = f"{second_idempotency.stdout}\n{second_idempotency.stderr}"
    if second_idempotency.returncode != 0:
        print("idempotency verification playbook failed unexpectedly", file=sys.stderr)
        print(second_idempotency_output, file=sys.stderr)
        return 1

    if "changed=0" not in second_idempotency_output:
        print("second agent-state-only run was not idempotent", file=sys.stderr)
        print(second_idempotency_output, file=sys.stderr)
        return 1

    print("ok: workstation agent state links are managed safely")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Create the success fixture**

Create `tests/regression/fixtures/workstation_agent_state_success.yml`:

```yaml
---
- name: Test workstation agent state success path
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    workstation_username: faviann
    workstation_uid: "{{ lookup('pipe', 'id -u') | int }}"
    workstation_gid: "{{ lookup('pipe', 'id -g') | int }}"
    workstation_home: "{{ temp_root }}/home/faviann"
    workstation_packages: []
    workstation_agent_state_enabled: true
    workstation_agent_state_root: "{{ temp_root }}/ephemeral/workstation/agent-state"
    workstation_agent_state_links:
      - name: claude
        path: "{{ workstation_home }}/.claude"
        target: "{{ workstation_agent_state_root }}/claude"
      - name: codex
        path: "{{ workstation_home }}/.codex"
        target: "{{ workstation_agent_state_root }}/codex"
    lxc_ssh_user: faviann
    lxc_ssh_uid: "{{ lookup('pipe', 'id -u') | int }}"
    lxc_ssh_gid: "{{ lookup('pipe', 'id -g') | int }}"
    lxc_github_keys_home: "{{ temp_root }}/home/faviann"
    lxc_github_users:
      - faviann
    docker_user: faviann
    docker_uid: "{{ lookup('pipe', 'id -u') | int }}"
    docker_gid: "{{ lookup('pipe', 'id -g') | int }}"
  tasks:
    - name: Place mock curl on PATH
      ansible.builtin.copy:
        dest: "{{ temp_root }}/curl"
        mode: "0755"
        content: |
          #!/bin/sh
          case "$*" in
            *faviann.keys*)
              printf '%s\n' 'ssh-ed25519 AAAATESTKEYONE faviann@laptop'
              ;;
            *get.chezmoi.io*)
              printf '%s\n' '#!/bin/sh' 'exit 0'
              ;;
            *)
              exit 0
              ;;
          esac

    - name: Place mock npm on PATH
      ansible.builtin.copy:
        dest: "{{ temp_root }}/npm"
        mode: "0755"
        content: |
          #!/bin/sh
          exit 0

    - name: Ensure workstation home exists
      ansible.builtin.file:
        path: "{{ workstation_home }}"
        state: directory
        mode: "0755"

    - name: Include workstation baseline role with PATH mocks
      block:
        - ansible.builtin.include_role:
            name: config/lxc_workstation_baseline
      environment:
        PATH: "{{ temp_root }}:{{ lookup('env', 'PATH') }}"

    - name: Stat agent state root
      ansible.builtin.stat:
        path: "{{ workstation_agent_state_root }}"
      register: agent_state_root_stat

    - name: Stat Claude agent state directory
      ansible.builtin.stat:
        path: "{{ workstation_agent_state_root }}/claude"
      register: claude_state_dir_stat

    - name: Stat Codex agent state directory
      ansible.builtin.stat:
        path: "{{ workstation_agent_state_root }}/codex"
      register: codex_state_dir_stat

    - name: Stat Claude home symlink
      ansible.builtin.stat:
        path: "{{ workstation_home }}/.claude"
      register: claude_home_link_stat

    - name: Stat Codex home symlink
      ansible.builtin.stat:
        path: "{{ workstation_home }}/.codex"
      register: codex_home_link_stat

    - name: Assert workstation agent state was linked safely
      ansible.builtin.assert:
        that:
          - agent_state_root_stat.stat.isdir
          - agent_state_root_stat.stat.uid == workstation_uid
          - agent_state_root_stat.stat.gid == workstation_gid
          - agent_state_root_stat.stat.mode == "0700"
          - claude_state_dir_stat.stat.isdir
          - claude_state_dir_stat.stat.uid == workstation_uid
          - claude_state_dir_stat.stat.gid == workstation_gid
          - claude_state_dir_stat.stat.mode == "0700"
          - codex_state_dir_stat.stat.isdir
          - codex_state_dir_stat.stat.uid == workstation_uid
          - codex_state_dir_stat.stat.gid == workstation_gid
          - codex_state_dir_stat.stat.mode == "0700"
          - claude_home_link_stat.stat.islnk
          - claude_home_link_stat.stat.lnk_source == workstation_agent_state_root ~ "/claude"
          - codex_home_link_stat.stat.islnk
          - codex_home_link_stat.stat.lnk_source == workstation_agent_state_root ~ "/codex"
        fail_msg: "Workstation agent state directories or symlinks were not created as expected"
```

- [ ] **Step 3: Create the disabled fixture**

Create `tests/regression/fixtures/workstation_agent_state_disabled.yml`:

```yaml
---
- name: Test workstation agent state disabled path
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    workstation_username: faviann
    workstation_uid: "{{ lookup('pipe', 'id -u') | int }}"
    workstation_gid: "{{ lookup('pipe', 'id -g') | int }}"
    workstation_home: "{{ temp_root }}/home/faviann"
    workstation_packages: []
    workstation_agent_state_enabled: false
    workstation_agent_state_root: "{{ temp_root }}/ephemeral/workstation/agent-state"
    lxc_ssh_user: faviann
    lxc_ssh_uid: "{{ lookup('pipe', 'id -u') | int }}"
    lxc_ssh_gid: "{{ lookup('pipe', 'id -g') | int }}"
    lxc_github_keys_home: "{{ temp_root }}/home/faviann"
    lxc_github_users:
      - faviann
    docker_user: faviann
    docker_uid: "{{ lookup('pipe', 'id -u') | int }}"
    docker_gid: "{{ lookup('pipe', 'id -g') | int }}"
  tasks:
    - name: Place mock curl on PATH
      ansible.builtin.copy:
        dest: "{{ temp_root }}/curl"
        mode: "0755"
        content: |
          #!/bin/sh
          case "$*" in
            *faviann.keys*)
              printf '%s\n' 'ssh-ed25519 AAAATESTKEYONE faviann@laptop'
              ;;
            *get.chezmoi.io*)
              printf '%s\n' '#!/bin/sh' 'exit 0'
              ;;
            *)
              exit 0
              ;;
          esac

    - name: Place mock npm on PATH
      ansible.builtin.copy:
        dest: "{{ temp_root }}/npm"
        mode: "0755"
        content: |
          #!/bin/sh
          exit 0

    - name: Ensure workstation home exists
      ansible.builtin.file:
        path: "{{ workstation_home }}"
        state: directory
        mode: "0755"

    - name: Include workstation baseline role with PATH mocks
      block:
        - ansible.builtin.include_role:
            name: config/lxc_workstation_baseline
      environment:
        PATH: "{{ temp_root }}:{{ lookup('env', 'PATH') }}"

    - name: Stat agent state root
      ansible.builtin.stat:
        path: "{{ workstation_agent_state_root }}"
      register: agent_state_root_stat

    - name: Stat Claude home path
      ansible.builtin.stat:
        path: "{{ workstation_home }}/.claude"
      register: claude_home_stat

    - name: Stat Codex home path
      ansible.builtin.stat:
        path: "{{ workstation_home }}/.codex"
      register: codex_home_stat

    - name: Assert workstation agent state was skipped
      ansible.builtin.assert:
        that:
          - not agent_state_root_stat.stat.exists
          - not claude_home_stat.stat.exists
          - not codex_home_stat.stat.exists
        fail_msg: "Disabled workstation agent state should not create directories or links"
```

- [ ] **Step 4: Create the conflict fixture**

Create `tests/regression/fixtures/workstation_agent_state_conflict.yml`:

```yaml
---
- name: Test workstation agent state conflict path
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    workstation_username: faviann
    workstation_uid: "{{ lookup('pipe', 'id -u') | int }}"
    workstation_gid: "{{ lookup('pipe', 'id -g') | int }}"
    workstation_home: "{{ temp_root }}/home/faviann"
    workstation_packages: []
    workstation_agent_state_enabled: true
    workstation_agent_state_root: "{{ temp_root }}/ephemeral/workstation/agent-state"
    workstation_agent_state_links:
      - name: claude
        path: "{{ workstation_home }}/.claude"
        target: "{{ workstation_agent_state_root }}/claude"
      - name: codex
        path: "{{ workstation_home }}/.codex"
        target: "{{ workstation_agent_state_root }}/codex"
    lxc_ssh_user: faviann
    lxc_ssh_uid: "{{ lookup('pipe', 'id -u') | int }}"
    lxc_ssh_gid: "{{ lookup('pipe', 'id -g') | int }}"
    lxc_github_keys_home: "{{ temp_root }}/home/faviann"
    lxc_github_users:
      - faviann
    docker_user: faviann
    docker_uid: "{{ lookup('pipe', 'id -u') | int }}"
    docker_gid: "{{ lookup('pipe', 'id -g') | int }}"
  tasks:
    - name: Place mock curl on PATH
      ansible.builtin.copy:
        dest: "{{ temp_root }}/curl"
        mode: "0755"
        content: |
          #!/bin/sh
          case "$*" in
            *faviann.keys*)
              printf '%s\n' 'ssh-ed25519 AAAATESTKEYONE faviann@laptop'
              ;;
            *get.chezmoi.io*)
              printf '%s\n' '#!/bin/sh' 'exit 0'
              ;;
            *)
              exit 0
              ;;
          esac

    - name: Place mock npm on PATH
      ansible.builtin.copy:
        dest: "{{ temp_root }}/npm"
        mode: "0755"
        content: |
          #!/bin/sh
          exit 0

    - name: Ensure workstation home exists
      ansible.builtin.file:
        path: "{{ workstation_home }}"
        state: directory
        mode: "0755"

    - name: Create conflicting Claude state directory
      ansible.builtin.file:
        path: "{{ workstation_home }}/.claude"
        state: directory
        mode: "0700"

    - name: Include workstation baseline role with PATH mocks
      block:
        - ansible.builtin.include_role:
            name: config/lxc_workstation_baseline
      environment:
        PATH: "{{ temp_root }}:{{ lookup('env', 'PATH') }}"
```

- [ ] **Step 5: Create the focused idempotency fixture**

Create `tests/regression/fixtures/workstation_agent_state_idempotency.yml`:

```yaml
---
- name: Test workstation agent state idempotency
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    workstation_username: faviann
    workstation_uid: "{{ lookup('pipe', 'id -u') | int }}"
    workstation_gid: "{{ lookup('pipe', 'id -g') | int }}"
    workstation_home: "{{ temp_root }}/home/faviann"
    workstation_agent_state_root: "{{ temp_root }}/ephemeral/workstation/agent-state"
    workstation_agent_state_links:
      - name: claude
        path: "{{ workstation_home }}/.claude"
        target: "{{ workstation_agent_state_root }}/claude"
      - name: codex
        path: "{{ workstation_home }}/.codex"
        target: "{{ workstation_agent_state_root }}/codex"
  tasks:
    - name: Ensure workstation home exists
      ansible.builtin.file:
        path: "{{ workstation_home }}"
        state: directory
        mode: "0755"

    - name: Include focused workstation agent state tasks
      ansible.builtin.include_role:
        name: config/lxc_workstation_baseline
        tasks_from: agent_state
```

- [ ] **Step 6: Run regression test and verify pass**

Run:

```bash
uv run --locked python tests/regression/test_workstation_agent_state.py
```

Expected: PASS and output includes `ok: workstation agent state links are managed safely`.

- [ ] **Step 7: Commit regression coverage**

Run:

```bash
git add tests/regression/test_workstation_agent_state.py tests/regression/fixtures/workstation_agent_state_success.yml tests/regression/fixtures/workstation_agent_state_disabled.yml tests/regression/fixtures/workstation_agent_state_conflict.yml tests/regression/fixtures/workstation_agent_state_idempotency.yml
git commit -m "test(workstation): cover agent state persistence"
```

Expected: commit succeeds.

---

### Task 5: Full Verification

**Files:**
- No source edits expected.

- [ ] **Step 1: Run focused unit test**

Run:

```bash
uv run --locked python tests/unit/test_workstation_baseline_role.py
```

Expected: PASS.

- [ ] **Step 2: Run focused regression test**

Run:

```bash
uv run --locked python tests/regression/test_workstation_agent_state.py
```

Expected: PASS.

- [ ] **Step 3: Run existing workstation regression test**

Run:

```bash
uv run --locked python tests/regression/test_workstation_baseline_github_keys.py
```

Expected: PASS and output includes `ok: workstation baseline writes inbound GitHub authorized_keys without outbound identity`.

- [ ] **Step 4: Run workstation check mode against inventory**

Run:

```bash
uv run --locked ansible-playbook site.yml --limit workstation --check
```

Expected: playbook completes without a workstation role failure. If running from inside the `workstation` LXC and the self-skip guard excludes it, rerun:

```bash
uv run --locked ansible-playbook site.yml -e proxmox_skip_self=false --limit workstation --check
```

- [ ] **Step 5: Inspect final worktree**

Run:

```bash
git status --short
```

Expected: only unrelated pre-existing untracked files remain, or the worktree is clean.

---

## Self-Review

Spec coverage:

- Selected Claude/Codex state under `/ephemeral/workstation/agent-state`: Tasks 2 and 3.
- Symlinks from `~/.claude` and `~/.codex`: Tasks 2, 3, and 4.
- `workstation_agent_state_enabled` escape hatch: Tasks 2, 3, and disabled fixture in Task 4.
- Full role path and `workstation_home` dependency: Task 2 uses existing defaults and argument specs.
- Root and child directory mode `0700`: Task 3 implementation and Task 4 success fixture.
- Existing real path fails clearly: Task 3 implementation and Task 4 conflict fixture.
- Existing correct symlinks are no-op: Task 4 idempotency fixture runs the focused agent-state task file twice and requires `changed=0` on the second run.
- No full-home persistence, no secrets handling, no cleanup-on-disable: encoded by the limited task block and disabled fixture.

Red-flag scan:

- No unresolved marker text remains in the plan.

Type consistency:

- Variable names match the approved spec: `workstation_agent_state_enabled`, `workstation_agent_state_root`, `workstation_agent_state_links`.
- Role path matches the repo: `playbooks/roles/config/lxc_workstation_baseline`.
- Commands follow the repo contract: Python/Ansible run through `uv run --locked`.
