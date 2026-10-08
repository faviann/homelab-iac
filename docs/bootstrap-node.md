# Bootstrap Node

Read before any interrupting workstation change, or when the workstation is
unreachable.

The `bootstrap` LXC (vmid 311, `tier_small`, no capability groups) is the
second control node. Its only target is the workstation. The workstation
creates it and keeps it patched through ordinary runs, like any other LXC, and
it stays on. Ansible installs `git`, `unzip`, chezmoi, a pinned `uv`, and the
native Bitwarden CLI, and makes the first clone of this repository at
`/root/homelab-iac`. Ansible never moves that checkout again. It delivers the
deploy notification webhook, but never the vault passphrase or the fleet key.

## The recipe

Interrupting workstation runs, rebuilds, and recovery of an unreachable
workstation run on this node through two template units. The instance name is
the git ref to deploy. People give a full commit SHA that is already on
GitHub: the deploy fetches it from `origin` and checks it out detached, so
unpushed code fails at the fetch.

- `workstation-deploy@<sha>` runs `./run.sh --limit workstation`. It interrupts
  the workstation only when the busy probe reports idle.
- `workstation-deploy-interrupt@<sha>` adds `--interrupt-busy`. It is the
  consent to interrupt a working agent, so start it only on a person's
  explicit request.

Start the unit from the workstation:

```bash
ssh -l root -i ~/.ansible/ssh/proxmox_lxc bootstrap.faviann.vms \
  'systemctl start --no-block workstation-deploy@<full-sha>'
```

The unit keeps running if the workstation restarts. Read the result from the
journal afterwards, never by streaming it. `-I` selects the unit's latest
invocation, so there is no ID to carry across a restart, and the last lines
hold systemd's own record of the exit status:

```bash
ssh -l root -i ~/.ansible/ssh/proxmox_lxc bootstrap.faviann.vms \
  'journalctl --no-pager -u workstation-deploy@<full-sha>.service -I | tail -40'
```

`journalctl --list-invocations -u workstation-deploy@<full-sha>.service` lists
earlier runs of the same unit. Every outcome is also posted to Discord with
the unit name, which carries the ref, the SHA the checkout is at, and the exit
status: `0` applied, `3` deferred, `75` another deploy was in flight, anything
else failed. A failed deploy goes to a person with the journal excerpt; do not
retry it.

Two deploys never overlap. A deploy of another unit started while one runs
exits `75` at once; starting the same unit again joins the run in flight.
Nobody runs `./run.sh` directly in `/root/homelab-iac`: the units own that
checkout and move it to the ref they deploy.

## The nightly run

`workstation-deploy.timer` starts `workstation-deploy@main` every night at
03:00 node-local time. The deploy fetches `origin/main` at that moment, so it
ships whatever was merged by then, and it never passes `--interrupt-busy`.
When the busy probe reports idle, the
[interrupting steps](../stacks/README.md#busy-checks) land with everything
else. When it reports busy, the run applies everything else and exits `3`:
deferred tonight. Every night's
outcome is posted to Discord, so a streak of deferred nights or a 03:00
failure shows up there. A missed night is not caught up, so a node restart
during the day never starts a deploy.

Read last night's run:

```bash
ssh -l root -i ~/.ansible/ssh/proxmox_lxc bootstrap.faviann.vms \
  'journalctl --no-pager -u workstation-deploy@main.service -I | tail -60'
```

Before work that must not be interrupted overnight, pause the timer:

```bash
ssh -l root -i ~/.ansible/ssh/proxmox_lxc bootstrap.faviann.vms \
  'systemctl stop workstation-deploy.timer'
```

The next run against this node starts it again.

## The probe

Every run against the workstation first asks its busy probe,
`/usr/local/sbin/workstation-busy-probe`. It reports busy while a herdr agent
is `working`, or while a run holds the workstation's lifecycle lock, which
covers a background `./run.sh` whose agent turn already ended. A `blocked`
pane, waiting on a permission prompt, does not count. The probe reports idle
when herdr is not running or not installed, and busy on any other error. A run
that includes its own control node defers without asking it.

To see why a run deferred, list the agents on the workstation:

```bash
herdr agent list
```

## Why

The workstation is both a control node and where agents work, so a run that
restarts it kills the run itself and every agent turn in flight. Interrupting
workstation changes therefore never run in place. They run from this node,
with `--interrupt-busy` as a person's consent, or overnight once the
workstation's busy probe reports idle.
[ADR-0018](adr/0018-run-interrupting-workstation-changes-from-the-bootstrap-node.md)
records the consent rule and the alternatives it rejected.

## Setting up the node

The node needs the vault passphrase and the fleet key before it can run
anything. Set them up after the first `./run.sh --limit bootstrap` and after
every rebuild of the node, because a rebuild wipes `/root` and the secrets in
it, and nothing keeps them on host storage. Follow the bootstrap-node path in
the dotfiles `BOOTSTRAP.md` for the Bitwarden and `chezmoi init --apply`
steps. They run as root on the node, which you reach with the fleet key:
`ssh -l root -i ~/.ansible/ssh/proxmox_lxc bootstrap.faviann.vms`. Then
verify on the node, in its checkout:

```bash
cd /root/homelab-iac
./vault.sh check
./inspect.sh connectivity --limit workstation
```

`./vault.sh rotate` refreshes only the workstation's copy of the passphrase.
After a rotation, commit and push the rekeyed vault, then refresh the node
with the line rotate prints:

```text
Refresh the bootstrap node: ssh -l root -i ~/.ansible/ssh/proxmox_lxc bootstrap.faviann.vms, then export BW_SESSION="$(bw unlock --raw)" && bw sync && chezmoi apply ~/.ansible/vault-pass && bw lock
```

Skip `./vault.sh check` on the node after a rotation: its checkout keeps the
vault from the last ref it deployed until its next deploy fetches the
rekeyed one.

## Reaching the node when the workstation is dead

Root's `authorized_keys` on the node holds only the fleet key. When the
workstation is dead, open the Proxmox host's shell (its Shell in the Proxmox
web UI) and run `pct enter 311`. The container's own Console tab stops at a
login prompt, because root has no password.
