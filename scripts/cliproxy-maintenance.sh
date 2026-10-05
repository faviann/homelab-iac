#!/usr/bin/env bash
# Human-only CPA/Home maintenance on overmind. See docs/cliproxy-maintenance.md.
#
# Usage: scripts/cliproxy-maintenance.sh stop|remove-bootstrap|remove-home|restart-cpa
#
# Holds the lifecycle lock for the whole run; contention exits 75 before SSH.
set -euo pipefail

case ${1:-} in
  stop|remove-bootstrap|remove-home|restart-cpa) action=$1 ;;
  *) sed -n 4p "$0" >&2; exit 2 ;;
esac

exec 9>>"$HOME/.ansible/homelab-iac-lifecycle.lock"
flock --exclusive --nonblock 9 ||
  { echo 'lifecycle lock held: nothing ran' >&2; exit 75; }

ssh -o BatchMode=yes -o ConnectTimeout=10 -l root \
  -i ~/.ansible/ssh/proxmox_lxc overmind bash -s -- "$action" <<'REMOTE'
set -euo pipefail

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

case $1 in
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
