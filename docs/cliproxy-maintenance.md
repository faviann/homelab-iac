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
- Both Home containers are running (`stop` and `remove-home`).
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
The exact-image recovery gate below adds native enrollment, snapshot and
restore verification; remaining client/panel behavior and live acceptance
belong to the later integration and human cutover gates.

## Matched recovery and assisted updates

This prepares recovery for the accepted [Home integration plan](https://github.com/faviann/homelab-iac/issues/476#issuecomment-5985413171).
It does not enroll or activate production Home. The initial compatible pins are:

| Component | Image | Source revision |
| --- | --- | --- |
| CPA | `eceasy/cli-proxy-api:v7.3.8@sha256:6c2c8a7904799bd29a3f7f92a598555d8321b6a5682000b87af4495c5704fa72` | `c93978c4ea2e908255a2a06c37599fda3651554a` |
| Home | `eceasy/cli-proxy-api-home:v1.1.0@sha256:14e666f537b26a3fe1cb1a17b458000ff80898edbd7d6cafd83a4d5f7450a49c` | `c098d84d36f57b765e1545dcb53cb6717a673654` |

Home owns runtime configuration, provider credentials/refresh state, consumer
keys and revocations, persistent accounting and cluster trust. Ansible owns
topology, pinned images, private directory declarations and startup inputs.
Keep `home` and `cpa` outside synced `appdata`, `x-prereq-dirs` and
`x-managed-files`; those mechanisms can normalize parent modes to 0755.
The existing auth directory remains protected until initial standalone
rollback acceptance closes. Existing overmind data/backup mounts suffice.
The Postgres backup timer does not protect Home; there is no Home timer.

Take a snapshot **after successful CPA enrollment**, after administrative
key/account/policy changes, and before every image or schema update:

```bash
scripts/cliproxy-maintenance.sh snapshot baseline-20261005
```

The new candidate under `/backups/overmind/cliproxy/<name>` contains
`home.zip`, the matching `cpa/` certificate cache, `images.txt` (deployed
digest-pinned images and repository revision), artifact checksums and a private
native export log. Record the upstream source revisions above for the initial
pair; an assisted update records its reviewed revisions and compatibility
evidence alongside the new candidate. Never edit pins in an existing set.
Names contain only letters, digits, underscores and hyphens; an existing
successful or incomplete candidate is never reused.

The script requires root:root 0700 parent directories, creates artifacts under
umask 077 and repairs existing runtime/cache and copied file modes to 0600
(directories 0700). Home export opens SQLite and runs its schema migration, so
use the **old deployed pin** before upgrading and mount the whole writable
database directory, including WAL/SHM. Never substitute a live `home.db` copy.
Native [`-db-export`](https://github.com/router-for-me/CLIProxyAPIHome/blob/c098d84d36f57b765e1545dcb53cb6717a673654/cmd/home/main.go)
creates a format-6 full snapshot in this pin, despite the README's stale
format-4 claim. It includes config, provider state, key metadata, accounting
and CA/private keys. Legacy `-export` creates exchange config/auth only and
loses Home-only metadata; it is not a matched recovery snapshot. Snapshot ZIPs
are **plaintext secrets** even at 0600. Never commit, publish, print or inspect
their payloads in evidence.

A candidate becomes successful only after a restore rehearsal with its
recorded pinned pair and matching cache on an isolated target. Block all
provider/production egress; a copied identity must never reach production
Home or refresh real accounts. Verify persistent state and native CPA
reconnection. The required synthetic gate is:

```bash
./validate.sh tests tests/regression/test_cliproxy_home_recovery.py
```

It requires a local Docker daemon and resolves these exact pinned images;
unavailable prerequisites fail the gate. It does not use production state.
Keep the current and previous **successful** matched recovery sets. Incomplete
or failed candidates never advance retention. Record acceptance privately
using names, revisions, counts and outcomes, with no secret payloads. Older
sets may remain until a human approves their retirement; no automated pruning
or backup service is introduced.

For recovery, keep the maintenance freeze and select a verified matched set:

```bash
scripts/cliproxy-maintenance.sh restore baseline-20261005
```

The native tool imports into a genuinely new empty
`/data/overmind/cliproxy/restore-<name>-<unique-attempt>/home` directory; a populated persistent
target is rejected by Home. The script keeps failed Home state (including
sidecars) and CPA cache under that attempt's `failed-home` and `failed-cpa`,
then installs the restored pair at the declared runtime paths. Native full
restore preserves persistent business state; expired/runtime-only records
and internal migration rows may intentionally be skipped. This is not a
byte-for-byte SQLite copy. Native output stays in private logs, and failed
attempt directories remain for diagnosis rather than being merged or retried.

Before clients return, restore the recorded compatible **pair** image pins and
revision, and reapply every revocation made after the snapshot through native
Home administration with CPA/client admission still blocked. The later
enrollment/cutover procedure supplies that isolated administrative phase;
`restore` deliberately leaves all writers stopped. Only then deploy through
`./run.sh` and perform secret-safe functional acceptance. Missing or mismatched
CPA cache/trust requires a matched restoration or new human enrollment. A
consumed enrollment carrier cannot recreate lost identity keys.
The pinned CPA may exit with status 0 after a carrier/cache failure; require
native connected identity and authenticated functional readiness, not an exit
code or container creation result.

Recovery rolls back changes after the last snapshot. Later consumer keys,
policy/account changes and accounting may be lost; later revocations must be
reapplied, and stale OAuth refresh state may require operator login. After named
consumer rollout, use Home recovery: the original single-key standalone
template cannot preserve those consumers. Before rollout, follow the separately
prepared initial standalone rollback procedure and preserve current refreshed
provider state rather than silently restoring stale tokens.

Renovate holds every update in this stack for dependency-dashboard approval,
including tag and digest changes and the future Home sibling. This holds new
update branches, not previously approved branches or rebases. An operator
reviews the pair's compatibility, takes a pre-update set with the old Home
binary, runs full `./validate.sh` plus the pinned pair's recovery/compatibility
checks, and records post-update acceptance before advancing the baseline.
Literal image pins remain in Compose for discovery; no automatic schema or
image upgrade is permitted.
