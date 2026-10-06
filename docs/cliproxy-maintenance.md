# Human maintenance of CPA and Home

This is the procedure behind the human-only
[command-policy exception](command-policy.md#cpahome-maintenance-on-overmind).
It covers CPA/Home on `overmind`: protected backup and restore, assisted pair
updates, node enrollment, and emergency termination of revoked CPA sessions.
Ordinary deployment stays on `./run.sh`. Agents do not run this against
managed hosts.

## Names

| Name | What it is |
| --- | --- |
| `cliproxy` | CPA, Compose service and container in project `cliproxy` |
| `cliproxy-home` | Home, same project |

CPA and Home both write state, so each of them counts as a **writer**.

Native one-shot tools use the images pinned for the deployed pair in
[`compose.yaml`](../stacks/overmind/cliproxy/compose.yaml).
After an assisted update, use the pins recorded
with the recovery set you restore from, and use the old Home image for the
pre-update export.

Private maintenance state lives under `/data/overmind/cliproxy/home`,
`/data/overmind/cliproxy/cpa`, and a unique subdirectory of
`/backups/overmind/cliproxy`. Require root ownership, 0700 directories and
0600 files before you use them. Never copy a live `home.db` on its own, and
never overwrite a populated restore target.

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
| `stop` | Stops Home, then CPA, and confirms each one exited. Use it before offline state work. |
| `restart-cpa` | Emergency. Stops and restarts CPA only. Home keeps running. |
| `snapshot <name>` | Stops all writers, exports the full Home database with the deployed pinned image, and copies its enrolled CPA cache into a new private recovery candidate. Leaves writers stopped. |
| `restore <name>` | Stops all writers, checks the candidate's artifact hashes, restores with its recorded Home image into a new empty directory, preserves failed state and replaces the runtime database/cache together. Leaves writers stopped. |

Actions abort without further changes on failures in the checks they perform:

- Docker can't list or inspect a container. A failed inspection never counts
  as "absent".
- A container is paused, restarting, or dead.
- A writer is still running after it was stopped.

Stops give Docker 30 seconds before SIGKILL, so active requests can be cut off
mid-stream. Container inspection, stop, removal and restart calls are
capped at 45 seconds. Offline native export and restore have no time cap.

Why Home stops first: Home's subscriptions can keep CPA from finishing
SIGTERM.

Never use Compose `down`, `--remove-orphans`, project-wide or pattern-based
removal, or volume or network deletion.

### Offline state work

Snapshot and restore start with the `stop` sequence, so they run under the
same lock and only after every writer has exited. The SSH session has no
overall time limit, so a long restore is not killed partway through. Native
one-shot tools run with `--network none` and no published ports.

### Emergency CPA restart

First [revoke the individual consumer key](#revocation-and-session-limits)
through Home administration. Revocation rejects new requests only; `restart-cpa`
interrupts **every** CPA session and may reach the
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

## Native node enrollment and durable trust

CPA joins Home once, with a one-time enrollment carrier (`HOME_JWT`). A fresh
enrollment is needed only when the CPA cache is lost and no matched recovery
set can restore it. It is a human step.

In the [LAN panel](#lan-administration-and-acceptance), use the native CPA
node-enrollment dialog to create **one** node named `cliproxy`. Each creation
issues another pending enrollment, and the pinned Home cannot revoke a pending
one, so create it once and keep the carrier it returns. Record the non-secret
certificate ID and node name.

Add the carrier to the vault as `vault_overmind_cliproxy_home_jwt`, either with
`./vault.sh edit` or by moving a protected 0600 file with
`./vault.sh set vault_overmind_cliproxy_home_jwt --from-file <path> --replace --strip-final-newline`.
Never echo it, pass it in an argument, dump browser requests or inspect a
container's environment. Clear the clipboard and retire any temporary file.

Deploy through the facade. CPA sends a CSR, Home issues the certificate and
consumes the enrollment secret, and CPA caches its trust under
`/data/overmind/cliproxy/cpa`. There is no automatic reenrollment.

Accept the issued trust before relying on it. Require the recorded identity to
be active in Home and an authenticated client/provider request to succeed.
Check root:root 0700 on `/data/overmind/cliproxy/cpa` and root:root 0600 on its
`client-crt.pem`, `client-key.pem` and `home-ca-crt.pem`, using file metadata
only. Then run:

```bash
scripts/cliproxy-maintenance.sh restart-cpa
```

Require the same identity to reconnect with unchanged cached trust. CPA can
exit 0 on enrollment failure, so process exit status or Compose startup alone
is insufficient. Take a [snapshot](#snapshot) after acceptance.

If the cache is missing, incomplete or mismatched, escalate to matched
Home/cache restoration or a fresh human-issued enrollment. Reusing a consumed
carrier cannot recreate a lost client identity. Do not delete trust, recreate
CA state or retry automatic enrollment to get past a failure.

## LAN administration and acceptance

From a LAN client, open
`https://cliproxy-home.local.faviann.com/management.html`. Confirm DNS selects
portal and the browser accepts its existing TLS certificate, then connect with
the management password. Home's native management
authentication owns this login; there is no Authentik or `MANAGEMENT_PASSWORD`
override. A missing or wrong password must fail. The old
`https://cliproxy.local.faviann.com/management.html` must return 404 while the
client API continues serving at its unchanged addresses.

Use the shipped Home panel's account-addition flow for any provider that needs
reauthentication or a newly accepted account. Complete the provider's login in
the browser. If its localhost callback cannot open, copy the complete callback
URL privately from the address bar and paste it into Home's callback submission
field. Require a successful result and a working provider request before
accepting that account. Never put authorization URLs, callback URLs, passwords
or tokens in logs, chat or Git.

The entire Home hostname uses the existing `local-ip-restriction` allowlist;
verify a client outside it receives 403. No path bypass or public administration
is configured. The direct listeners stay reachable on the flat LAN; see
[the shared-pool ADR](adr/0013-share-one-ai-provider-credential-pool.md).

Record acceptance as hostname, revision, pins and outcomes without secret
payloads.

## Consumer identity rollout

This prepares [#484](https://github.com/faviann/homelab-iac/issues/484). Only a
human enrolls real consumer secrets and changes consumer configuration.
Use Home's native API-key controls through the accepted LAN panel. The
individual API operations below also describe the supported native management
path; they are request shapes, not terminal commands. Supply passwords and
key values through private native input or protected files. Never print the
key-list response: it includes every raw key, even when only IDs/names are
needed. No provider credential or CPA enrollment carrier is a consumer key.

### Readiness and enumeration

Before the first real consumer-key change, require all of these:

- Initial client/provider acceptance at both unchanged addresses and
  [LAN panel/callback acceptance](#lan-administration-and-acceptance) are
  recorded on [#477](https://github.com/faviann/homelab-iac/issues/477).
- A [matched recovery set](#snapshot) taken after enrollment has passed its
  isolated [restore rehearsal](#retention).
- The [synthetic identity gate](#synthetic-identity-gate) passes at the accepted
  pair pins. A maintenance window covers key changes, snapshot stops and any
  emergency restart, since each can interrupt other consumers' sessions.

Enumerate known consumers from operator knowledge and accepted deployment
contracts. Fill the
[non-secret inventory](../stacks/overmind/cliproxy/README.md#consumer-identities-and-inventory)
with actual names, stable numeric Home IDs, actual credential-source owners
and observed migration status. Keep unidentified consumers on the legacy key.
Broodling follows its
[fixed gateway contract](../stacks/overmind/cliproxy/README.md#broodling-gateway-contract).

### Individual native key operations

Use `/v8/management/access/api-keys` with Home's native management
authentication. The
[pinned native implementation](https://github.com/router-for-me/CLIProxyAPIHome/blob/c098d84d36f57b765e1545dcb53cb6717a673654/internal/cluster/management/api_keys.go)
supports these operations:

| Operation | Method and input | Record to keep |
| --- | --- | --- |
| Identify the imported record privately | `GET`; match its key privately against the frozen legacy credential | Its `items[].id` / `api_key_id`, without copying the secret-bearing response |
| Create one actual consumer key | `POST` body `{"api_key": "<REPLACE_ME>", "display_name": "<ACTUAL_CONSUMER>", "user_id": null, "channels": [], "model_groups": []}` | Returned `api_key.id`, approved secret reference and actual owner |
| Rename one record, including the legacy one to `legacy-shared` | `PATCH` body `{"id": <HOME_KEY_ID>, "display_name": "<NAME>"}` | Same stable ID and key value; updated inventory name |
| Revoke one record | `DELETE` with query `id=<HOME_KEY_ID>` | Retained inventory row, revocation date and outcome |

Do not use a bulk `PUT`, positional list indices or secret-valued query
selectors. Verify the imported legacy record is unowned and has empty channel
and model-group bindings. Create named keys with those same unrestricted
bindings; this shares one existing provider pool without Home User tenancy,
per-consumer channels, quotas or model policy. Naming the legacy record
does not identify its individual callers.

### Migrate one actual consumer

1. Privately create a distinct consumer key using the individual native
   operation. Confirm its actual name, returned ID, null owner and empty
   bindings. Record the secret-source owner/reference and status `prepared`;
   keep its value only in the approved credential store and native state.
2. Change only that consumer's gateway credential using its owner's supported
   procedure. Keep its base URL, model and request behavior. Test the actual
   consumer contract and an unrelated named/legacy consumer. On failure,
   stop this rollout: keep the legacy key serving, return this consumer to its
   accepted legacy credential if necessary, and revoke its unused candidate
   by ID.
3. Send a fresh accepted request and verify attribution through Home's native
   `/v8/management/usage/records?client_key_id=<HOME_KEY_ID>` or
   `/v8/management/usage/aggregates?group_by=client_key`. Match the record's
   `client.api_key_id` or aggregate `id` to the inventory ID; the label may be
   `api-key-ID` rather than the friendly name. Accounting is asynchronous:
   wait for that request to appear, and record only non-secret ID/outcome
   evidence. The provider API-key usage view measures provider credentials,
   not consumer identity. Do not inspect/export payloads or raw key responses.
4. Record status `migrated` only after behavior and ID attribution pass. Take
   the [manual protected snapshot](#snapshot) after this administrative key
   change, and resume through the existing supported deployment procedure.
   Accept the recovery candidate through its isolated matched restore before
   advancing retention. Snapshot creation stops Home and CPA, so schedule it
   with every affected consumer. Then move to the next actual consumer.

Keep deleted/revoked inventory rows and the ID evidence. Reapply later
revocations after a stale snapshot restore before consumers return. Home
remains the key authority; the inventory records the accepted migration and
revocation outcomes.

### Revocation and session limits

First create a sacrificial key without changing any real consumer. Prove a
request works, delete that one record by ID, and require its next independent
request to be rejected while the other named and legacy keys still work.
Record the revocation outcome and snapshot the resulting administrative state.
Real revocation uses the same individual operation and preserves its inventory
row; legacy retirement needs a separate explicit decision confirming no
remaining callers depend on it.

Revocation rejects new requests only. It does not prove existing work ended:
an accepted HTTP stream can finish, and the pinned
[CPA retained selection path](https://github.com/router-for-me/CLIProxyAPI/blob/c93978c4ea2e908255a2a06c37599fda3651554a/sdk/cliproxy/auth/conductor_home.go)
reuses an existing same-model WebSocket selection without a fresh key check.
Any key change publishes a configuration update that CPA reloads, which can
also interrupt unrelated consumers' native sessions; do not rely on it as a
per-consumer session kill. Treat existing work as potentially authorized until
it closes. For guaranteed termination, revoke first and run the human-only
bounded action:

```bash
scripts/cliproxy-maintenance.sh restart-cpa
```

This interrupts **all** CPA sessions, including unrelated consumers, and can
force termination after the stop deadline. Follow
[emergency CPA restart](#emergency-cpa-restart), then require fresh rejection
for the revoked key and readiness for the surviving keys.

### Synthetic identity gate

```bash
./validate.sh tests tests/regression/cliproxy_home_identity_gate.py
```

This explicit local-Docker gate reuses the pinned-pair fixture with synthetic
credentials and one fake provider. It labels the imported legacy record without
changing its ID or value, creates multiple unowned unrestricted named records
individually, and checks attribution by stable ID. Deleting one record by ID
rejects its next request while the other named and legacy keys keep serving.
It does not check existing sessions; see
[revocation and session limits](#revocation-and-session-limits). No-argument
`./validate.sh` excludes this Docker-dependent filename.

## Matched recovery and assisted updates

Home owns runtime configuration, provider credentials and refresh state,
consumer keys and revocations, accounting and cluster trust. Ansible owns
topology, pinned images, private directory declarations and startup inputs.
Home state and the enrolled CPA certificate cache live in root-only 0700
directories under `/data/overmind/cliproxy/{home,cpa}`. Recovery sets live under
`/backups/overmind/cliproxy`. Keep these out of synced `appdata`,
`x-prereq-dirs` and `x-managed-files`, which can reset parent modes to 0755.
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
login.

### Assisted updates

Renovate holds every update to this stack, tags and digests alike, for
dependency-dashboard approval. The hold applies to new update branches, not
ones already approved. Before approving: review the pair's compatibility, take a
snapshot with the old Home pin, and run the pinned-pair gate and full
`./validate.sh`. Record post-update acceptance before advancing the baseline.

### Pinned-pair gate

```bash
./validate.sh tests tests/regression/cliproxy_home_runtime_gate.py tests/regression/cliproxy_home_recovery_gate.py tests/regression/cliproxy_home_identity_gate.py
```

The runtime gate materializes the actual repository stack and starts its
rendered Compose wiring with only isolated names, paths and network/port
overrides. It checks that a missing carrier fails rendering, the private `.env`,
native DNS/mTLS identity, the legacy key with Broodling's `gpt-5.6-sol`
tools/JSON request, an unchanged redeploy that recreates nothing, the cluster
document mounted read-only, and private startup umasks. Stack sync recreates
Home after a cluster change; its regression covers that rule. Protocol behavior belongs to the pinned images and is a
human acceptance check. The recovery gate, described next, owns restart from cached trust and the native matched restore.

Using synthetic credentials on an internal Docker network, this verifies the
imported bcrypt password through native remote management and that the embedded
panel is served. It enrolls CPA through `cliproxy-home:8327`, checks private
issued cache modes, restarts with the consumed carrier and unchanged trust, and
proves cache loss cannot reuse that carrier. The same fixture takes
a native full snapshot, restores it into an empty target, compares persistent
state and reconnects the same CPA identity from the matching copied cache.
It uses the deployed CPA pin and the resolved Home pin. It needs a local Docker
daemon and fails without it. No-argument `./validate.sh` does not run it.
This is isolated native-image evidence, not production enrollment, a browser
interaction test or real OAuth/provider acceptance; those remain human gates.
