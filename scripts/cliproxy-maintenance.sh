#!/usr/bin/env bash
# Human-only CPA/Home maintenance on overmind. See docs/cliproxy-maintenance.md.
#
# Usage: scripts/cliproxy-maintenance.sh stop|remove-bootstrap|remove-home|restart-cpa|snapshot <name>|restore <name>
#
# Holds the lifecycle lock for the whole run; contention exits 75 before SSH.
set -euo pipefail

case ${1:-} in
  stop|remove-bootstrap|remove-home|restart-cpa)
    (($# == 1)) || { sed -n 4p "$0" >&2; exit 2; }
    action=$1
    name=
    revision=
    ;;
  snapshot|restore)
    (($# == 2)) && [[ $2 =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$ ]] ||
      { sed -n 4p "$0" >&2; exit 2; }
    action=$1
    name=$2
    revision=$(git -C "$(dirname "$0")/.." rev-parse HEAD)
    ;;
  *) sed -n 4p "$0" >&2; exit 2 ;;
esac

exec 9>>"$HOME/.ansible/homelab-iac-lifecycle.lock"
flock --exclusive --nonblock 9 ||
  { echo 'lifecycle lock held: nothing ran' >&2; exit 75; }

ssh -o BatchMode=yes -o ConnectTimeout=10 -l root \
  -i ~/.ansible/ssh/proxmox_lxc overmind bash -s -- "$action" "$name" "$revision" <<'REMOTE'
set -euo pipefail
umask 077

abort() { echo "maintenance aborted: $*" >&2; exit 1; }
docker_() { timeout --kill-after=5s 45s docker "$@"; }

# A failed listing aborts here; it never reads as "absent".
names=$(docker_ container ls --all --format '{{.Names}}')

# Prints running, stopped or absent. Any other state aborts. Always call it as
# an assignment so set -e catches the abort.
state() {
  grep -qxF -- "$1" <<<"$names" || { echo absent; return; }
  local status
  status=$(docker_ container inspect --format '{{.State.Status}}' "$1")
  case $status in
    running) echo running ;;
    exited|created) echo stopped ;;
    *) abort "$1 is $status" ;;
  esac
}

# Stops one container if it runs, then confirms it actually exited.
stop() {
  local s
  s=$(state "$1")
  [[ $s != running ]] || docker_ container stop --time 30 "$1" >/dev/null
  s=$(state "$1")
  [[ $s != running ]] || abort "$1 is still running"
}

# Home holds subscriptions that can keep CPA from finishing SIGTERM, so every
# Home instance stops first. A failure leaves CPA untouched.
stop_writers() {
  local home bootstrap
  home=$(state cliproxy-home)
  bootstrap=$(state cliproxy-home-bootstrap)
  [[ "$home $bootstrap" != 'running running' ]] || abort 'two Home instances are running'
  stop cliproxy-home
  stop cliproxy-home-bootstrap
  stop cliproxy
}

# Detaches the stopped bootstrap from the stack network without removing it.
detach_bootstrap() {
  local s networks
  s=$(state cliproxy-home-bootstrap)
  [[ $s != absent ]] || return 0
  [[ $s == stopped ]] || abort 'cliproxy-home-bootstrap is running'
  networks=$(docker_ container inspect \
    --format '{{range $n, $_ := .NetworkSettings.Networks}}{{$n}} {{end}}' \
    cliproxy-home-bootstrap)
  [[ " $networks " != *' cliproxy_default '* ]] ||
    docker_ network disconnect cliproxy_default cliproxy-home-bootstrap
}

remove() {
  local s
  s=$(state "$1")
  [[ $s == absent ]] || docker_ container rm "$1" >/dev/null
}

# These fixed runtime paths deliberately stay outside the synced stack tree.
data=/data/overmind/cliproxy
backups=/backups/overmind/cliproxy
home_dir=$data/home
cpa_dir=$data/cpa

private_tree() {
  chown -R root:root -- "$1"
  find "$1" -type d -exec chmod 0700 {} +
  find "$1" -type f -exec chmod 0600 {} +
}

private_parent() {
  [[ -d $1 && $(stat -c '%u:%g:%a' "$1") == '0:0:700' ]] ||
    abort "private parent must be root:root 0700: $1"
}

pinned_image() {
  local image
  image=$(docker_ container inspect --format '{{.Config.Image}}' "$1")
  [[ $image =~ @sha256:[a-f0-9]{64}$ ]] || abort "$1 image is not digest-pinned"
  echo "$image"
}

snapshot() {
  local recovery home_image cpa_image
  recovery=$backups/$1
  private_parent "$data"
  private_parent "$backups"
  [[ -d $home_dir && -s $home_dir/home.db && -d $cpa_dir ]] || abort 'runtime state is missing'
  for file in client-crt.pem client-key.pem home-ca-crt.pem; do
    [[ -s $cpa_dir/$file ]] || abort 'enrolled CPA cache is incomplete'
  done
  home_image=$(pinned_image cliproxy-home)
  cpa_image=$(pinned_image cliproxy)
  mkdir -- "$recovery" # Never reuse a successful or incomplete candidate.
  private_tree "$home_dir"
  private_tree "$cpa_dir"
  # Native export opens/migrates SQLite: it needs the whole writable directory,
  # including WAL/SHM. Offline tools have no time cap and no network access.
  docker run --rm --network none --entrypoint sh \
    --mount "type=bind,src=$home_dir,dst=/CLIProxyAPIHome/data" \
    --mount "type=bind,src=$recovery,dst=/recovery" "$home_image" \
    -c 'umask 077; exec ./CLIProxyAPIHome -db-export /recovery/home.zip -sqlite-path /CLIProxyAPIHome/data/home.db' \
    >"$recovery/snapshot.log" 2>&1 || abort 'native snapshot failed; retain the private candidate and log'
  cp -a -- "$cpa_dir" "$recovery/cpa"
  printf 'home_image=%s\ncpa_image=%s\nrepository_revision=%s\n' \
    "$home_image" "$cpa_image" "$2" >"$recovery/images.txt"
  (cd "$recovery"; sha256sum home.zip cpa/client-crt.pem cpa/client-key.pem cpa/home-ca-crt.pem >SHA256SUMS)
  private_tree "$recovery"
  echo "snapshot candidate prepared: $recovery; verify isolated restore before counting it as successful"
}

restore() {
  local recovery stage home_image
  recovery=$backups/$1
  private_parent "$data"
  private_parent "$backups"
  private_parent "$recovery"
  [[ -d $recovery/cpa && -f $recovery/images.txt && -f $recovery/SHA256SUMS ]] || abort 'recovery set is incomplete'
  home_image=$(sed -n 's/^home_image=//p' "$recovery/images.txt")
  [[ $home_image =~ @sha256:[a-f0-9]{64}$ ]] || abort 'recorded Home image is not digest-pinned'
  (cd "$recovery"; sha256sum --check SHA256SUMS >verify.log 2>&1) || abort 'recovery artifact checksums failed'
  stage=$(mktemp -d "$data/restore-$1-XXXXXX") # Retained sets can be restored repeatedly.
  mkdir -- "$stage/home"
  docker run --rm --network none --entrypoint sh \
    --mount "type=bind,src=$stage/home,dst=/CLIProxyAPIHome/data" \
    --mount "type=bind,src=$recovery,dst=/recovery,readonly" "$home_image" \
    -c 'umask 077; exec ./CLIProxyAPIHome -db-import /recovery/home.zip -sqlite-path /CLIProxyAPIHome/data/home.db' \
    >"$stage/restore.log" 2>&1 || abort 'native restore failed; retain the private target and log'
  cp -a -- "$recovery/cpa" "$stage/cpa"
  # Preserve the entire failed DB/WAL/cache before replacing either runtime path.
  [[ ! -e $home_dir ]] || mv -- "$home_dir" "$stage/failed-home"
  [[ ! -e $cpa_dir ]] || mv -- "$cpa_dir" "$stage/failed-cpa"
  private_tree "$stage"
  mv -- "$stage/home" "$home_dir"
  mv -- "$stage/cpa" "$cpa_dir"
  echo 'matched state restored; keep writers stopped, use recorded pair pins and reapply later revocations before admitting clients'
}

case $1 in
  snapshot|restore)
    stop_writers
    detach_bootstrap
    "$1" "$2" "$3"
    ;;
  stop)
    stop_writers
    detach_bootstrap
    ;;
  remove-bootstrap)
    detach_bootstrap
    remove cliproxy-home-bootstrap
    ;;
  remove-home)
    stop_writers
    detach_bootstrap
    remove cliproxy-home-bootstrap
    remove cliproxy-home
    ;;
  restart-cpa)
    stop cliproxy
    docker_ container start cliproxy >/dev/null
    s=$(state cliproxy)
    [[ $s == running ]] || abort 'cliproxy did not restart'
    ;;
esac
REMOTE
