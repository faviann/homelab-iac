# Copy the control-node secrets from the workstation

#534 gave the bootstrap node its vault passphrase and fleet key through one
human Bitwarden unlock and `chezmoi apply` on the node, after its first run and
after every rebuild. Every `./run.sh --limit bootstrap` from the workstation
now copies both from the workstation's `~/.ansible` to root on the node, mode
`0600` (the public key `0644`), with `no_log` and no diff. The dotfiles
bootstrap profile stops managing those files, so chezmoi and Ansible never
write them both.

## Why

- The passphrase and the key already sit on both control nodes' disks. A
  copy from one to the other over the fleet's own SSH adds no new place they
  live and no new reader.
- A rebuilt node is ready after its first run, with no person at a Bitwarden
  prompt. The nightly deploy no longer waits on that step.
- After `./vault.sh rotate`, the node's refresh is an ordinary run from `main`
  instead of a manual unlock on the node.

Bitwarden stays the backup of record and the workstation's source. When both
control nodes are down, `scripts/recover-bootstrap-node.sh` writes the files
on the temporary node from Bitwarden directly.

## Accepted costs

- The node holds whatever the deploying controller holds. A wrong passphrase
  on the workstation reaches the node on its next run.
- A rotation leaves the node on the old passphrase until a person or agent
  runs `./run.sh --limit bootstrap` once the rekeyed vault is on `main`. A
  nightly deploy in between fails to decrypt the vault.

## Rejected

- **Keeping the unlock (#534)**: it bought no isolation, since the same
  secrets reach the same node either way, and it made every rebuild and
  rotation wait on a person.
- **The node fetching from Bitwarden on its own**: it would need a stored
  Bitwarden credential on the node, a secret the fleet does not hold today.
