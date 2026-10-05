# Human maintenance of CPA and Home

This is the procedure behind the human-only
[command-policy exception](command-policy.md#cpahome-maintenance-on-overmind).
It covers the CPA/Home migration on `overmind`, protected backup and restore,
assisted pair updates, and emergency termination of revoked CPA sessions.
Ordinary deployment stays on `./run.sh`. Agents do not run this against
managed hosts.

## Names

| Name | What it is |
| --- | --- |
| `cliproxy` | CPA, Compose service and container in project `cliproxy` |
| `cliproxy-home` | Permanent Home, same project |
| `cliproxy-home-bootstrap` | Temporary plain Home container used once for enrollment, attached only to `cliproxy_default` |

CPA always exists. Before migration, both Home containers may be absent. CPA
and Home both write state, so each of them counts as a **writer**.

Native one-shot tools use the images pinned for the deployed pair. The CPA pin
is in [`compose.yaml`](../stacks/overmind/cliproxy/compose.yaml). The Home pin
is in the [migration plan](https://github.com/faviann/homelab-iac/issues/476#issuecomment-5985413171)
until Home joins that file. After an assisted update, use the pins recorded
with the recovery set you restore from, and use the old Home image for the
pre-update export.

Private maintenance state lives under `/data/overmind/cliproxy/home`,
`/data/overmind/cliproxy/cpa`, and a unique subdirectory of
`/backups/overmind/cliproxy`. Require root ownership, 0700 directories and
0600 files before you use them. Never copy a live `home.db` on its own, never
overwrite a populated restore target, and keep the original standalone state
until initial acceptance passes.

## Before you start

Approve a maintenance window. Freeze deployments from **every** control node,
Home administration, provider and policy changes, and consumer key changes.
Keep the freeze until acceptance or recovery is complete. The script's lock
only covers this workstation, and it does nothing about Home's administrative
API.

In-flight requests may be cut off. Shutdown is not a graceful drain.

## Run an action

Run from the repository root on the workstation:

```bash
scripts/cliproxy-maintenance.sh <action>
```

The script takes the exclusive lifecycle lock before SSH and holds it until it
exits. If a live operation holds the lock, it prints
`lifecycle lock held: nothing ran`, exits 75, and does not contact `overmind`.
Because the lock is taken directly, a `./run.sh` that collides with it cannot
name this holder.

| Action | Effect |
| --- | --- |
| `stop` | Stops both Home containers, then CPA, and confirms each one exited. Then detaches a stopped bootstrap from `cliproxy_default`. Use it before offline state work. |
| `remove-bootstrap` | Detaches and removes the stopped bootstrap. The running pair is left alone. Use it only after initial acceptance and a verified matched recovery baseline. |
| `remove-home` | Standalone rollback. Runs `stop`, then removes both Home containers, which ordinary Compose startup would leave as orphans. CPA stays stopped until you deploy the original revision. Preserve the failed state first; removing the containers does not delete bind mounts. |
| `restart-cpa` | Emergency. Stops and restarts CPA only. Home keeps running. |

Each action aborts without further changes when:

- Docker can't list or inspect a container. A failed inspection never counts
  as "absent".
- A container is paused, restarting, or dead.
- Both Home containers are running.
- A writer is still running after it was stopped.
- The bootstrap is running when it should be detached or removed.

Stops give Docker 30 seconds before SIGKILL, so active requests can be cut off
mid-stream. Every Docker call is capped at 45 seconds.

Why Home stops first: Home's subscriptions can keep CPA from finishing
SIGTERM.

Why the bootstrap is kept until acceptance: normal deployment prunes unused
images. The stopped bootstrap keeps the pulled Home image in use. It is
detached so its network alias cannot compete with the permanent Home. If the
daemon refuses to detach a stopped container, the run aborts. Don't restart a
writer and don't add `--force` to get past it.

Never use Compose `down`, `--remove-orphans`, project-wide or pattern-based
removal, or volume or network deletion.

### Offline state work

Later issues add each snapshot, import, export or restore step as a new
action of this script. Each one starts with the `stop` sequence, so it runs
under the same lock and only after every writer has exited. The SSH session
has no overall time limit, so a long import is not killed partway through.
Run one-shot import and export with `--network none` and no published ports.
A temporary bootstrap publishes management port 8327 on loopback only, with
no routing labels.

### Emergency CPA restart

First revoke the consumer key through Home administration. Revoking rejects
new requests but does not end an open stream or a retained Responses WebSocket
session. `restart-cpa` interrupts **every** CPA session and may reach the
forced-termination deadline. A running container is not proof that CPA works;
run the secret-safe acceptance probes afterwards.

## Deploy, accept or recover

Deploy through the facade. Each call takes the lock again:

```bash
./run.sh configure --limit overmind --stack cliproxy
./run.sh configure --limit portal --stack traefik3
```

`--stack` narrows stack sync. Host configuration can still upgrade packages,
reconcile Docker, and reboot. A clean recap or `up -d` is not acceptance.
Check the recorded pins, private modes, every writer, and the readiness,
client/provider, panel and recovery gates.

If SSH drops mid-run, the remote result is unknown. Keep the freeze, find out
the actual remote state, and choose the recovery branch before you retry or
deploy.

Abort and preserve evidence on any of these:

- an unusable recovery set
- a partial or skipped import
- unexpected state
- a writer that is still running
- failed acceptance

Then follow the recorded recovery branch. Don't merge into or overwrite
targets, don't reuse a consumed enrollment blindly, and don't fall back to
stale provider tokens.

Keep secrets out of terminals and evidence. That means no environment dumps,
no credential-file contents, no key, JWT or password in command arguments, no
callback URLs, and no secret request or log payloads. Use protected files or
prompts and native state. Logs stay private. `./vault.sh edit` is human-only
and takes no lifecycle lock.

## Rehearsal

```bash
./validate.sh tests tests/regression/test_cliproxy_maintenance.py
```

This runs the script with a real `flock` and local SSH/Docker stand-ins. It
checks the script's ordering, scope and abort decisions. It does not check
Docker's shutdown or network behavior, pinned-image termination, DNS/mTLS,
enrollment, snapshot and restore, or real provider and client acceptance.
Those remain human cutover gates.
