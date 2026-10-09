# Bootstrap Node

Read before any interrupting workstation change, when the workstation is
unreachable, or to find out how last night's deploy went.

The `bootstrap` LXC (vmid 101, `tier_small`, no capability groups) is the
second control node. It runs the nightly deploy of every other LXC and carries
interrupting workstation runs. The workstation creates it and keeps it patched
through ordinary runs, like any other LXC, and it stays on. Its own busy probe
reports busy while a deploy is in flight, so such a run defers the node's
upgrade and reboot instead of killing the deploy. Ansible installs `git`,
`unzip`, chezmoi, a pinned `uv`, and the native Bitwarden CLI, and makes the
first clone of this repository at `/root/homelab-iac`. Ansible never moves
that checkout again. It delivers the deploy notification webhook, Dockhand's
Discord channel (`vault_dockhand_discord_webhook_url`), but never the vault
passphrase or the fleet key.

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

Both units call `/usr/local/sbin/homelab-deploy` with their ref and lifecycle
arguments. The script holds `/run/homelab-deploy.lock`, so two deploys never
overlap. A deploy of another unit started while one runs
exits `75` at once; starting the same unit again joins the run in flight.
Nobody runs `./run.sh` directly in `/root/homelab-iac`: the units own that
checkout and move it to the ref they deploy.

## The nightly deploy

`nightly-deploy.timer` starts `nightly-deploy@main` every night at 03:00
node-local time. The deploy fetches `origin/main` at that moment, so it ships
whatever was merged by then. It runs the lifecycle with no limit, so it
targets every managed LXC; the controller skip leaves out this node, which
the workstation deploys. It never passes `--interrupt-busy`: busy stacks and
hosts defer as in any run, and the workstation's
[interrupting steps](../stacks/README.md#busy-checks) land only when its busy
probe reports idle.

The lifecycle lock is machine-local (#174), so a run on the workstation and
this deploy could configure the same LXC at once. Before the deploy lock and
the checkout, the unit's gate, `/usr/local/sbin/nightly-deploy-gate`, asks
the workstation busy probe over SSH, the way the lifecycle reaches LXCs, with
a 30-second bound:

- idle: the deploy runs.
- busy: an agent is mid-turn or a run holds the workstation's lock. The
  night defers with `workstation: busy (<reason>); nightly deploy not started`.
- anything else, an SSH failure included: the night defers with
  `workstation: check failed (<reason>); nightly deploy not started`. A gate
  that cannot read the workstation never lets the night run.

A deferred night leaves the checkout untouched and exits `3`, with its line
under the same `Deferred by busy checks:` header as a run's deferred stacks.
A collision still happens if an agent starts a run on the workstation while
the nightly deploy is in progress
([ADR-0019](adr/0019-deploy-every-lxc-nightly-from-the-bootstrap-node.md)).

Every night posts one Discord message, `nightly-deploy@main: <outcome>`, with
the exit status and either the deferred hosts and stacks or the gate's line.
A streak of deferred nights or a 03:00 failure shows up there. A run stops at
the first failing host, as any lifecycle run does. A missed night is not
caught up, so a node restart during the day never starts a deploy.

Read last night's run:

```bash
ssh -l root -i ~/.ansible/ssh/proxmox_lxc bootstrap.faviann.vms \
  'journalctl --no-pager -u nightly-deploy@main.service -I | tail -60'
```

Before work that must not be interrupted overnight, pause the timer:

```bash
ssh -l root -i ~/.ansible/ssh/proxmox_lxc bootstrap.faviann.vms \
  'systemctl stop nightly-deploy.timer'
```

The next run against this node starts it again.

A person may start `nightly-deploy@<full-sha>` by hand, for verification or
when recovery needs the other LXCs patched; agents never start it. Outside
03:00 it reboots hosts and recreates stacks during working hours.

## The probe

Every run against the workstation first asks its busy probe,
`/usr/local/sbin/workstation-busy-probe`. It reports busy while a herdr agent
is in any state but `idle`, `done`, or `blocked` (`working`, but also
`unknown` and any state a later herdr adds), or while a run holds the
workstation's lifecycle lock, which covers a background `./run.sh` whose agent
turn already ended. A `blocked` pane, waiting on a permission prompt, does not
count. The probe reports idle
when herdr is not running or not installed, and busy on any other error. A run
that includes its own control node defers whatever it says.

To see why a run deferred, list the agents on the workstation:

```bash
herdr agent list
```

## Why

The workstation is both a control node and where agents work, so a run that
restarts it kills the run itself and every agent turn in flight. Interrupting
workstation changes therefore never run in place. They run from this node,
with `--interrupt-busy` as a person's consent, or overnight in the nightly
deploy once the workstation's busy probe reports idle.
[ADR-0018](adr/0018-run-interrupting-workstation-changes-from-the-bootstrap-node.md)
records the consent rule and the alternatives it rejected;
[ADR-0019](adr/0019-deploy-every-lxc-nightly-from-the-bootstrap-node.md)
records the nightly deploy and its gate.

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
./inspect.sh connectivity
```

The connectivity check must reach every LXC, because the nightly deploy
targets all of them.

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
web UI) and run `pct enter 101`. The container's own Console tab stops at a
login prompt, because root has no password.

## Both control nodes down

When neither the workstation nor this node can run `./run.sh`,
`scripts/recover-bootstrap-node.sh` carries you from the Proxmox host shell to
a working workstation deploy and a recreated node. It is human-only: the
standing permission for runs from the bootstrap node does not cover it, and no
agent runs it.

Fetch it by a full commit SHA on GitHub, read it, run it, then delete it. Run
it from a file, never `curl ... | bash`: the pipe would become the script's
input, so its prompts and Bitwarden's would read the script instead of your
keyboard. As root in the Proxmox host shell:

```bash
sha=<full-sha>
curl -fsSLo /root/recover-bootstrap-node.sh \
  "https://raw.githubusercontent.com/faviann/homelab-iac/$sha/scripts/recover-bootstrap-node.sh"
less /root/recover-bootstrap-node.sh
bash /root/recover-bootstrap-node.sh "$sha"
rm /root/recover-bootstrap-node.sh
```

The host runs only `pct` and `pveam`; everything else runs inside the
containers through `pct exec`, which keeps your terminal attached. The script
never handles a secret: you type it at Bitwarden's own prompts. The stages:

1. Create 101 (`bootstrap`, `tier_small`, DHCP on `vmbr1`, `local-zfs`, the
   newest local `debian-13-standard` template). An existing 101 named
   `bootstrap` is destroyed only after you type `101`; any other 101 stops the
   script.
2. Install `git`, `unzip`, `curl`, `uv`, chezmoi, and `bw`, and clone this
   repository at `<full-sha>` into `/root/homelab-iac`.
3. Unlock: press Enter, then answer Bitwarden's email, master password, and
   2FA prompts, once each. This is the dotfiles bootstrap-node path, with
   `bw login --raw` doing the login and the unlock in one step.
4. On `y`, `./run.sh --limit workstation`. It may restart the workstation
   (a pending reboot after upgrades, or a container config change); if the
   busy probe reports busy, the run defers and exits `3`.
5. Only when that run exits `0`, destroy the temporary node. On any other
   status, or when you decline stage 4, 101 stays up and the script exits
   with that status and prints the command to retry from the Proxmox host shell.
6. The workstation (306, refused unless named `workstation`) runs
   `./run.sh --limit bootstrap` as `faviann` from a throwaway clone at
   `<full-sha>`, using its own vault passphrase and fleet key. On failure,
   for example `75` while another run holds the workstation's lock, the
   script prints the command to rerun.
7. Unlock the recreated node, as in stage 3.

It ends by printing the one remaining check, `./vault.sh check` and
`./inspect.sh connectivity` on the node, as in
[Setting up the node](#setting-up-the-node).
