# Human maintenance of CPA and Home

This procedure is the finite human-only exception in
[command policy](command-policy.md#cpahome-maintenance-on-overmind). It implements
[#478](https://github.com/faviann/homelab-iac/issues/478), using the
[resolved migration plan](https://github.com/faviann/homelab-iac/issues/476#issuecomment-5985413171).
It authorizes no agent execution against managed hosts. Ordinary deployment
continues through `./run.sh`.

## Preconditions and authority

A human approves the maintenance window and freezes competing deployments on
**all control nodes**, Home administration, provider/policy changes, and consumer
key changes. Keep that freeze through raw maintenance, deployment, acceptance,
and recovery. The workstation lock does not coordinate other control nodes or
Home's administrative API. Cancel active requests as necessary; there is no
promise of a graceful drain.

Use the normal workstation home directory and existing controller identity.
Do not change `$HOME` to evade a held lock. On `overmind`, the deployed project
is `/conf/docker/stacks/cliproxy`, project `cliproxy`. Its exact container/service
names are `cliproxy` and `cliproxy-home`; the plain temporary Home is
`cliproxy-home-bootstrap`, attached only to `cliproxy_default`. Before migration,
Home and bootstrap may be absent; CPA must exist. Unexpected names, project or
service labels, two running Home owners, paused/restarting/dead state, unavailable
Docker, or failed inspection are aborts, not evidence that a writer is absent.
Do not use Compose `down`, `--remove-orphans`, project-wide removal, name patterns,
volume deletion, or network deletion.

Native maintenance tools use the recorded pair, initially:

| Component | Pin |
| --- | --- |
| CPA | `eceasy/cli-proxy-api:v7.3.8@sha256:6c2c8a7904799bd29a3f7f92a598555d8321b6a5682000b87af4495c5704fa72` |
| Home | `eceasy/cli-proxy-api-home:v1.1.0@sha256:14e666f537b26a3fe1cb1a17b458000ff80898edbd7d6cafd83a4d5f7450a49c` |

After an assisted pair update, use the pins recorded with the selected recovery
set. Use the old pinned Home binary for the pre-update export/snapshot. The
private paths reserved by the plan are `/data/overmind/cliproxy/home`,
`/data/overmind/cliproxy/cpa`, and unique subdirectories under
`/backups/overmind/cliproxy`. Their declarations and snapshot/import/restore
commands arrive in later subissues; they are **not provisioned by this change**.
Require root ownership, directories 0700 and files 0600 before using them.
Never copy a live `home.db` alone, overwrite a populated restoration target,
or allow concurrent state writers. Preserve the original standalone source
through initial acceptance.

## Stop writers and detach bootstrap

Run this block from the repository root on the workstation. It takes the existing
exclusive nonblocking lock before SSH; contention exits 75 without contacting
`overmind`. A directly acquired lock has no holder record, so competing supported
commands may not identify this holder. The outer SSH limit is three minutes;
each Docker observation has a ten-second limit plus five seconds before forced
client termination. Each stop grants Docker thirty seconds before container
SIGKILL and bounds its client to forty seconds plus five. A timeout or nonzero
result aborts. Client timeout alone never proves a container exited.

Home subscriptions can keep CPA from finishing SIGTERM: stop permanent or
temporary Home **before CPA**, inspect actual stopped state after each stop,
and recheck every writer before offline work. Stop failure or any remaining
writer forbids copying, importing, exporting, restoring, starting another owner,
and deployment. Inspecting only state, labels and network names avoids container
environment disclosure.

<!-- rehearsal: maintenance -->
```bash
(
  flock --exclusive --nonblock 9 ||
    { echo 'lifecycle lock held: nothing ran' >&2; exit 75; }
  timeout --signal=TERM --kill-after=5s 180s \
    ssh -o BatchMode=yes -o ConnectTimeout=10 -l root \
      -i ~/.ansible/ssh/proxmox_lxc overmind 'bash -se' <<'REMOTE'
set -euo pipefail
umask 077
cd /conf/docker/stacks/cliproxy

docker_bounded() {
  timeout --signal=TERM --kill-after=5s 10s docker "$@"
}
abort() { echo "maintenance aborted: $*" >&2; exit 1; }
# No environment/config dump. Failed inventory is not an absent container.
docker_bounded info --format '{{.ServerVersion}}' >/dev/null
containers="$(docker_bounded container ls --all --format '{{.Names}}')"
container_state() {
  local name="$1" record project service status running
  case "$name" in
    cliproxy|cliproxy-home|cliproxy-home-bootstrap) ;;
    *) abort 'unapproved container' ;;
  esac
  if [[ $'\n'"$containers"$'\n' != *$'\n'"$name"$'\n'* ]]; then
    [[ "$name" != cliproxy ]] || abort 'CPA is absent'
    echo absent
    return
  fi
  record="$(docker_bounded container inspect --format \
    '{{with index .Config.Labels "com.docker.compose.project"}}{{.}}{{end}}|{{with index .Config.Labels "com.docker.compose.service"}}{{.}}{{end}}|{{.State.Status}}|{{.State.Running}}' "$name")"
  IFS='|' read -r project service status running <<<"$record"
  if [[ "$name" == cliproxy-home-bootstrap ]]; then
    [[ -z "$project" && -z "$service" ]] || abort 'bootstrap has unexpected Compose labels'
  else
    [[ "$project" == cliproxy && "$service" == "$name" ]] || abort "unexpected owner of $name"
  fi
  case "$status|$running" in
    'running|true') echo running ;;
    'exited|false'|'created|false') echo stopped ;;
    *) abort "unexpected state of $name" ;;
  esac
}
require_stopped() {
  local state
  state="$(container_state "$1")"
  [[ "$state" == stopped || "$state" == absent ]] || abort "$1 remains a writer"
}
stop_writer() {
  local state
  state="$(container_state "$1")"
  if [[ "$state" == running ]]; then
    timeout --signal=TERM --kill-after=5s 40s docker container stop --time 30 "$1" >/dev/null
  fi
  require_stopped "$1"
}
stop_all_writers() {
  local home_state bootstrap_state
  home_state="$(container_state cliproxy-home)"
  bootstrap_state="$(container_state cliproxy-home-bootstrap)"
  [[ "$home_state|$bootstrap_state" != 'running|running' ]] || abort 'two running Home owners'
  # Validate CPA ownership/state before the first mutation.
  container_state cliproxy >/dev/null
  stop_writer cliproxy-home
  stop_writer cliproxy-home-bootstrap
  stop_writer cliproxy
  require_stopped cliproxy-home
  require_stopped cliproxy-home-bootstrap
  require_stopped cliproxy
}
detach_bootstrap() {
  local state networks
  state="$(container_state cliproxy-home-bootstrap)"
  [[ "$state" != absent ]] || return 0
  require_stopped cliproxy-home-bootstrap
  networks="$(docker_bounded container inspect --format \
    '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}' cliproxy-home-bootstrap)"
  case "$networks" in
    '') return 0 ;;
    cliproxy_default) ;;
    *) abort 'unexpected bootstrap network attachment' ;;
  esac
  docker_bounded network disconnect cliproxy_default cliproxy-home-bootstrap
  networks="$(docker_bounded container inspect --format \
    '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}' cliproxy-home-bootstrap)"
  [[ -z "$networks" ]] || abort 'bootstrap remains attached'
}
# Replace only these two action lines for the named alternatives below.
stop_all_writers
detach_bootstrap
REMOTE
) 9>>~/.ansible/homelab-iac-lifecycle.lock
```

The block detaches only the stopped bootstrap from `cliproxy_default`. The
[Moby v28 stopped-container path](https://github.com/moby/moby/blob/v28.0.0/daemon/container_operations.go#L958-L991)
removes this stored attachment without starting the container. This source
evidence does not verify the target daemon: if it rejects detach, abort and
escalate without restarting a writer or adding `--force`. Retain
that stopped container until initial acceptance: normal deployment prunes unused
images, and the stopped container keeps the pulled Home image in use. Never start
the permanent Home while a temporary Home writer or its competing alias remains.
For offline state operations, insert only the reviewed pinned native/private
operation after the successful writer checks, before `REMOTE`. Later runbooks
supply those commands. Native one-shot import/export runs unpublished with
`--network none`; temporary bootstrap publishes management port 8327 on loopback
only, with no routing labels. No alternate owners or public bootstrap binding.

## Named alternatives within the same locked block

Replace the two action lines above, leaving all preflight/lock/bounds intact.
These are finite alternatives, not a new lifecycle command.

After initial acceptance and the verified matched recovery baseline, remove
only the stopped bootstrap, leaving the permanent pair running. Do not force-remove
a writer:

<!-- rehearsal: bootstrap-remove -->
```bash
require_stopped cliproxy-home-bootstrap
detach_bootstrap
if [[ "$(container_state cliproxy-home-bootstrap)" != absent ]]; then
  docker_bounded container rm cliproxy-home-bootstrap >/dev/null
fi
```

For the recorded standalone rollback branch, stop all writers and remove only
Home containers that ordinary Compose startup would leave as orphans. Preserve
the failed state/recovery data before removal; removal does not delete bind mounts.
CPA stays stopped until supported deployment of the reviewed original revision.

<!-- rehearsal: home-remove -->
```bash
stop_all_writers
detach_bootstrap
for name in cliproxy-home-bootstrap cliproxy-home; do
  require_stopped "$name"
  if [[ "$(container_state "$name")" != absent ]]; then
    docker_bounded container rm "$name" >/dev/null
  fi
done
```

For an active compromise, first revoke the consumer key through native Home
administration. Revocation rejects new requests but does not end an existing
stream or retained Responses WebSocket session. Explicitly accept interruption
of **all CPA sessions**. This CPA-only operation may reach Docker's forced
termination deadline; Home remains running. Verify CPA exited before starting it
again, then perform the secret-safe functional acceptance probes. A running
container is not functional readiness.

<!-- rehearsal: emergency -->
```bash
# Validate every known owner, including the optional temporary Home.
home_state="$(container_state cliproxy-home)"
bootstrap_state="$(container_state cliproxy-home-bootstrap)"
[[ "$home_state|$bootstrap_state" != 'running|running' ]] || abort 'two running Home owners'
stop_writer cliproxy
docker_bounded container start cliproxy >/dev/null
[[ "$(container_state cliproxy)" == running ]] || abort 'CPA did not restart'
```

## Unlock, deploy, accept or recover

The subshell releases the raw lock on exit, including aborts. An SSH/client
timeout leaves remote completion uncertain: keep the operator freeze, establish
the actual remote state, and choose recovery before any retry or deployment.
**Release it before
every supported deployment invocation**; never nest `./run.sh` under that lock.
For the reviewed permanent pair and, once prepared, its administration route:

```bash
./run.sh configure --limit overmind --stack cliproxy
./run.sh configure --limit portal --stack traefik3
```

Each call reacquires the existing lock. The unlock gap admits another deployment
from this workstation; the operator freeze must cover that gap and both calls.
`--stack` narrows stack sync/start, but host configuration can still upgrade
packages, reconcile Docker, and reboot. Do not interpret `up -d` or a successful
recap as acceptance. Check the recorded pins, private modes, every writer/alias,
and the applicable readiness, client/provider, panel and recovery gates.

No environment dumps, credential-file contents, key/JWT/password argv values,
callback URLs or secret request/log payloads may enter terminal transcripts or
published evidence. Use operator-controlled protected files/prompts and native
state; logs/artifacts stay private. `./vault.sh edit` is human-only and takes no
lifecycle lock. An unusable recovery set, partial/skipped import, unexpected
state, remaining writer or failed acceptance is an abort. Preserve evidence and
choose the recorded recovery branch; do not merge/overwrite targets, reuse a
consumed enrollment blindly, or fall back to stale provider tokens.

## Synthetic rehearsal and later acceptance

Run `./validate.sh tests tests/regression/test_cliproxy_maintenance.py` to execute
the exact documented maintenance block and named alternatives with a real local
`flock`, a temporary home, and local SSH/Docker stand-ins. No managed host,
production credential, real Docker daemon, or provider is contacted. The stand-in
records finite operations and simulated container states, including failures;
this verifies procedure decisions, not Docker's implementation or CPA's shutdown
behavior. Full handoff is `./validate.sh` with no arguments.

Rehearsal results are recorded with this PR: contention exits 75 before SSH;
Home-first stops use a finite deadline and require exited observations; absent
optional containers are distinguished from Docker/inspection failure; surviving
writers prevent later actions; bootstrap detach/removal stays named; emergency
restart stops only CPA before restart. Synthetic markers replace all credentials.

Real pinned-image termination, Docker DNS/mTLS, bootstrap/enrollment, matched
snapshot/restore, functional protocols/panel, and real provider/client acceptance
remain later implementation and human cutover gates. This rehearsal does not
satisfy them or authorize production execution.
