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
scripts/cliproxy-maintenance.sh <action> [recovery-name]
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
| `snapshot <name>` | Stops all writers, exports the full Home database with the deployed pinned image, and copies its enrolled CPA cache into a new private recovery candidate. Leaves writers stopped. |
| `restore <name>` | Stops all writers, checks the candidate's artifact hashes, restores with its recorded Home image into a new empty directory, preserves failed state and replaces the runtime database/cache together. Leaves writers stopped. |

Actions abort without further changes on failures in the checks they perform:

- Docker can't list or inspect a container. A failed inspection never counts
  as "absent".
- A container is paused, restarting, or dead.
- Both Home containers are running (`stop`, `remove-home`, `snapshot` and `restore`).
- A writer is still running after it was stopped.
- The bootstrap is running when it should be detached or removed.

Stops give Docker 30 seconds before SIGKILL, so active requests can be cut off
mid-stream. Container inspection, stop, detach, removal and restart calls are
capped at 45 seconds. Offline native export and restore have no time cap.

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

Later issues add credential import/export and bootstrap as named actions.
Snapshot and restore start with the `stop` sequence, so they run
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
The [pinned-pair gate](#pinned-pair-gate) covers native snapshot and restore.

## Matched recovery and assisted updates

Home owns runtime configuration, provider credentials and refresh state,
consumer keys and revocations, accounting and cluster trust. Ansible owns
topology, pinned images, private directory declarations and startup inputs.
Home state and the enrolled CPA certificate cache live in root-only 0700
directories under `/data/overmind/cliproxy/{home,cpa}`. Recovery sets live under
`/backups/overmind/cliproxy`. Keep these out of synced `appdata`,
`x-prereq-dirs` and `x-managed-files`, which can reset parent modes to 0755.
The legacy auth directory stays protected until standalone rollback acceptance.
No timer backs up Home. The Postgres backup does not cover it.

The initial compatible pair is CPA v7.3.8 (source `c93978c4ea2e908255a2a06c37599fda3651554a`)
and Home v1.1.0 (source `c098d84d36f57b765e1545dcb53cb6717a673654`).

### Snapshot

Take a snapshot after CPA enrollment, after administrative key, account or
policy changes, and before every image or schema update:

```bash
scripts/cliproxy-maintenance.sh snapshot baseline-20261005
```

This creates a new candidate at `/backups/overmind/cliproxy/<name>`: `home.zip`,
the matching `cpa/` cache, `images.txt` (deployed digest pins and repository
revision), `SHA256SUMS` and the native export log. The script refuses an existing
name, and it refuses to run unless both parents are root:root 0700. It writes
under umask 077.

Home export opens SQLite and runs its schema migration. Export with the **old
deployed Home pin** before an upgrade, from the whole database directory
including WAL/SHM. Never copy a live `home.db`. In this pin, native
[`-db-export`](https://github.com/router-for-me/CLIProxyAPIHome/blob/c098d84d36f57b765e1545dcb53cb6717a673654/cmd/home/main.go)
writes a full snapshot: config, provider state, key metadata, accounting and
CA/private keys. Legacy `-export` writes only exchange config and auth and is
not a recovery snapshot. Snapshot ZIPs are **plaintext secrets**. Never
commit, publish, print or inspect their payloads.

### Retention

A candidate counts as successful only after a restore rehearsal with its
recorded pair and cache on an isolated target with no provider or production
egress. A copied identity must never reach production Home or refresh real
accounts. Keep the current and previous successful sets. Failed or incomplete
candidates never advance retention. Record acceptance privately as names,
revisions, counts and outcomes. A human retires older sets. Nothing prunes
them automatically.

### Restore

Keep the maintenance freeze and pick a verified set:

```bash
scripts/cliproxy-maintenance.sh restore baseline-20261005
```

The script verifies the set's checksums. It imports with the recorded Home
image into a new empty `/data/overmind/cliproxy/restore-<name>-<attempt>/home`,
moves the current Home state (with WAL/SHM) and CPA cache into that attempt's
`failed-home` and `failed-cpa`, then installs the restored pair. Writers stay
stopped. Native restore keeps business state but may skip expired or
runtime-only records. It is not a byte-for-byte copy.

Before clients return, deploy the recorded pair pins and reapply every
revocation made after the snapshot, through Home administration while CPA and
clients are still blocked. Then deploy through `./run.sh` and run functional
acceptance. Judge CPA by its connected identity and an authenticated request.
The pinned CPA can exit 0 after a carrier or cache failure. A missing or
mismatched cache needs a matched restore or new human enrollment, because a
consumed enrollment carrier cannot recreate lost identity keys.

Recovery loses everything after the snapshot: later consumer keys, policy and
account changes, and accounting. Stale OAuth refresh state may need an operator
login. After named consumers exist, only Home recovery preserves them. Before
then, use the standalone rollback and keep the current refreshed provider state.

### Assisted updates

Renovate holds every update to this stack, tags and digests alike, for
dependency-dashboard approval. The hold applies to new update branches, not
ones already approved. Before approving: review the pair's compatibility, take a
snapshot with the old Home pin, and run the pinned-pair gate and full
`./validate.sh`. Record post-update acceptance before advancing the baseline.

### Pinned-pair gate

```bash
./validate.sh tests tests/regression/cliproxy_home_recovery_gate.py
```

Using synthetic credentials on an internal Docker network, this enrolls a CPA
with Home, takes a native full snapshot, restores it into an empty target,
compares persistent state and reconnects the same CPA identity from the copied
cache. It uses the deployed CPA pin and the gate's Home pin. It needs a local
Docker daemon and fails without it. No-argument `./validate.sh` does not run it.
