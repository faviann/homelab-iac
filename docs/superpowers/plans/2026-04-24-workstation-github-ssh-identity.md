# Workstation GitHub SSH Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the workstation LXC regain the same GitHub SSH authentication and signing identity after rebuilds.

**Architecture:** Establish the stable key once on the running LXC, store it in Bitwarden, and let `dotfiles` restore it through chezmoi. After dotfiles restore is verified, remove outbound GitHub identity management from `ServerManagementScripts` so the infra repo only owns baseline capability and inbound LXC access.

**Tech Stack:** Bash, Bitwarden CLI (`bw`), chezmoi templates/scripts, Ansible, Python unittest/regression tests

---

## File Map

### Live Workstation LXC

| Action | Path | Responsibility |
|---|---|---|
| Create temporarily | `/tmp/import-workstation-github-key-to-bitwarden.sh` | One-time import/generate helper for the dedicated workstation SSH key |

### `~/repos/dotfiles`

| Action | Path | Responsibility |
|---|---|---|
| Create | `private_dot_ssh/private_id_ed25519.tmpl` | Restore private key from Bitwarden item notes |
| Create | `private_dot_ssh/id_ed25519.pub.tmpl` | Restore public key from Bitwarden `public_key` field |
| Create | `.chezmoiscripts/run_after_github-known-hosts.sh.tmpl` | Manage `github.com` in the daily user's `known_hosts` |
| Create | `.chezmoiscripts/run_after_switch-chezmoi-origin-to-ssh.sh.tmpl` | Switch chezmoi source remote from HTTPS to SSH after bootstrap |
| Modify | `BOOTSTRAP.md` | Source of truth for key bootstrap, GitHub registration, verification, and rotation |

### `/home/aperture/ServerManagementScripts`

| Action | Path | Responsibility |
|---|---|---|
| Modify | `playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml` | Stop managing outbound GitHub SSH identity |
| Modify | `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml` | Remove unused `workstation_github_*` defaults |
| Modify | `playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml` | Remove unused argument specs |
| Modify | `tests/unit/test_workstation_baseline_role.py` | Assert outbound GitHub identity tasks/defaults are absent and baseline tools remain |
| Modify | `tests/regression/fixtures/workstation_baseline_github_keys_test.yml` | Assert inbound `authorized_keys` behavior still works without outbound key generation |
| Modify | `tests/regression/test_workstation_baseline_github_keys.py` | Rename expected message to reflect inbound key scope |
| Delete | `tests/regression/fixtures/workstation_baseline_empty_github_keys_test.yml` | Empty-key failure is already covered by the shared `lxc_github_keys` role test |
| Modify | `docs/workstation-post-provisioning-handoff.md` | Shrink to a boundary pointer to `dotfiles/BOOTSTRAP.md` |

---

## Task 1: Establish the Stable Key in Bitwarden From the Live LXC

**Files:**
- Create temporarily on workstation: `/tmp/import-workstation-github-key-to-bitwarden.sh`

- [ ] **Step 1: Open an interactive shell on the workstation as `faviann`**

Run from `/home/aperture/ServerManagementScripts`:

```bash
ssh -l faviann -i .ansible/ssh/proxmox_lxc workstation.faviann.vms
```

Expected: shell prompt on the workstation LXC as `faviann`.

- [ ] **Step 2: Unlock Bitwarden in that shell**

Run on the workstation:

```bash
bw login
export BW_SESSION=$(bw unlock --raw)
bw status
```

Expected: `bw status` returns JSON whose `status` value is `unlocked`.

- [ ] **Step 3: Write the one-time helper**

Create `/tmp/import-workstation-github-key-to-bitwarden.sh` on the workstation with this exact content:

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x

ITEM_NAME="dotfiles/workstation-ssh-key"
KEY_COMMENT="faviann@workstation"
SSH_DIR="$HOME/.ssh"
PRIVATE_KEY="$SSH_DIR/id_ed25519"
PUBLIC_KEY="$PRIVATE_KEY.pub"
REPLACE=false

usage() {
  cat <<'USAGE'
Usage: import-workstation-github-key-to-bitwarden.sh [--replace]

Imports or creates ~/.ssh/id_ed25519, then writes it to Bitwarden item:
  dotfiles/workstation-ssh-key

Default behavior refuses to overwrite an existing Bitwarden item.
Use --replace only during deliberate key rotation or migration repair.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --replace)
      REPLACE=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_command bw
require_command jq
require_command ssh-keygen

if [ -z "${BW_SESSION:-}" ]; then
  echo 'BW_SESSION is not set. Run: export BW_SESSION=$(bw unlock --raw)' >&2
  exit 1
fi

if ! bw status | jq -e '.status == "unlocked"' >/dev/null; then
  echo 'Bitwarden is not unlocked. Run: export BW_SESSION=$(bw unlock --raw)' >&2
  exit 1
fi

mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"

if [ ! -f "$PRIVATE_KEY" ]; then
  ssh-keygen -q -t ed25519 -f "$PRIVATE_KEY" -N "" -C "$KEY_COMMENT"
fi

chmod 600 "$PRIVATE_KEY"

derived_public_core="$(ssh-keygen -y -f "$PRIVATE_KEY")"

public_file_matches=false
if [ -f "$PUBLIC_KEY" ]; then
  current_public_core="$(awk 'NF >= 2 { print $1 " " $2; exit }' "$PUBLIC_KEY")"
  if [ "$current_public_core" = "$derived_public_core" ]; then
    public_file_matches=true
  fi
fi

if [ "$public_file_matches" = true ]; then
  public_key="$(head -n 1 "$PUBLIC_KEY")"
else
  public_key="$derived_public_core $KEY_COMMENT"
  printf '%s\n' "$public_key" > "$PUBLIC_KEY"
fi

chmod 644 "$PUBLIC_KEY"

existing_item_json=""
if existing_item_json="$(bw get item "$ITEM_NAME" 2>/dev/null)"; then
  if [ "$REPLACE" != true ]; then
    echo "Bitwarden item already exists: $ITEM_NAME" >&2
    echo "Re-run with --replace only if you intend to overwrite it." >&2
    exit 1
  fi
  existing_item_id="$(printf '%s' "$existing_item_json" | jq -r '.id')"
else
  existing_item_id=""
fi

payload="$(
  bw get template item |
    jq \
      --arg name "$ITEM_NAME" \
      --rawfile private_key "$PRIVATE_KEY" \
      --arg public_key "$public_key" \
      '
      .type = 2 |
      .name = $name |
      .notes = $private_key |
      .secureNote = {"type": 0} |
      .fields = [
        {
          "name": "public_key",
          "value": $public_key,
          "type": 0
        }
      ]
      '
)"

encoded_payload="$(printf '%s' "$payload" | bw encode)"

if [ -n "$existing_item_id" ]; then
  bw edit item "$existing_item_id" "$encoded_payload" >/dev/null
  echo "Updated Bitwarden item: $ITEM_NAME"
else
  bw create item "$encoded_payload" >/dev/null
  echo "Created Bitwarden item: $ITEM_NAME"
fi

written_item="$(bw get item "$ITEM_NAME")"
written_public_key="$(
  printf '%s' "$written_item" |
    jq -r '.fields[] | select(.name == "public_key") | .value' |
    head -n 1
)"

if [ -z "$(printf '%s' "$written_item" | jq -r '.notes // empty')" ]; then
  echo "Verification failed: Bitwarden item notes are empty." >&2
  exit 1
fi

if [ "$written_public_key" != "$public_key" ]; then
  echo "Verification failed: Bitwarden public_key field does not match local public key." >&2
  exit 1
fi

cat <<EOF

Stable workstation SSH key is stored in Bitwarden.

Public key:
$public_key

Add this public key to GitHub twice:
1. Settings -> SSH and GPG keys -> New SSH key -> Authentication Key -> title: workstation
2. Settings -> SSH and GPG keys -> New SSH key -> Signing Key -> title: workstation-signing

The private key was not printed.
EOF
```

- [ ] **Step 4: Run the helper**

Run on the workstation:

```bash
chmod 700 /tmp/import-workstation-github-key-to-bitwarden.sh
/tmp/import-workstation-github-key-to-bitwarden.sh
```

Expected:
- exits `0`
- prints `Created Bitwarden item: dotfiles/workstation-ssh-key`
- prints a public key beginning with `ssh-ed25519`
- does not print an OpenSSH private key block

- [ ] **Step 5: Register the public key in GitHub manually**

Use the public key printed by the helper.

Add it in GitHub:

```text
Settings -> SSH and GPG keys -> New SSH key
Key type: Authentication Key
Title: workstation
Key: <printed public key>
```

Add the same public key again:

```text
Settings -> SSH and GPG keys -> New SSH key
Key type: Signing Key
Title: workstation-signing
Key: <printed public key>
```

Expected: GitHub shows one authentication key and one signing key for the workstation public key.

---

## Task 2: Add Dotfiles Templates for the Stable SSH Key

**Files:**
- Create: `/home/aperture/repos/dotfiles/private_dot_ssh/private_id_ed25519.tmpl`
- Create: `/home/aperture/repos/dotfiles/private_dot_ssh/id_ed25519.pub.tmpl`

- [ ] **Step 1: Create the private key template**

Create `/home/aperture/repos/dotfiles/private_dot_ssh/private_id_ed25519.tmpl`:

```gotemplate
{{ (bitwarden "item" "dotfiles/workstation-ssh-key").notes }}
```

Expected target path after chezmoi apply: `~/.ssh/id_ed25519` with private file permissions from chezmoi's `private_` attribute.

- [ ] **Step 2: Create the public key template**

Create `/home/aperture/repos/dotfiles/private_dot_ssh/id_ed25519.pub.tmpl`:

```gotemplate
{{ (bitwardenFields "item" "dotfiles/workstation-ssh-key").public_key.value }}
```

Expected target path after chezmoi apply: `~/.ssh/id_ed25519.pub`.

- [ ] **Step 3: Verify template syntax through chezmoi**

Run from `/home/aperture/repos/dotfiles` with `BW_SESSION` set:

```bash
chezmoi execute-template < private_dot_ssh/private_id_ed25519.tmpl >/tmp/dotfiles-private-key-rendered
chezmoi execute-template < private_dot_ssh/id_ed25519.pub.tmpl >/tmp/dotfiles-public-key-rendered
test -s /tmp/dotfiles-private-key-rendered
test -s /tmp/dotfiles-public-key-rendered
rm -f /tmp/dotfiles-private-key-rendered /tmp/dotfiles-public-key-rendered
```

Expected: all commands exit `0`; no private key content is printed.

---

## Task 3: Add Dotfiles Scripts for GitHub SSH State

**Files:**
- Create: `/home/aperture/repos/dotfiles/.chezmoiscripts/run_after_github-known-hosts.sh.tmpl`
- Create: `/home/aperture/repos/dotfiles/.chezmoiscripts/run_after_switch-chezmoi-origin-to-ssh.sh.tmpl`

- [ ] **Step 1: Create the GitHub known_hosts script**

Create `/home/aperture/repos/dotfiles/.chezmoiscripts/run_after_github-known-hosts.sh.tmpl`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ssh_dir="$HOME/.ssh"
known_hosts="$ssh_dir/known_hosts"

mkdir -p "$ssh_dir"
chmod 700 "$ssh_dir"
touch "$known_hosts"
chmod 600 "$known_hosts"

tmp_file="$(mktemp)"
trap 'rm -f "$tmp_file"' EXIT

ssh-keyscan -t ed25519 github.com > "$tmp_file" 2>/dev/null

if [ ! -s "$tmp_file" ]; then
  echo "Failed to fetch github.com SSH host key with ssh-keyscan." >&2
  exit 1
fi

ssh-keygen -R github.com -f "$known_hosts" >/dev/null 2>&1 || true
cat "$tmp_file" >> "$known_hosts"
```

- [ ] **Step 2: Create the chezmoi remote switch script**

Create `/home/aperture/repos/dotfiles/.chezmoiscripts/run_after_switch-chezmoi-origin-to-ssh.sh.tmpl`:

```bash
#!/usr/bin/env bash
set -euo pipefail

source_dir="{{ .chezmoi.sourceDir }}"
expected_https="https://github.com/faviann/dotfiles.git"
expected_https_no_suffix="https://github.com/faviann/dotfiles"
expected_ssh="git@github.com:faviann/dotfiles.git"

if [ ! -d "$source_dir/.git" ]; then
  echo "chezmoi source repo is not a git checkout: $source_dir" >&2
  exit 1
fi

current_remote="$(git -C "$source_dir" remote get-url origin 2>/dev/null || true)"

case "$current_remote" in
  "$expected_ssh")
    exit 0
    ;;
  "$expected_https"|"$expected_https_no_suffix")
    git -C "$source_dir" remote set-url origin "$expected_ssh"
    ;;
  "")
    echo "chezmoi source repo has no origin remote: $source_dir" >&2
    exit 1
    ;;
  *)
    echo "Refusing to change unexpected chezmoi origin remote: $current_remote" >&2
    exit 1
    ;;
esac
```

- [ ] **Step 3: Check shell syntax**

Run from `/home/aperture/repos/dotfiles`:

```bash
bash -n .chezmoiscripts/run_after_github-known-hosts.sh.tmpl
chezmoi execute-template < .chezmoiscripts/run_after_switch-chezmoi-origin-to-ssh.sh.tmpl >/tmp/dotfiles-switch-origin-rendered.sh
bash -n /tmp/dotfiles-switch-origin-rendered.sh
rm -f /tmp/dotfiles-switch-origin-rendered.sh
```

Expected: all commands exit `0`.

---

## Task 4: Update Dotfiles Bootstrap Documentation and Commit

**Files:**
- Modify: `/home/aperture/repos/dotfiles/BOOTSTRAP.md`

- [ ] **Step 1: Replace the bootstrap guide**

Replace `/home/aperture/repos/dotfiles/BOOTSTRAP.md` with:

````markdown
# Bootstrap - New Machine Setup

Run these steps in order on any new machine.

## 1. Install chezmoi and Bitwarden CLI

On the workstation LXC these are installed by `ServerManagementScripts`.

For a standalone machine:

```bash
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b ~/.local/bin
npm install -g @bitwarden/cli
```

## 2. Unlock Bitwarden

```bash
bw login                                  # first time only
export BW_SESSION=$(bw unlock --raw)
```

`BW_SESSION` must be present for templates that restore private files.

## 3. Apply dotfiles

Use HTTPS for the first clone because the SSH key is restored by this repo:

```bash
chezmoi init --apply https://github.com/faviann/dotfiles.git
```

During apply, chezmoi restores:

- `~/.ssh/id_ed25519`
- `~/.ssh/id_ed25519.pub`
- `~/.ssh/config`
- `~/.ssh/allowed_signers`
- `~/.gitconfig`
- `~/.ansible/vault-pass`

After apply, the chezmoi source remote is switched to:

```text
git@github.com:faviann/dotfiles.git
```

## GitHub SSH Key Registration

The workstation key is stored in Bitwarden item:

```text
dotfiles/workstation-ssh-key
```

Item shape:

- notes: OpenSSH private key
- custom field `public_key`: matching public key line

Register the public key in GitHub twice:

1. **Authentication Key**
   - GitHub path: Settings -> SSH and GPG keys -> New SSH key
   - Title: `workstation`
   - Key type: Authentication Key
2. **Signing Key**
   - GitHub path: Settings -> SSH and GPG keys -> New SSH key
   - Title: `workstation-signing`
   - Key type: Signing Key

## Verify

```bash
test -s ~/.ssh/id_ed25519
test -s ~/.ssh/id_ed25519.pub
diff <(ssh-keygen -y -f ~/.ssh/id_ed25519) <(awk 'NF >= 2 { print $1 " " $2; exit }' ~/.ssh/id_ed25519.pub)
ssh -T git@github.com
git config --global --get user.signingkey
cat ~/.ansible/vault-pass | wc -c
```

Expected:

- key files exist
- `diff` exits `0`
- `ssh -T git@github.com` authenticates as `faviann`
- signing key config prints `~/.ssh/id_ed25519.pub`
- vault passphrase byte count is greater than `1`

## Optional GitHub CLI Auth

Git-over-SSH does not require `gh auth login`.

For `gh pr`, `gh issue`, `gh workflow`, or `gh api` commands:

```bash
gh auth login --git-protocol ssh --skip-ssh-key
```

`--skip-ssh-key` prevents `gh` from generating or uploading another SSH key.

## Rotation Runbook

Rotation is manual.

1. Generate a new dedicated workstation key.
2. Update Bitwarden item notes with the new private key.
3. Update Bitwarden custom field `public_key` with the new public key.
4. Add the new public key to GitHub as Authentication Key.
5. Add the new public key to GitHub as Signing Key.
6. Run:

   ```bash
   export BW_SESSION=$(bw unlock --raw)
   chezmoi apply
   ```

7. Run the verification commands.
8. Remove the old authentication and signing keys from GitHub.

## Day-to-day: pull and re-apply

```bash
export BW_SESSION=$(bw unlock --raw)
chezmoi update
```

## Hostname contract

The LXC workstation must be named `workstation` when provisioned by `ServerManagementScripts`.
This triggers `is_lxc = true` in `.chezmoi.toml.tmpl`, which skips fish config on that machine.

When lifecycle playbooks run from the workstation itself, they exclude that host by default. To manage it intentionally, run from `ServerManagementScripts`:

```bash
ansible-playbook site.yml -e proxmox_skip_self=false --limit workstation
```
````

- [ ] **Step 2: Review the docs for accidental secrets**

Run:

```bash
rg -n "BEGIN OPENSSH PRIVATE KEY|vault_proxmox|token_secret|password:" /home/aperture/repos/dotfiles/BOOTSTRAP.md /home/aperture/repos/dotfiles/private_dot_ssh
```

Expected: no output.

- [ ] **Step 3: Commit dotfiles changes**

Run from `/home/aperture/repos/dotfiles`:

```bash
git status --short
git add \
  BOOTSTRAP.md \
  private_dot_ssh/private_id_ed25519.tmpl \
  private_dot_ssh/id_ed25519.pub.tmpl \
  .chezmoiscripts/run_after_github-known-hosts.sh.tmpl \
  .chezmoiscripts/run_after_switch-chezmoi-origin-to-ssh.sh.tmpl
git commit -m "feat: restore workstation github ssh identity"
```

Expected: a commit containing only the five listed dotfiles changes.

---

## Task 5: Apply and Verify Dotfiles on the Workstation

**Files:**
- Runtime verification only

- [ ] **Step 1: Apply dotfiles over HTTPS on the workstation**

Run on the workstation as `faviann` with `BW_SESSION` set:

```bash
chezmoi init --apply https://github.com/faviann/dotfiles.git
```

Expected:
- chezmoi apply exits `0`
- no private key content is printed
- `~/.ssh/id_ed25519` exists
- `~/.ssh/id_ed25519.pub` exists

- [ ] **Step 2: Verify key files and GitHub SSH**

Run on the workstation:

```bash
test -s ~/.ssh/id_ed25519
test -s ~/.ssh/id_ed25519.pub
diff <(ssh-keygen -y -f ~/.ssh/id_ed25519) <(awk 'NF >= 2 { print $1 " " $2; exit }' ~/.ssh/id_ed25519.pub)
ssh -T git@github.com
git config --global --get user.signingkey
git -C ~/.local/share/chezmoi remote get-url origin
```

Expected:
- `test` commands exit `0`
- `diff` exits `0`
- `ssh -T git@github.com` authenticates as `faviann`
- signing key config prints `~/.ssh/id_ed25519.pub`
- remote URL is `git@github.com:faviann/dotfiles.git`

---

## Task 6: Update Failing Tests for Infra Cleanup

**Files:**
- Modify: `tests/unit/test_workstation_baseline_role.py`
- Modify: `tests/regression/fixtures/workstation_baseline_github_keys_test.yml`
- Modify: `tests/regression/test_workstation_baseline_github_keys.py`
- Delete: `tests/regression/fixtures/workstation_baseline_empty_github_keys_test.yml`

- [ ] **Step 1: Replace the workstation baseline unit test**

Replace `tests/unit/test_workstation_baseline_role.py` with:

```python
#!/usr/bin/env python3
"""Contract tests for the workstation baseline role."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class WorkstationBaselineRoleTests(unittest.TestCase):
    def test_role_defaults_contract(self) -> None:
        defaults = load_yaml(REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml")

        self.assertEqual(defaults["workstation_username"], "{{ docker_user }}")
        self.assertEqual(defaults["workstation_uid"], "{{ docker_uid }}")
        self.assertEqual(defaults["workstation_gid"], "{{ docker_gid }}")
        self.assertNotIn("workstation_github_known_host_name", defaults)
        self.assertNotIn("workstation_github_ssh_private_key_path", defaults)
        self.assertNotIn("workstation_github_register_public_key", defaults)

        lxc_github_keys_defaults = load_yaml(REPO_ROOT / "playbooks/roles/config/lxc_github_keys/defaults/main.yml")
        self.assertEqual(lxc_github_keys_defaults["lxc_github_keys_base_url"], "https://github.com")
        self.assertTrue(
            {
                "tmux",
                "mosh",
                "gh",
                "jq",
                "ripgrep",
                "fd-find",
                "fzf",
                "tree",
                "zip",
                "unzip",
                "build-essential",
                "pkg-config",
                "python3-venv",
                "python3-pip",
                "pipx",
                "nodejs",
                "npm",
            }.issubset(set(defaults["workstation_packages"])),
            msg="workstation_packages is missing expected baseline tools",
        )

    def test_lifecycle_wires_workstation_baseline_role_once(self) -> None:
        tasks = load_yaml(REPO_ROOT / "playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/configure.yml")
        flat_tasks = []
        for task in tasks:
            flat_tasks.append(task)
            flat_tasks.extend(task.get("block", []))
        matching_tasks = [task for task in flat_tasks if task.get("name") == "Configure workstation baseline"]

        self.assertEqual(len(matching_tasks), 1)

        task = matching_tasks[0]
        include_role = next(
            (value for key, value in task.items() if key.endswith("include_role")),
            None,
        )
        self.assertIsNotNone(include_role)
        self.assertEqual(include_role["name"], "config/lxc_workstation_baseline")

        when_value = task.get("when")
        if isinstance(when_value, list):
            when_text = " ".join(str(item) for item in when_value)
        else:
            when_text = str(when_value)
        self.assertIn("workstation_enabled | default(false)", when_text)

    def test_role_tasks_keep_baseline_tools_without_outbound_github_identity(self) -> None:
        tasks = load_yaml(REPO_ROOT / "playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml")
        task_names = [t.get("name") for t in tasks]

        self.assertIn("Install workstation baseline packages", task_names)
        self.assertIn("Configure GitHub SSH keys", task_names)
        self.assertIn("Install chezmoi", task_names)
        self.assertIn("Install bw CLI", task_names)

        removed_task_names = {
            "Fetch GitHub SSH host key on controller",
            "Ensure github.com known_hosts entry exists",
            "Ensure workstation GitHub known_hosts permissions",
            "Generate workstation GitHub SSH keypair",
            "Ensure workstation GitHub SSH key ownership",
            "Read workstation GitHub SSH public key",
            "Set workstation GitHub SSH public key fact",
            "Verify GitHub CLI auth is available on controller",
            "List registered GitHub SSH public keys on controller",
            "Register workstation GitHub SSH public key on controller",
        }
        self.assertTrue(
            removed_task_names.isdisjoint(task_names),
            msg="workstation baseline still manages outbound GitHub SSH identity",
        )

        rendered_tasks = "\n".join(str(task) for task in tasks)
        self.assertNotIn("workstation_github_", rendered_tasks)
        self.assertNotIn("gh auth status", rendered_tasks)
        self.assertNotIn("user/keys", rendered_tasks)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Replace the success regression fixture**

Replace `tests/regression/fixtures/workstation_baseline_github_keys_test.yml` with:

```yaml
---
- name: Test workstation baseline inbound GitHub keys
  hosts: localhost
  connection: local
  gather_facts: false
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
            *get.chezmoi.io)
              printf '%s\n' '#!/bin/sh' 'exit 0'
              ;;
            *)
              echo "unexpected curl url: $url" >&2
              exit 1
              ;;
          esac

    - name: Place mock npm on PATH
      ansible.builtin.copy:
        dest: "{{ temp_root }}/npm"
        mode: "0755"
        content: |
          #!/bin/sh
          exit 0

    - name: Include workstation baseline role with mock commands on PATH
      block:
        - ansible.builtin.include_role:
            name: config/lxc_workstation_baseline
      environment:
        PATH: "{{ temp_root }}:{{ lookup('env', 'PATH') }}"

    - name: Stat workstation ssh directory
      ansible.builtin.stat:
        path: "{{ workstation_home }}/.ssh"
      register: workstation_ssh_dir_stat

    - name: Stat workstation authorized_keys
      ansible.builtin.stat:
        path: "{{ workstation_home }}/.ssh/authorized_keys"
      register: workstation_authorized_keys_stat

    - name: Stat workstation GitHub private key
      ansible.builtin.stat:
        path: "{{ workstation_home }}/.ssh/id_ed25519"
      register: workstation_private_key_stat

    - name: Stat workstation known_hosts
      ansible.builtin.stat:
        path: "{{ workstation_home }}/.ssh/known_hosts"
      register: workstation_known_hosts_stat

    - name: Read workstation authorized_keys
      ansible.builtin.slurp:
        src: "{{ workstation_home }}/.ssh/authorized_keys"
      register: workstation_authorized_keys_content

    - name: Assert workstation baseline only writes inbound GitHub authorized_keys
      ansible.builtin.assert:
        that:
          - workstation_ssh_dir_stat.stat.uid == workstation_uid
          - workstation_ssh_dir_stat.stat.gid == workstation_gid
          - workstation_ssh_dir_stat.stat.mode == "0700"
          - workstation_authorized_keys_stat.stat.uid == workstation_uid
          - workstation_authorized_keys_stat.stat.gid == workstation_gid
          - workstation_authorized_keys_stat.stat.mode == "0600"
          - (workstation_authorized_keys_content.content | b64decode) == "ssh-ed25519 AAAATESTKEYONE faviann@laptop\nssh-ed25519 AAAATESTKEYTWO faviann@phone\n"
          - not workstation_private_key_stat.stat.exists
          - not workstation_known_hosts_stat.stat.exists
        fail_msg: "Workstation baseline should only manage inbound authorized_keys, not outbound GitHub identity"
```

- [ ] **Step 3: Replace the regression runner**

Replace `tests/regression/test_workstation_baseline_github_keys.py` with:

```python
#!/usr/bin/env python3
"""Regression test for workstation baseline inbound GitHub key population."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SUCCESS_PLAYBOOK = REPO_ROOT / "tests" / "regression" / "fixtures" / "workstation_baseline_github_keys_test.yml"
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

    with tempfile.TemporaryDirectory(prefix="workstation-baseline-github-keys-success-") as temp_root:
        success = run_playbook(SUCCESS_PLAYBOOK, temp_root)

    success_output = f"{success.stdout}\n{success.stderr}"
    if success.returncode != 0:
        print("success playbook failed unexpectedly", file=sys.stderr)
        print(success_output, file=sys.stderr)
        return 1

    print("ok: workstation baseline writes inbound GitHub authorized_keys without outbound identity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Delete the obsolete empty-key fixture**

Delete:

```text
tests/regression/fixtures/workstation_baseline_empty_github_keys_test.yml
```

The shared empty-key behavior is still covered by:

```bash
python3 tests/regression/test_lxc_github_keys.py
```

- [ ] **Step 5: Run the updated tests and confirm they fail**

Run from `/home/aperture/ServerManagementScripts`:

```bash
python3 -m pytest tests/unit/test_workstation_baseline_role.py -v
python3 tests/regression/test_workstation_baseline_github_keys.py
```

Expected:
- unit test fails because `workstation_github_*` defaults/tasks still exist
- regression test fails because the role still creates outbound GitHub key state

---

## Task 7: Remove Outbound GitHub Identity From the Infra Role

**Files:**
- Modify: `playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml`
- Modify: `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml`
- Modify: `playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml`

- [ ] **Step 1: Replace workstation baseline tasks**

Replace `playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml` with:

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

- name: Install chezmoi
  ansible.builtin.shell:
    cmd: sh -c "$(curl -fsLS get.chezmoi.io)" -- -b /usr/local/bin
    creates: /usr/local/bin/chezmoi

- name: Install bw CLI
  ansible.builtin.shell:
    cmd: npm install -g @bitwarden/cli
    creates: /usr/local/bin/bw
```

- [ ] **Step 2: Replace workstation baseline defaults**

Replace `playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml` with:

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
  - nodejs
  - npm
```

- [ ] **Step 3: Replace workstation baseline argument specs**

Replace `playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml` with:

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

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest tests/unit/test_workstation_baseline_role.py -v
python3 tests/regression/test_workstation_baseline_github_keys.py
python3 tests/regression/test_lxc_github_keys.py
```

Expected:
- unit test passes
- workstation baseline regression passes
- shared `lxc_github_keys` regression passes

---

## Task 8: Shrink Infra Handoff Docs

**Files:**
- Modify: `docs/workstation-post-provisioning-handoff.md`

- [ ] **Step 1: Replace the handoff doc**

Replace `docs/workstation-post-provisioning-handoff.md` with:

````markdown
# Workstation Post-Provisioning Handoff

Use this after the `workstation` LXC has been provisioned by this repo.

## Boundary

`ServerManagementScripts` makes the workstation baseline-ready:

- normal managed LXC in `tier_large` + `cap_docker`
- non-root daily user: `faviann`
- inbound SSH access for `faviann` from GitHub public keys listed in `lxc_github_users`
- Docker runtime support with `docker_user: faviann`
- baseline packages installed by `config/lxc_workstation_baseline`
- `gh`, `chezmoi`, and `bw` installed but not personally authenticated

The separate `dotfiles` repo makes the workstation operator-ready.

## Operator Readiness

Follow the bootstrap documentation in:

```text
~/repos/dotfiles/BOOTSTRAP.md
```

That repo owns personal workstation state such as:

- outbound GitHub SSH identity
- Git SSH signing config
- GitHub `known_hosts`
- `~/.ansible/vault-pass`
- shell and personal workflow config
- optional `gh auth login`

Do not duplicate those personal bootstrap details here.

## Recovery Reminder

If the workstation is lost:

1. Recreate the LXC baseline from this repo.
2. Apply the separate dotfiles bootstrap.
3. Verify operator readiness using the dotfiles verification commands.
````

- [ ] **Step 2: Remove stale controller `gh auth` prerequisite from deployment plan**

Open `docs/superpowers/plans/2026-04-24-workstation-deployment.md`.

Delete the section that says:

````markdown
**Step 2 - Verify GitHub CLI auth is present:**

```bash
gh auth status
```

If not logged in, run `gh auth login` (browser-based; agent cannot do this) and complete it now.
````

Replace later references to controller-side `gh auth status` with:

```markdown
`gh auth status` is not required for provisioning. GitHub CLI API auth is a separate optional operator step owned by the dotfiles bootstrap.
```

- [ ] **Step 3: Search for stale controller-side GitHub key registration wording**

Run:

```bash
rg -n "Register workstation GitHub|workstation_github_|gh auth status|user/keys|Signing Key|Authentication Key|dotfiles/workstation-ssh-key" docs README.md AGENTS.md playbooks inventory tests
```

Expected:
- no operational docs in this repo contain the Bitwarden item name
- no role/default/test references to `workstation_github_`
- only historical specs/plans mention detailed personal key registration

---

## Task 9: Final Verification and Commits

**Files:**
- Dotfiles files from Tasks 2-4
- ServerManagementScripts files from Tasks 6-8

- [ ] **Step 1: Run infra focused verification**

Run from `/home/aperture/ServerManagementScripts`:

```bash
python3 -m pytest tests/unit/test_workstation_baseline_role.py -v
python3 tests/regression/test_workstation_baseline_github_keys.py
python3 tests/regression/test_lxc_github_keys.py
```

Expected: all pass.

- [ ] **Step 2: Run broader unit verification**

Run:

```bash
python3 -m pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 3: Review staged infra diff**

Run:

```bash
git status --short
git diff -- playbooks/roles/config/lxc_workstation_baseline tests docs/workstation-post-provisioning-handoff.md docs/superpowers/plans/2026-04-24-workstation-deployment.md
```

Expected:
- diff only removes outbound GitHub identity from workstation baseline
- diff keeps inbound `lxc_github_keys`
- handoff doc points to dotfiles without duplicating secret item details

- [ ] **Step 4: Commit infra cleanup**

Run from `/home/aperture/ServerManagementScripts`:

```bash
git add \
  playbooks/roles/config/lxc_workstation_baseline/tasks/main.yml \
  playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml \
  playbooks/roles/config/lxc_workstation_baseline/meta/argument_specs.yml \
  tests/unit/test_workstation_baseline_role.py \
  tests/regression/fixtures/workstation_baseline_github_keys_test.yml \
  tests/regression/test_workstation_baseline_github_keys.py \
  docs/workstation-post-provisioning-handoff.md \
  docs/superpowers/plans/2026-04-24-workstation-deployment.md
git rm tests/regression/fixtures/workstation_baseline_empty_github_keys_test.yml
git commit -m "refactor(workstation): move github ssh identity to dotfiles"
```

Expected: commit succeeds and contains only the infra cleanup files.

If SSH commit signing fails in the non-interactive agent session, verify the diff and use:

```bash
git commit --no-gpg-sign -m "refactor(workstation): move github ssh identity to dotfiles"
```

- [ ] **Step 5: Final live check from controller**

Run from `/home/aperture/ServerManagementScripts`:

```bash
ssh -l faviann -i .ansible/ssh/proxmox_lxc workstation.faviann.vms \
  'test -s ~/.ssh/id_ed25519 && test -s ~/.ssh/id_ed25519.pub && git -C ~/.local/share/chezmoi remote get-url origin && git config --global --get user.signingkey'
```

Expected:
- SSH succeeds
- remote URL is `git@github.com:faviann/dotfiles.git`
- signing key config prints `~/.ssh/id_ed25519.pub`

---

## References

- Design spec: `docs/superpowers/specs/2026-04-24-workstation-github-ssh-identity-design.md`
- Chezmoi scripts: https://www.chezmoi.io/user-guide/use-scripts-to-perform-actions/
- Chezmoi Bitwarden functions: https://www.chezmoi.io/user-guide/password-managers/bitwarden/
