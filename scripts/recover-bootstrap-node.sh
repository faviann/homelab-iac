#!/usr/bin/env bash
# Both-down recovery, human-only (docs/bootstrap-node.md#both-control-nodes-down).
# Run as root in the Proxmox host shell: bash <file> <full SHA it was fetched at>
set -euo pipefail

sha=${1:-}
repo=https://github.com/faviann/homelab-iac.git
[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo "usage: bash $0 <full SHA this script was fetched at>" >&2; exit 2; }
if [[ $EUID -ne 0 ]] || ! command -v pct >/dev/null; then
  echo "Run this as root in the Proxmox host shell." >&2
  exit 1
fi

hostname_of() {
  local key value
  while read -r key value; do
    if [[ $key == hostname: ]]; then echo "$value"; fi
  done < <(pct config "$1")
}

# pct exec starts with PATH=/sbin:/bin:/usr/sbin:/usr/bin, which misses uv and bw in /usr/local/bin.
root_env=(env HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin)

echo "[1/6] Create the bootstrap node (101)"
if pct status 101 >/dev/null 2>&1; then
  name=$(hostname_of 101)
  echo "101 already exists: hostname $name, $(pct status 101)"
  [[ $name == bootstrap ]] || { echo "Not the bootstrap node; leaving it alone." >&2; exit 1; }
  read -rp "Type 101 to destroy it: " answer
  [[ $answer == 101 ]] || { echo "Left untouched."; exit 1; }
  if [[ $(pct status 101) == "status: running" ]]; then pct stop 101; fi
  pct destroy 101
fi
template=
while read -r volid _; do
  if [[ $volid == *debian-13-standard_* ]]; then template=$volid; fi
done < <(pveam list local)
[[ -n $template ]] || { echo "No debian-13-standard template in local storage." >&2; exit 1; }
# nesting=1: Debian 13's journald fails without it (inventory/group_vars/all/proxmox.yml).
pct create 101 "$template" --hostname bootstrap --unprivileged 1 --features nesting=1 \
  --cores 2 --memory 4096 --swap 512 --rootfs local-zfs:8 \
  --net0 name=eth0,bridge=vmbr1,ip=dhcp
pct start 101

echo "[2/6] Install tools and clone the repository"
# The loop waits for DHCP and DNS after the start; apt fails loudly if they never come.
# shellcheck disable=SC2016  # expanded inside the container
pct exec 101 -- "${root_env[@]}" bash -euo pipefail -c '
  for _ in {1..30}; do getent hosts deb.debian.org >/dev/null && break; sleep 2; done
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y git unzip curl
  curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
  curl -fsSLo /tmp/bw.zip "https://vault.bitwarden.com/download/?app=cli&platform=linux"
  unzip -o /tmp/bw.zip bw -d /usr/local/bin && chmod 755 /usr/local/bin/bw && rm /tmp/bw.zip
  git clone "$1" /root/homelab-iac
  git -C /root/homelab-iac checkout --detach "$2"
' _ "$repo" "$sha"

echo "[3/6] Unlock secrets on 101"
read -rp "Press Enter, then log in at Bitwarden's prompts (email, master password, 2FA). "
# Only Bitwarden prompts for secrets, inside the container; nothing prints them.
# shellcheck disable=SC2016  # expanded inside the container
pct exec 101 -- "${root_env[@]}" bash -c 'BW_SESSION=$(bw login --raw) && export BW_SESSION &&
  umask 077 && mkdir -p /root/.ansible/ssh && cd /root/.ansible &&
  pass=$(bw get notes dotfiles/ansible-vault-pass) && key=$(bw get notes dotfiles/proxmox-lxc-ssh-key) &&
  printf "%s\n" "$pass" > vault-pass && printf "%s\n" "$key" > ssh/proxmox_lxc &&
  ssh-keygen -y -f ssh/proxmox_lxc > ssh/proxmox_lxc.pub; rc=$?; bw lock; exit $rc'

echo "[4/6] Deploy the workstation from 101"
echo "This may restart the workstation (pending reboot after upgrades, or a container config change); if its busy probe reports busy, the run defers and exits 3."
read -rp "Run ./run.sh --limit workstation now? [y/N] " answer
retry="101 stays up. Retry from this shell: pct exec 101 -- ${root_env[*]} bash -c 'cd /root/homelab-iac && ./run.sh --limit workstation'"
[[ $answer == y ]] || { echo "$retry"; exit 0; }
rc=0
pct exec 101 -- "${root_env[@]}" bash -c 'cd /root/homelab-iac && ./run.sh --limit workstation' || rc=$?
echo "./run.sh exited $rc (0 applied, 3 deferred, anything else failed)."
[[ $rc -eq 0 ]] || { echo "$retry"; exit "$rc"; }

echo "[5/6] Destroy the temporary node"
pct stop 101
pct destroy 101

echo "[6/6] Recreate the bootstrap node from the workstation (306); it copies the secrets"
name=$(hostname_of 306)
[[ $name == workstation ]] || { echo "306 is '$name', not workstation; stopping." >&2; exit 1; }
# A throwaway clone at this script's commit; the workstation's own checkouts stay untouched.
# shellcheck disable=SC2016  # expanded by faviann's shell on the workstation
recreate='d=$(mktemp -d) && trap "rm -rf $d" EXIT && cd "$d" && git init -q &&
  git fetch -q --depth 1 '"$repo $sha"' && git checkout -q FETCH_HEAD && ./run.sh --limit bootstrap'
rc=0
pct exec 306 -- su - faviann -c "$recreate" || rc=$?
if [[ $rc -ne 0 ]]; then
  echo "./run.sh exited $rc. Rerun from this shell: pct exec 306 -- su - faviann -c '$recreate'" >&2
  exit "$rc"
fi

echo "Done. Verify the node from this shell:"
echo "  pct exec 101 -- ${root_env[*]} bash -c 'cd /root/homelab-iac && ./vault.sh check && ./inspect.sh connectivity'"
