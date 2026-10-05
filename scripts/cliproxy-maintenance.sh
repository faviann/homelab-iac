#!/usr/bin/env bash
# Human-only CPA/Home maintenance on overmind. See docs/cliproxy-maintenance.md.
#
# Usage: scripts/cliproxy-maintenance.sh start-bootstrap|stop|remove-bootstrap|remove-home|restart-cpa|snapshot <name>|restore <name>|import-legacy <name>|export-current <name>|rollback-original <name>|rollback-current <name>
#
# Holds the lifecycle lock for the whole run; contention exits 75 before SSH.
set -euo pipefail

case ${1:-} in
  start-bootstrap|stop|remove-bootstrap|remove-home|restart-cpa)
    (($# == 1)) || { sed -n 4p "$0" >&2; exit 2; }
    action=$1
    name=
    revision=
    ;;
  snapshot|restore|import-legacy|export-current|rollback-original|rollback-current)
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
legacy=/conf/docker/stacks/cliproxy/appdata
# The finite initial migration uses exactly the resolved Home version.
initial_home_image=eceasy/cli-proxy-api-home:v1.1.0@sha256:14e666f537b26a3fe1cb1a17b458000ff80898edbd7d6cafd83a4d5f7450a49c

# A root-only 0700 parent keeps everything beneath it private.
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

start-bootstrap() {
  local s container
  for container in cliproxy-home cliproxy; do
    s=$(state "$container")
    [[ $s != running ]] || abort "$container must be stopped before bootstrap"
  done
  private_parent "$data"
  private_parent "$home_dir"
  # Without it Home would create an empty database that blocks a later import.
  [[ -s $home_dir/home.db ]] || abort 'imported Home database is missing'
  # No Compose labels, automatic restart, credential input or enrollment helper.
  # cluster.yaml, not Docker networking, supplies the identity in the carrier,
  # so the bootstrap stays off the stack network. An existing bootstrap fails
  # the name check; preserve it rather than removing it to retry.
  docker_ run --detach --pull never --name cliproxy-home-bootstrap --restart no \
    --publish 127.0.0.1:8327:8327 --entrypoint sh \
    --mount "type=bind,src=$home_dir,dst=/CLIProxyAPIHome/data" \
    --mount "type=bind,src=$legacy/config/cluster.yaml,dst=/CLIProxyAPIHome/cluster.yaml,readonly" \
    "$initial_home_image" -c 'umask 077; exec ./CLIProxyAPIHome' >/dev/null
  echo 'bootstrap started; authenticate through the loopback tunnel and accept the imported state before issuing a pending enrollment'
}

import-legacy() {
  local candidate file
  candidate=$backups/$1
  private_parent "$data"
  private_parent "$backups"
  [[ ! -e $home_dir ]] || {
    private_parent "$home_dir"
    [[ -z $(find "$home_dir" -mindepth 1 -maxdepth 1 -print -quit) ]] || abort 'Home import directory is not empty; preserve and abandon the candidate'
  }
  [[ -s $legacy/config/config.yaml && -d $legacy/auth ]] || abort 'standalone source is missing'
  private_parent "$legacy/auth"
  [[ $(stat -c '%u:%g:%a' "$legacy/config/config.yaml") == '0:0:600' ]] || abort 'standalone config must be root:root 0600'
  mkdir -- "$candidate"
  mkdir -- "$candidate/original" "$candidate/bootstrap" "$candidate/bootstrap/auth"
  cp -a -- "$legacy/config/config.yaml" "$candidate/original/config.yaml"
  cp -a -- "$legacy/auth" "$candidate/original/auth"
  # Hashes stay private; rollback-original checks them after the human gap.
  (cd "$candidate/original"; find . -type f -exec sha256sum -- {} + >../SOURCE_SHA256SUMS)
  cp -a -- "$candidate/original/config.yaml" "$candidate/bootstrap/config.yaml"
  shopt -s nullglob
  for file in "$candidate/original/auth/"*.[jJ][sS][oO][nN]; do
    [[ -f $file && ! -L $file && $(stat -c '%u:%g:%a' "$file") == '0:0:600' ]] || abort 'OAuth source must be regular root:root 0600 files'
    cp -a -- "$file" "$candidate/bootstrap/auth/"
  done
  printf 'home_image=%s\nstandalone_revision=%s\noauth_files=%s\n' \
    "$initial_home_image" "$2" "$(find "$candidate/bootstrap/auth" -maxdepth 1 -type f | wc -l)" >"$candidate/import.txt"
  [[ -d $home_dir ]] || mkdir -- "$home_dir"
  docker run --rm --network none --entrypoint sh \
    --mount "type=bind,src=$candidate/bootstrap,dst=/bootstrap" \
    --mount "type=bind,src=$home_dir,dst=/CLIProxyAPIHome/data" "$initial_home_image" \
    -c 'umask 077; exec ./CLIProxyAPIHome -import -config /bootstrap/config.yaml -auth-dir /bootstrap/auth -sqlite-path /CLIProxyAPIHome/data/home.db' \
    >"$candidate/import.log" 2>&1 || abort 'native import failed; retain and abandon the private copy and DB candidate'
  echo "import candidate prepared: $candidate; compare source coverage/status and native counts privately before enrollment; writers remain stopped"
}

export-current() {
  local candidate
  candidate=$backups/$1
  private_parent "$data"
  private_parent "$backups"
  [[ -s $home_dir/home.db ]] || abort 'Home state is missing'
  mkdir -- "$candidate"
  # Export opens/migrates the DB, so keep the whole directories (WAL/SHM and a
  # not-yet-enrolled cache) first. This is evidence, not a matched recovery set.
  cp -a -- "$home_dir" "$candidate/home"
  [[ ! -d $cpa_dir ]] || cp -a -- "$cpa_dir" "$candidate/cpa"
  mkdir -- "$candidate/export"
  docker run --rm --network none --entrypoint sh \
    --mount "type=bind,src=$home_dir,dst=/CLIProxyAPIHome/data" \
    --mount "type=bind,src=$candidate/export,dst=/export" "$initial_home_image" \
    -c 'umask 077; exec ./CLIProxyAPIHome -export -export-dir /export -sqlite-path /CLIProxyAPIHome/data/home.db' \
    >"$candidate/export.log" 2>&1 || abort 'native legacy export failed; retain and abandon the private candidate'
  [[ -s $candidate/export/config.yaml && -d $candidate/export/auths ]] || abort 'legacy export is incomplete'
  echo "current export candidate prepared: $candidate; compare coverage/status and frozen config-provider policy before rollback-current; writers remain stopped"
}

# Home state and its bind mounts stay in place; only the standalone auth tree
# is replaced. Deploying the original revision re-renders the frozen config.
rollback() {
  local candidate source attempt
  candidate=$backups/$2
  private_parent "$data"
  private_parent "$backups"
  private_parent "$candidate"
  if [[ $1 == original ]]; then
    source=$candidate/original/auth
    (cd "$candidate/original"; sha256sum --check ../SOURCE_SHA256SUMS >../source-verify.log 2>&1) || abort 'frozen source checksums failed'
  else
    source=$candidate/export/auths
  fi
  [[ -d $source ]] || abort 'selected auth tree is missing'
  attempt=$(mktemp -d "$backups/rollback-$1-$2-XXXXXX")
  cp -a -- "$source" "$attempt/auth"
  # Restore a complete tree, never overlay stale credentials or stale filenames.
  # cp -a preserves root-owned source/native-export files; protect the tree's
  # root when it moves back into shared standalone storage.
  chmod 0700 -- "$attempt/auth"
  [[ ! -e $legacy/auth ]] || mv -- "$legacy/auth" "$attempt/replaced-auth"
  mv -- "$attempt/auth" "$legacy/auth"
  remove cliproxy-home-bootstrap
  remove cliproxy-home
  echo "standalone auth restored; evidence: $attempt; deploy the recorded original revision with ./run.sh, then verify legacy clients/providers"
}

rollback-original() { rollback original "$1"; }
rollback-current() { rollback current "$1"; }

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
  mv -- "$stage/home" "$home_dir"
  mv -- "$stage/cpa" "$cpa_dir"
  echo 'matched state restored; keep writers stopped, use recorded pair pins and reapply later revocations before admitting clients'
}

case $1 in
  start-bootstrap)
    start-bootstrap
    ;;
  snapshot|restore|import-legacy|export-current|rollback-original|rollback-current)
    stop_writers
    "$1" "$2" "$3"
    ;;
  stop)
    stop_writers
    ;;
  remove-bootstrap)
    remove cliproxy-home-bootstrap
    ;;
  remove-home)
    stop_writers
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
