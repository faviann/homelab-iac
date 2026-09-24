# Command policy

Six Bash commands are the supported interface to this repository for
contributors, operators, and agents. This document records their grammar, the
rules for changing them, the raw commands that remain permitted, and the limits
of what the guards enforce.

## Commands

| Command | Operation | Lock | Agent use |
| --- | --- | --- | --- |
| `./setup.sh` | `sync` | none | yes |
| `./vault.sh` | `check` | none | yes |
| | `set <key> --from-file <path> --create\|--replace [--strip-final-newline]` | none | on explicit request |
| | `rotate --dry-run` | none | yes |
| | `configure`, `edit`, `rotate` | none | human-only |
| `./validate.sh` | *(default)* comprehensive handoff | none | yes |
| | `lint` | none | yes |
| | `lifecycle [--full] [--only <launcher.py>]... [--fail-fast]` | none | yes |
| | `tests [<target>...]` | none | yes |
| | `stack <path>` | none | yes |
| | `renovate` | none | yes |
| `./inspect.sh` | `credentials`, `containers` | shared | yes |
| | `connectivity [--limit <targets>]`, `plan [--limit <targets>]` | shared | yes |
| | `vars <host>`, `vars --graph` | none | yes |
| `./recover.sh` | `ssh-keys [--limit <targets>]` | exclusive | human-only |
| | `proxmox-host-ssh` | exclusive | human-only |
| `./run.sh` | *(default)* `full`, `provision`, `configure` | exclusive | yes |
| | any form with `--check` | shared | yes |

`./run.sh` options: `--limit <targets>` (Ansible limit grammar), `--check`,
`--stack <name>`, `--include-controller`, and `-v`, `-vv`, or `-vvv`. Every
command answers `--help` with its operations.

A human-only operation prompts at a terminal, changes the vault, or enrolls
trust on managed infrastructure, so a person runs it. "On explicit request"
means an agent runs it only when a person asks for that transfer.

### Grammar

```text
./<command>.sh [operation] [options] [-- ansible-arguments]
```

`./run.sh` and `./validate.sh` default to their most common operation.
`./setup.sh`, `./vault.sh`, `./inspect.sh`, and `./recover.sh` require an
operation. None of them has a consequential default.

Only `./run.sh` accepts low-level arguments, and only after `--`. Those
arguments cannot change target selection, lifecycle intent, check mode, the
lock, or the wrapper marker. `./run.sh` rejects them as invalid usage.

Two statuses are guaranteed across all six commands. A command that rejects
its own grammar, such as an unknown operation or option or a missing
operation, exits `2` before it does any work. A live operation exits `75` when
another live operation holds the lock. The live operations are every
`./run.sh` and `./recover.sh` form and every `./inspect.sh` operation except
`vars`, which reads only local inventory, takes no lock, and never returns
`75`. `0` means success.

Every other non-zero status is a failure, and its value depends on the
command. Some operations pass the status of the tool they run through
unchanged:

| Command | Failure statuses |
| --- | --- |
| `./setup.sh`, `./vault.sh` | `1` |
| `./run.sh`, `./recover.sh`, live `./inspect.sh` operations | `1` when the playbook fails. A dependency reconciliation failure passes its own status through, usually `1`. |
| `./inspect.sh vars` | `1` |
| `./validate.sh lint` | `ansible-lint`'s status, for example `2` when it finds violations |
| `./validate.sh lifecycle` | `1` when a launcher fails, and `2` when the runner rejects an unregistered launcher |
| `./validate.sh tests` | pytest's status: `1` for failed tests, `4` for a target pytest cannot load, and `5` when no test was collected |
| `./validate.sh stack` | `1` when the stack policy is invalid |
| `./validate.sh renovate` | pytest's status: `1` when the real Renovate run fails or cannot start, for example without `npx` or registry access, and `5` when the gate test was not collected |
| `./validate.sh` | the status of the first failing gate, checked as lint, then lifecycle, then tests. `130` or `143` when interrupted. |

So a `2` from `./validate.sh` does not always mean invalid usage. Read stderr:
wrapper usage errors name the command and point to `--help`.

The no-argument `./validate.sh`, `lint`, and `tests` first install every
collection pinned in `collections/requirements.yml` that is not already at its
pin. When that fails, for example because Galaxy is unreachable, the command
exits `1` with the reconciliation error before any gate starts.

The stable interface is the documented names, operations, options, exit
status, safety guarantees, and explicit output formats. Terminal prose is for
people and can change. The one machine interface is the schema-versioned JSON
that `./validate.sh stack` writes to stdout.

### The lock

Live operations, meaning every `./run.sh` and `./recover.sh` form and every
`./inspect.sh` operation except `vars`, take one machine-local lock at
`~/.ansible/homelab-iac-lifecycle.lock`. Mutating operations take it
exclusively. Audited read-only operations take it shared, so reads can overlap
each other but never a mutation. A live operation that cannot take the lock
stops at once with status `75`. There is no wait mode. When the holder is
another live operation, the message names its process and worktree. A holder
that took the lock directly, such as the stack-rename `flock` below, leaves no
holder record. The message then cannot identify it,
and any pid and worktree it prints were left in the lock file by an earlier
lock implementation.

The lock covers every worktree on one machine. Its path is under `$HOME`, so a
run with a different home directory takes a different lock and is not
coordinated. It does not coordinate two control nodes either (#174). ADR-0009
records the split.

The lock only decides whether a live run may start. Inside one admitted
lifecycle run, `playbooks/lifecycle-lxcs.yml` executes targeted LXCs one at a
time (`serial: 1`). The first execution failure sets a run-local fail-fast
latch, and every later target in that run reports `not_executed` without
acting. The latch never coordinates separate runs, and no supported command
executes targets concurrently.

## Changing the command set

**A seventh command** needs a distinct safety boundary, availability
requirement, or operator purpose. Related work goes into an existing command
as an operation or option.

**The internal-call rule.** A script may call `uv run --locked <tool>` directly
if and only if that call contacts no managed host. Anything that contacts a
managed host goes through `scripts/lib/live-execution.sh`, which owns the lock,
the wrapper marker, dependency reconciliation, and the playbook call.

## Raw commands

A raw command is any command other than the six that does work they exist to
govern. That means running Ansible, `uv`, `pytest`, or a repository script
directly, or acting on the Proxmox host, its API, or a managed LXC outside the
six commands, through `ssh`, `pct`, `docker`, `curl`, or any other client.
Local workstation tooling that touches none of these, such as `git`, `rg`, or
`tail` on a local log, is not a raw command.

When a supported command owns an operation, tracked guidance uses that
command. For example, `./inspect.sh credentials` owns Proxmox API
reachability, so guidance does not teach a `curl` against the API. A raw
command is documented only for a bounded purpose that no supported operation
owns.

Agent use of a documented raw command is a separate decision:

- Guidance must explicitly permit agent use. Silence means human-only.
- An agent cannot approve its own exception.
- A live bypass needs a person's approval for the exact operation and scope.
  Read-only intent does not waive this.
- Approval given in a conversation covers one operation when it names the
  target, purpose, allowed effects, and relevant safeguards. It expires with
  the task and is not precedent for later work.
- A standing permission is valid only when it is recorded below with all six
  fields.

### Standing permissions

#### Read-only SSH diagnosis of a named host

- **Trigger:** a request to diagnose a named or clearly implied LXC or the
  Proxmox host, where no `./inspect.sh` operation answers the question.
- **Audience:** agents and people.
- **Scope:** the named host only.

  ```bash
  ssh -l root -i ~/.ansible/ssh/proxmox_lxc <host> '<read-only command>'
  ```

- **Boundary:** observational. Non-secret files, logs, processes, memory,
  disks, networking, and service state may be inspected without asking for
  each observation. No file edits, service restarts, package installs, process
  kills, or container changes, and no `docker compose` operations other than
  reads such as `ps` and `logs`.
- **Sensitive output:** do not read or print secrets. This covers `.env`
  files, container environment from `docker inspect`, vault material, and
  private keys. Filter log output that can carry tokens. A masked value from
  `./inspect.sh vars` is not a secret. That exemption covers that one command
  and its documented mask only.
- **Escalation:** when diagnosis needs a mutation, use `./run.sh` or
  `./recover.sh`, or get a person's approval for that exact operation. A host
  the request did not name or clearly imply needs the same approval.

#### Proxmox-host manual key injection

- **Trigger:** `./recover.sh ssh-keys` cannot run at all. For example, the
  control node itself is broken.
- **Audience:** human-only. It is a last resort.
- **Scope:** one container VMID, run on the Proxmox host through `pct exec`, as
  written in [ssh-key-management.md](ssh-key-management.md).
- **Boundary:** mutating. It appends one public key to the container's
  `/root/.ssh/authorized_keys`. It runs outside the machine-local lock, so
  nothing serializes it against a lifecycle run.
- **Sensitive output:** only the public key moves. Never paste a private key.
- **Escalation:** when `./recover.sh ssh-keys` can run, use it instead.

#### Stack-rename remote mutation

- **Trigger:** an explicit request to rename a repository-managed stack,
  handled by the `rename-stack` skill.
- **Audience:** agents after the skill's second approval gate, and people.
- **Scope:** one stack folder on one named host, as written in
  `.agents/skills/rename-stack/SKILL.md`.
- **Boundary:** mutating. It stops the old stack, moves its folder in place,
  and changes ownership. Precondition: no live operation holds the lock. Take
  the lock first, then run the SSH command while holding it, so that no live
  operation can start during the move:

  ```bash
  (
    flock --exclusive --nonblock 9 ||
      { echo "lifecycle lock held: nothing ran" >&2; exit 75; }
    ssh -l root -i ~/.ansible/ssh/proxmox_lxc <host> '<rename commands>'
  ) 9>>~/.ansible/homelab-iac-lifecycle.lock
  ```

  The message tells the two failures apart. The status does not, because the
  remote commands can return any status, including `75`.

  - `lifecycle lock held: nothing ran` means a live operation holds the lock
    and SSH never started. Wait for that operation to finish, then run the
    block again.
  - Any other non-zero status comes from SSH or the remote commands, and the
    move may be partial. Do not retry. Follow the escalation below.

  While the move runs, a live operation started on this machine exits `75` and
  cannot name this holder. The lock is machine-local, so it does not cover a
  run from another control node.
- **Sensitive output:** as for SSH diagnosis.
- **Escalation:** a stack the skill refuses (foundational, OIDC-coupled, or
  with named volumes) needs a dedicated migration that a person plans. A
  failure after SSH starts goes to a person with the command output. Read-only
  SSH diagnosis may establish which of the old and new folders exist, but
  repairing a partial move needs that person's approval.

#### Proxmox RAM report

- **Trigger:** a question about Proxmox host memory, ZFS ARC, or guest memory,
  handled by the `proxmox-ram-usage` skill.
- **Audience:** agents and people.
- **Scope:** the Proxmox host.

  ```bash
  bash .agents/skills/proxmox-ram-usage/proxmox-ram-report.sh
  ```

- **Boundary:** observational. The script reads `/proc`, cgroups, `pvesh`, and
  `ps`.
- **Sensitive output:** none expected. Do not add reads of guest files or
  process environments.
- **Escalation:** when SSH fails, report that live data was not collected. Do
  not infer an answer from stale values.

#### Renovate adapter

- **Trigger:** maintainer work on the image-update Renovate boundary.
- **Audience:** maintainer only. No in-repository code produces the request
  it consumes yet, so a wrapper would wrap a caller that does not exist.
- **Scope:** one request file, as written in
  [image-update-renovate-adapter.md](image-update-renovate-adapter.md).

  ```bash
  uv run --locked python scripts/image_update_renovate_adapter.py <request.json>
  ```

- **Boundary:** observational. It queries public registries and writes
  candidate observations to stdout. It contacts no managed host.
- **Sensitive output:** none. It strips inherited `RENOVATE_*` variables.
- **Escalation:** agents exercise this boundary through its tests, not by
  running the adapter. `./validate.sh` runs the deterministic contract tests.
  `./validate.sh renovate` runs the real pinned Renovate against public
  registries, as
  [image-update-renovate-adapter.md](image-update-renovate-adapter.md)
  requires for adapter changes.

## Superseded forms

| Superseded form | Replacement |
| --- | --- |
| `./run.sh -e stack_filter=<stack>` | `./run.sh --stack <stack>` |
| `./run.sh -e proxmox_skip_self=false` | `./run.sh --include-controller` |
| any other `./run.sh -e <var>=<value>` | `./run.sh -- -e <var>=<value>` |
| `--tags validation` | `./inspect.sh plan` |
| `--tags provision` | `./run.sh provision` |
| `--tags bootstrap` | `./recover.sh proxmox-host-ssh` |
| `ansible-playbook` on a repository playbook | the operation that runs it |
| `ansible -m ping` | `./inspect.sh connectivity` |
| `ansible-inventory --host <host>` | `./inspect.sh vars <host>` |
| `ansible-inventory --list` | none. The whole-inventory dump was removed; `./inspect.sh vars <host>` shows one host |
| `ansible-inventory --graph` | `./inspect.sh vars --graph` |
| `ansible-vault encrypt` | `./vault.sh configure`, which creates the vault |
| `ansible-vault edit` | `./vault.sh edit` |
| `ansible-vault view` | `./vault.sh check`, which verifies the vault without printing values. No operation prints decrypted contents |
| `ansible-lint` | `./validate.sh lint` |
| the lifecycle regression runner | `./validate.sh lifecycle [--full] [--only <launcher.py>]... [--fail-fast]` |
| `pytest`, `python -m unittest`, or a test file run with `python` | `./validate.sh tests [<target>...]`, or `./validate.sh renovate` for the real Renovate compatibility test |
| `python -m stack_update_policy validate` | `./validate.sh stack <path>` |
| `python -c "import proxmoxer, requests"` | none. `./setup.sh sync` repairs the environment it only probed |
| `./configure-vault.sh` | `./vault.sh configure` |
| `./rotate-vault-passphrase.sh` | `./vault.sh rotate` |
| bare `./setup.sh`, `./setup.sh bootstrap` | none. Each command owns its prerequisites (ADR-0011) |
| `ansible-galaxy collection install`, `collection list`, `role install` | none. Live commands and `./validate.sh` reconcile what they consume |

When editing tracked guidance, review command examples against this table and
use the supported command for each operation it owns. In a documented
`./run.sh` invocation, place `-e` and `--extra-vars` after `--`; never place
`--tags` before `--`. The wrapper also rejects `--tags` after `--`, so use a
named operation instead. Record intentional raw-command exceptions under
Standing permissions above. This is a review rule for prose, not an automated
text scan. Validation tests the `./run.sh` grammar, which rejects low-level
options before `--`.

## Recorded boundaries

These are known limits, not defects waiting for a fix.

- The enforcement tests catch only someone who runs `./validate.sh`.
  `AGENTS.md` requires that run before handoff, and nothing enforces anything
  outside it. The wrapper marker is the same kind of guard. It stops accidents,
  not intent.
- `./inspect.sh vars` masks a value that contains a vault value only when that
  vault value has 8 characters or more. A shorter secret can print inside a
  different variable (ADR-0010).
- A secret written into a plain group or host variable file is not a vault
  value, so `./inspect.sh vars` does not mask it.
- A vault key without the `vault_` prefix escapes the name rule.
- A lifecycle launcher run directly, outside `./validate.sh` and pytest, does
  not get the fixture inventory and vault password (ADR-0008).
- A playbook is detected as live when a play targets something other than
  `localhost` or when it imports the Proxmox-host layer. A controller-only
  playbook that delegates to the Proxmox host without importing that layer is
  not detected.
- The lifecycle lock is machine-local. Two control nodes can still collide
  (#174).
- `./validate.sh` requires `/usr/sbin/sshd` (Debian package `openssh-server`).
  The Proxmox trust regression starts an unprivileged `sshd` on `127.0.0.1` so
  that the real `ssh` client decides trust. Validation fails on a machine
  without it, and it installs nothing.
- `./validate.sh` needs no machine-local secret, so a build server can now run
  it after a checkout, a `uv` install, and `openssh-server`. None exists yet
  (#200).
