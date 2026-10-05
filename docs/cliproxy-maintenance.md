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
| `cliproxy-home-bootstrap` | Temporary plain Home container used once for enrollment, outside the stack network |

CPA always exists. Before migration, both Home containers may be absent. CPA
and Home both write state, so each of them counts as a **writer**.

Native one-shot tools use the images pinned for the deployed pair in
[`compose.yaml`](../stacks/overmind/cliproxy/compose.yaml).
After an assisted update, use the pins recorded
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
| `start-bootstrap` | Starts one plain named Home from the imported database and reviewed cluster file, publishing 8327 on loopback only. Requires stopped writers; Docker refuses a second bootstrap by name. |
| `stop` | Stops both Home containers, then CPA, and confirms each one exited. Use it before offline state work. |
| `remove-bootstrap` | Removes the stopped bootstrap. The running pair is left alone. Use it only after initial acceptance and a verified matched recovery baseline. |
| `remove-home` | Standalone rollback. Runs `stop`, then removes both Home containers, which ordinary Compose startup would leave as orphans. CPA stays stopped until you deploy the original revision. Preserve the failed state first; removing the containers does not delete bind mounts. |
| `restart-cpa` | Emergency. Stops and restarts CPA only. Home keeps running. |
| `import-legacy <name>` | Freezes complete standalone config/auth in a new private candidate, imports only from a writable config/top-level OAuth copy into an empty Home directory, and leaves writers stopped for human acceptance. |
| `export-current <name>` | Preserves the whole stopped Home directory and any CPA cache, then exports current legacy state into a new empty candidate. Leaves writers stopped for human coverage/status acceptance. |
| `rollback-original <name>` | Before Home could refresh. Replaces standalone auth with the frozen original after checking its hashes, keeps the displaced tree, and removes both Home containers. |
| `rollback-current <name>` | After possible refresh. Replaces standalone auth with an accepted current export, keeps the displaced tree, and removes both Home containers. |
| `snapshot <name>` | Stops all writers, exports the full Home database with the deployed pinned image, and copies its enrolled CPA cache into a new private recovery candidate. Leaves writers stopped. |
| `restore <name>` | Stops all writers, checks the candidate's artifact hashes, restores with its recorded Home image into a new empty directory, preserves failed state and replaces the runtime database/cache together. Leaves writers stopped. |

Actions abort without further changes on failures in the checks they perform:

- Docker can't list or inspect a container. A failed inspection never counts
  as "absent".
- A container is paused, restarting, or dead.
- Both Home containers are running when an action fences all writers.
- A writer is still running after it was stopped.

Stops give Docker 30 seconds before SIGKILL, so active requests can be cut off
mid-stream. Container inspection, stop, removal and restart calls are
capped at 45 seconds. Offline native export and restore have no time cap.

Why Home stops first: Home's subscriptions can keep CPA from finishing
SIGTERM.

Why the bootstrap is kept until acceptance: normal deployment prunes unused
images. The stopped bootstrap keeps the pulled Home image in use. It never
joins the stack network, so it cannot compete for the permanent Home's alias.

Never use Compose `down`, `--remove-orphans`, project-wide or pattern-based
removal, or volume or network deletion.

### Offline state work

Import, export, standalone rollback, snapshot and restore start with the
`stop` sequence, so they run under the same lock and only after every writer has exited. The SSH session
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

## One-time standalone import and initial rollback

This finite transition keeps the original client addresses, arbitrary legacy
client key and management bcrypt hash. Ordinary deployment never imports. The
import is accepted through the [loopback bootstrap](#native-node-enrollment-and-durable-trust)
before issuing its pending machine enrollment. Permanent activation follows
that acceptance; see [the integrated cutover](#permanent-activation-and-initial-acceptance).

### Freeze and inventory

Before stopping standalone CPA, record a private **safe inventory** from the
authenticated panel and operator knowledge: the original repository revision and
CPA pin; OAuth filenames and count; each account's identity, active/disabled
status and previously healthy models; the config-based provider record count; and
the metadata in use (expiry/refresh status, account identity, routing prefix,
excluded models, headers, custom fields). Record names, counts and outcomes only.

Until initial acceptance ends, freeze all client keys, runtime policy and
config-based provider roots. Rollback re-renders the original template, so a
change to any of them abandons this procedure for matched Home recovery or human
reauthentication. Also freeze other controllers and Home administration between
script calls, and admit no clients while a candidate is unaccepted. Check free
space for the source, its copy, Home state and recovery candidates. The script
fences only the three named containers; confirm nothing else owns these paths.

Before stop/import, synchronize the reviewed standalone checkout through the
facade so the non-secret Home cluster file is deployed:

```bash
./run.sh configure --limit overmind --stack cliproxy
```

This revision still runs standalone CPA. The facade can reconcile Docker,
upgrade host packages and reboot; include those effects in the maintenance
window. The cluster file carries only the SQLite path and advertised Home
identity. Its permanent service binding belongs to the later runtime change.

### Import once

Run from a clean checkout of the reviewed **original standalone revision**: one
that contains this script and still defines standalone CPA. `import.txt` records
that HEAD as the rollback revision, so never import from a Home-runtime checkout.
Confirm its template and vault references reproduce the deployed config, then:

```bash
scripts/cliproxy-maintenance.sh import-legacy initial-20261005
```

The script aborts unless `/data/overmind/cliproxy/home` is absent or an empty
root:root 0700 directory. There is no repeat-import or populated-DB option. The
standalone config must be root:root 0600, its auth directory root:root 0700, and
top-level OAuth files regular root:root 0600 files. The new candidate holds:

- `original/`: the untouched config and complete auth tree. It is never mounted
  into a native import; `SOURCE_SHA256SUMS` lets rollback prove it is unchanged.
- `bootstrap/`: the writable copy, holding config and top-level OAuth JSON only.
- `import.txt` (Home pin, standalone revision, OAuth file count) and `import.log`.

The pinned Home v1.1.0 digest runs native `-import` with `--network none`. Home
adds UUIDs to the writable OAuth copies **before** its database transaction, so a
failure can leave changed copies and a partial DB. Abandon both: never reimport,
merge or repair them. After a lost SSH session, resolve the actual state first.

Native success only prepares a candidate. Before any machine enrollment, compare
`import.log` with the safe inventory and inspect each account through the
bootstrap's authenticated panel. Confirm the legacy key and bcrypt hash with the
native checks in the [bootstrap procedure](#native-node-enrollment-and-durable-trust),
without printing them. UUID addition and
documented config normalization are expected.

The native `created/updated/unchanged/skipped` totals mix config roots, client
keys and credentials; they are **not OAuth account counts**. `auth-dir`,
config-provider roots synthesized into credential records, and concurrency roots
are intentional structural skips. Any other skip, a missing OAuth account, a
changed active status, collapsed duplicates, lost metadata or an unexplained count
aborts acceptance: keep clients fenced and take a rollback branch below. Never
patch SQLite or YAML by hand to pass acceptance.

### Rollback before Home could refresh

Use this only when Home/CPA cannot have used or refreshed the imported
credentials. If unsure, use the current-export branch.

```bash
scripts/cliproxy-maintenance.sh rollback-original initial-20261005
```

It verifies `SOURCE_SHA256SUMS`, replaces the standalone auth tree with the frozen
one, moves the displaced tree into a new `rollback-original-*` attempt, and
removes both Home containers, which Compose `up -d` would leave as orphans. Home
state stays in place for diagnosis. Nothing starts. From a clean checkout of the
recorded revision, with the frozen vault references, deploy:

```bash
./run.sh configure --limit overmind --stack cliproxy
```

The deploy re-renders the frozen config. Recheck legacy clients and each
previously healthy provider before lifting the freeze; a started container is not
acceptance.

### Rollback after possible refresh

Never restore stale original tokens once Home may have refreshed them. Export the
current state first:

```bash
scripts/cliproxy-maintenance.sh export-current current-20261005
```

It copies the whole Home directory (with WAL/SHM) and any CPA cache into the new
candidate first, because native export opens and migrates the database. It then
runs the pinned Home offline with `-export-dir /export`, producing
`export/config.yaml` and `export/auths/`. This legacy export is not #479's matched
recovery format.

Exit 0 and a file count are not acceptance: export writes config before auth, can
leave partial output, and can collapse records whose original filenames
duplicated. Compare `export/` with the current safe inventory: every provider,
active/disabled status and current refresh/account metadata, plus unchanged YAML
provider roots, legacy key and management hash. An unusable export means human
reauthentication or matched Home recovery, never stale-token fallback. Keep it as
evidence and retry under a new name. Only after acceptance:

```bash
scripts/cliproxy-maintenance.sh rollback-current current-20261005
```

It replaces the standalone auth tree with `export/auths/`, keeps the displaced
tree in a `rollback-current-*` attempt and removes both Home containers. It never
installs the exported config. Deploy the original revision as above while the
frozen baseline still holds, then recheck providers and legacy clients.

### Close the window

Keep the frozen original until initial client/provider acceptance passes. After
cutover, verify #479's enrolled matched recovery set, then record **standalone
rollback closed** before the first real consumer-key switch
([#484](https://github.com/faviann/homelab-iac/issues/484)). The original
single-key template cannot serve new keys, so later recovery uses matched Home
state. The change that records the closure also deletes the four one-time
actions, this section and the migration gate with its tests.

Archive cleanup is a deliberate human step, with no automatic prune or payload
inspection. Retire standalone and bootstrap copies only after the protected
original and verified current/previous matched recovery sets exist with private
modes. Keep each export and failed candidate until its rollback, recovery or
incident is resolved.

### Synthetic migration gate

```bash
./validate.sh tests tests/regression/cliproxy_home_migration_gate.py
```

Using the script's Home pin, the deployed CPA pin, synthetic credentials and a
fake provider on an internal network, the gate proves original/copy separation,
silent preservation of the legacy key, bcrypt hash and OAuth metadata, UUID
normalization, current export after simulated refreshed metadata, and restored
standalone provider behavior. Script stand-ins cover auth-tree replacement and
removal of both Home containers. It does not exercise real OAuth refresh; real
account health is human acceptance. Only this named gate needs Docker, so
no-argument `./validate.sh` does not.

## Native node enrollment and durable trust

This continues the accepted one-time import above. The human performs these
steps under the same maintenance freeze. Existing standalone CPA remains
stopped; permanent Home/CPA activation follows these steps. The
isolated [pinned-pair gate](#pinned-pair-gate) verifies that future activation
contract using synthetic credentials.

### Start and reach the temporary Home

Use the reviewed standalone checkout synchronized before import, then:

```bash
scripts/cliproxy-maintenance.sh start-bootstrap
```

The action uses the imported `/data/overmind/cliproxy/home/home.db` and the
single reviewed [`cluster.yaml`](../stacks/overmind/cliproxy/appdata/config/cluster.yaml)
at `/conf/docker/stacks/cliproxy/appdata/config/cluster.yaml`. It starts the
resolved Home v1.1.0 digest with `umask 077`, no Compose labels, no automatic
restart, and `127.0.0.1:8327:8327` only. The cluster file advertises
`cliproxy-home:8327`; that identity goes into the carrier, regardless of the
bootstrap's network or the browser's tunnel address, so the bootstrap stays off
`cliproxy_default`. Docker refuses an existing bootstrap, including a stopped
one. Preserve that attempt and resolve it before starting another; do not
remove it to retry.

From the workstation, keep this human-only tunnel open in another terminal:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8327:127.0.0.1:8327 \
  -l root -i ~/.ansible/ssh/proxmox_lxc overmind
```

Open `http://127.0.0.1:8327/management.html`. If workstation port 8327 is
occupied, change only the left-hand tunnel port and the browser URL. The
embedded Home panel needs no download into the old CPA auth tree.

Log in using the **existing management password**, the plaintext corresponding
to the imported bcrypt hash. Keep `remote-management.allow-remote: true`; Docker
forwarding is not an authentication bypass. Do not supply `MANAGEMENT_PASSWORD`,
change the password, reimport or modify SQLite to get login working. A failed
login or unavailable panel aborts acceptance.

In the authenticated panel, compare the legacy client key with its protected
original and review every imported provider account, status and metadata against
the safe inventory. Keep values inside the private panel and original files;
record only names, counts and outcomes. Do not start provider logins or change
runtime policy. A running Home is not import acceptance. Home may refresh
accounts, so use the current-export rollback branch if refresh cannot be ruled
out.

### Issue and protect one pending machine enrollment

After import acceptance, use the panel's native CPA node-enrollment dialog to
create one node named `cliproxy`. The native operation is
`POST /v8/management/certificates/clients` with `node_name: cliproxy`; use the
panel, without a custom request script or credential-bearing command arguments.
Keep the returned `home_jwt` carrier private. Record its non-secret certificate
ID and node name for later connected-identity acceptance.

On the workstation, use the human vault editor:

```bash
./vault.sh edit
```

Add `vault_overmind_cliproxy_home_jwt` and transfer the carrier directly from the
private panel into the editor. Use a protected 0600 file in a private 0700
directory if a temporary file is needed. Keep it outside Git and issue evidence;
never echo it, pass it in an argument, dump browser requests or inspect a
container's environment. Close the editor to persist the encrypted vault, then
clear the clipboard and retire any temporary carrier file. Keep the existing
legacy client-key and management-hash vault entries for rollback.

At this point the certificate is **pending**. Issuing the carrier does not
connect CPA, consume the enrollment secret or create its cache. When permanent
activation first starts CPA with `HOME_JWT`, native CPA sends a CSR, Home
issues the certificate and consumes the enrollment secret. Startup then keeps
using that carrier's target/identity with its matching persisted trust. There
is no automatic reenrollment.

### Stop and retain before permanent activation

After saving the pending carrier, run:

```bash
scripts/cliproxy-maintenance.sh stop
```

This uses the existing bounded Home-first stop and fails unless the bootstrap
exited. On failure, keep the freeze and preserve the attempt. Close the tunnel. Retain the stopped container through initial acceptance so
normal image prune keeps the pulled Home image available.

### Accept issued trust and take its matching snapshot

After permanent activation, require the recorded named CPA identity
to be healthy in Home and an authenticated legacy client/provider request to
succeed. The imported management password must still work through the native
panel. Check root:root 0700 on `/data/overmind/cliproxy/cpa` and root:root 0600 on
its `client-crt.pem`, `client-key.pem` and `home-ca-crt.pem`, using file metadata
only. Exercise the existing bounded restart:

```bash
scripts/cliproxy-maintenance.sh restart-cpa
```

It interrupts all CPA sessions. Require that same identity to reconnect with
unchanged cached trust and the original, now-consumed carrier. CPA can exit 0 on enrollment failure, so
process exit status or Compose startup alone is insufficient.

Only **after certificate issuance and cache acceptance**, take a full Home
snapshot and its matching CPA cache using the existing
[snapshot procedure](#snapshot). A pre-enrollment database or legacy export is
not this baseline. Verify isolated matched restore before recording initial
acceptance. Then retire only the stopped bootstrap:

```bash
scripts/cliproxy-maintenance.sh remove-bootstrap
```

Snapshot leaves the permanent writers stopped. From the reviewed runtime
checkout, deploy the pair again through the facade and recheck functional
acceptance before lifting the freeze.

Retain the current and previous accepted recovery sets under the existing
retention policy. If the cache is missing, incomplete or mismatched, stop and
escalate to matched Home/cache restoration or a fresh **human-issued** enrollment
with its own acceptance and new snapshot. Reusing the consumed carrier cannot
recreate the lost client identity. Do not delete trust, recreate CA state or
retry automatic enrollment to get past a failure.

## Permanent activation and initial acceptance

This puts the procedures above in cutover order. PR completion verifies
synthetic behavior only; the human records production acceptance on
[#477](https://github.com/faviann/homelab-iac/issues/477).

1. **Rehearse.** Run full `./validate.sh` and the
   [pinned-pair gate](#pinned-pair-gate) at the exact pins, and record
   revisions, pins and outcomes. Confirm free disk space and that port 8327 is
   free on `overmind`. Confirm `cliproxy-home.local.faviann.com` resolves to
   portal from the operator's LAN client. DNS is human-managed; the existing
   `*.local.faviann.com` TLS certificate covers the new hostname. Runtime
   startup alone cannot pass the [LAN acceptance](#lan-administration-and-acceptance).
2. **Freeze, inventory and import** from the original standalone revision:
   [Freeze and inventory](#freeze-and-inventory), then [Import once](#import-once).
3. **Enroll and stop the bootstrap:**
   [Native node enrollment and durable trust](#native-node-enrollment-and-durable-trust)
   through [Stop and retain](#stop-and-retain-before-permanent-activation).
   Never run two Home writers on the same SQLite state.
4. **Activate.** From the clean reviewed Home-runtime checkout, run:

   ```bash
   ./run.sh configure --limit overmind --stack cliproxy
   ./run.sh configure --limit portal --stack traefik3
   ```

   This can still configure and reboot the host; see
   [Deploy, accept or recover](#deploy-accept-or-recover). Check the exact
   pins, one running Home writer, `.env` at 0600 and both PID 1 umasks at 0077.
   Readiness means native Home login with the imported management password,
   the recorded CPA identity healthy in Home, and a legacy-key request served
   by a known provider and model. A clean recap, a running container or CPA
   exit 0 is not readiness.
5. **Accept clients and providers, or roll back.** Keep keys and policy frozen.
   Use the original key and representative real consumers at both
   `https://cliproxy.local.faviann.com` and `http://overmind.faviann.vms:8317`.
   Require all of these:
   - Broodling's gateway `/v1` URL with `gpt-5.6-sol` Chat Completions, tools
     and JSON output, plus each protocol another known consumer uses
     (streaming, Anthropic Messages, Responses HTTP/SSE/WebSockets).
   - Every previously healthy Claude/Codex account still serves, and accounts
     and management login match the safe inventory.
   - A Home runtime edit reaches CPA and survives a supported redeploy without reimport.
   - With Home stopped, requests fail instead of being served standalone.
   - [LAN administration and acceptance](#lan-administration-and-acceptance),
     including the native panel, imported password and real provider callback.

   On any failure, preserve evidence and take the matching rollback branch:
   [before](#rollback-before-home-could-refresh) or
   [after possible refresh](#rollback-after-possible-refresh).
6. **Take the enrolled recovery baseline:**
   [Accept issued trust and take its matching snapshot](#accept-issued-trust-and-take-its-matching-snapshot).
7. **Close the window:** record **standalone rollback closed** as in
   [Close the window](#close-the-window), before the first real consumer-key
   change.

### LAN administration and acceptance

From a LAN client, open
`https://cliproxy-home.local.faviann.com/management.html`. Confirm DNS selects
portal and the browser accepts its existing TLS certificate, then connect with
the original imported management password. Home's native management
authentication owns this login; there is no Authentik or `MANAGEMENT_PASSWORD`
override. A missing or wrong password must fail. The old
`https://cliproxy.local.faviann.com/management.html` must return 404 while the
client API continues serving at its unchanged addresses.

Use the shipped Home panel's account-addition flow for any provider that needs
reauthentication or a newly accepted account. Complete the provider's login in
the browser. If its localhost callback cannot open, copy the complete callback
URL privately from the address bar and paste it into Home's callback submission
field. Require a successful result and a working provider request before
accepting that account. Imported healthy accounts need no new login. Never put
authorization URLs, callback URLs, passwords or tokens in logs, chat or Git.
The standalone CPA callback tunnels and port mappings 1455, 54545 and 51121
are retired; Home handles callback submission natively. The temporary bootstrap
tunnel above serves enrollment only and is closed before permanent activation.

The entire Home hostname uses the existing `local-ip-restriction` allowlist;
verify a client outside it receives 403. No path bypass or public administration
is configured. The direct Home HTTP listener at `overmind.faviann.vms:8327`
and CPA client listener at `overmind.faviann.vms:8317` remain reachable inside
the accepted flat LAN boundary. The portal allowlist does not protect direct
ports; future host segmentation is recorded in
[the shared-pool ADR](adr/0013-share-one-ai-provider-credential-pool.md).

Record production acceptance as hostname, revision, pins and outcomes without
secret payloads: valid DNS/TLS, native browser/password login, successful real
account addition and callback paste, previously healthy providers, allowlist
denial and both unchanged client paths. Synthetic gates below do not perform
these human checks.

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
./validate.sh tests tests/regression/cliproxy_home_runtime_gate.py tests/regression/cliproxy_home_recovery_gate.py tests/regression/cliproxy_home_migration_gate.py
./validate.sh tests tests/regression/cliproxy_home_route_gate.py
```

The runtime gate materializes the actual repository stack and starts its
rendered Compose wiring with only isolated names, paths and network/port
overrides. It checks that a missing carrier fails rendering, the private `.env`,
native DNS/mTLS identity, the legacy key with Broodling's `gpt-5.6-sol`
tools/JSON request, an unchanged redeploy that recreates nothing, a cluster
change that recreates only Home with the new document mounted read-only, and
private startup umasks. Protocol behavior belongs to the pinned images and is a
human acceptance check. The migration gate rehearses the initial standalone
rollback with synthetic refreshed credentials. The recovery gate, described
next, owns restart from cached trust and the native matched restore.

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

The route gate loads the actual Home and client router definitions and unchanged
LAN allowlist into an isolated loopback-only Traefik. It checks the shipped
Home panel and referenced assets, the panel's native password connection with
the imported bcrypt credential, and its account-addition session and pasted
synthetic canceled callback through that route. Cancellation deliberately ends
in an authentication failure without a provider token exchange. A real socket
source outside the allowlist receives 403 even with a forged forwarded header;
the admitted client route still serves the legacy key and its old panel returns
404. Only synthetic credentials and internal local Docker resources are used.
The fixture's disposable TLS proves transport only; DNS, certificate validity,
browser interactions and successful real-provider account addition remain the
[human LAN acceptance](#lan-administration-and-acceptance). This explicit gate
also needs local Docker and is excluded from no-argument `./validate.sh`.
