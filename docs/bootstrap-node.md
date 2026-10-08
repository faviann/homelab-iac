# Bootstrap Node

Read before any interrupting workstation change, or when the workstation is
unreachable.

The `bootstrap` LXC (vmid 311, `tier_small`, no capability groups) is the
second control node. Its only target is the workstation. The workstation
creates it and keeps it patched through ordinary runs, like any other LXC, and
it stays on. Ansible installs `git`, `unzip`, chezmoi, a pinned `uv`, and the
native Bitwarden CLI, and makes the first clone of this repository at
`/root/homelab-iac`. Ansible never moves that checkout again and never
delivers the node's secrets.

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
