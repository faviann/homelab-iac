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

# Only Bitwarden prompts for secrets, inside the container.
unlock() {
  read -rp "Press Enter, then log in at Bitwarden's prompts (email, master password, 2FA). "
  # shellcheck disable=SC2016  # expanded inside the container
  pct exec "$1" -- env HOME=/root bash -c 'BW_SESSION=$(bw login --raw) && export BW_SESSION &&
    chezmoi init --apply https://github.com/faviann/dotfiles.git; rc=$?; bw lock; exit $rc'
}

echo "[1/7] Create the bootstrap node (101)"
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
  --net0 name=eth0,bridge=vmbr1,ip=dhcp,ip6=auto
pct start 101

echo "[2/7] Install tools and clone the repository"
# The loop waits for DHCP and DNS after the start; apt fails loudly if they never come.
# shellcheck disable=SC2016  # expanded inside the container
pct exec 101 -- env HOME=/root bash -euo pipefail -c '
  for _ in {1..30}; do getent hosts deb.debian.org >/dev/null && break; sleep 2; done
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y git unzip curl
  curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
  sh -c "$(curl -fsLS get.chezmoi.io)" -- -b /usr/local/bin
  curl -fsSLo /tmp/bw.zip "https://vault.bitwarden.com/download/?app=cli&platform=linux"
  unzip -o /tmp/bw.zip bw -d /usr/local/bin && chmod 755 /usr/local/bin/bw && rm /tmp/bw.zip
  git clone "$1" /root/homelab-iac
  git -C /root/homelab-iac checkout --detach "$2"
' _ "$repo" "$sha"

echo "[3/7] Unlock secrets on 101"
unlock 101

echo "[4/7] Deploy the workstation from 101"
echo "This restarts the workstation unless its busy probe reports busy; then the run defers and exits 3."
read -rp "Run ./run.sh --limit workstation now? [y/N] " answer
[[ $answer == y ]] || { echo "Stopped. 101 stays up: pct enter 101"; exit 0; }
rc=0
pct exec 101 -- env HOME=/root bash -c 'cd /root/homelab-iac && ./run.sh --limit workstation' || rc=$?
echo "./run.sh exited $rc (0 applied, 3 deferred, anything else failed)."

echo "[5/7] Destroy the temporary node"
read -rp "Check the workstation. Once it is healthy, type 101 to destroy this node: " answer
[[ $answer == 101 ]] || { echo "101 left running; retry the deploy from it: pct enter 101"; exit 0; }
if [[ $(pct status 101) == "status: running" ]]; then pct stop 101; fi
pct destroy 101

echo "[6/7] Recreate the bootstrap node from the workstation (306)"
name=$(hostname_of 306)
[[ $name == workstation ]] || { echo "306 is '$name', not workstation; stopping." >&2; exit 1; }
# A throwaway clone at this script's commit; the workstation's own checkouts stay untouched.
# shellcheck disable=SC2016  # expanded by faviann's shell on the workstation
recreate='d=$(mktemp -d) && trap "rm -rf $d" EXIT && cd "$d" && git init -q &&
  git fetch -q --depth 1 '"$repo $sha"' && git checkout -q FETCH_HEAD && ./run.sh --limit bootstrap'
read -rp "Run ./run.sh --limit bootstrap on the workstation now? [y/N] " answer
[[ $answer == y ]] || { echo "Run it later from this shell: pct exec 306 -- su - faviann -c '$recreate'"; exit 0; }
rc=0
pct exec 306 -- su - faviann -c "$recreate" || rc=$?
if [[ $rc -ne 0 ]]; then
  echo "./run.sh exited $rc. Rerun from this shell: pct exec 306 -- su - faviann -c '$recreate'" >&2
  exit "$rc"
fi

echo "[7/7] Unlock secrets on the recreated node"
unlock 101

echo "Done. Verify the node from this shell:"
echo "  pct exec 101 -- env HOME=/root bash -c 'cd /root/homelab-iac && ./vault.sh check && ./inspect.sh connectivity'"
