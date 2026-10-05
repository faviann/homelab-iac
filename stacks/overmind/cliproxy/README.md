# cliproxy

One shared Claude/Codex provider pool on `overmind`, served by CPA v7.3.8 and
managed by SQLite-backed Home v1.1.0. The existing project, CPA container and
client addresses stay the same:

- `https://cliproxy.local.faviann.com`, through portal Traefik's existing LAN
  `local-ip-restriction` route
- `http://overmind.faviann.vms:8317`, directly on the LAN

Broodling keeps its fixed gateway `/v1` URL, `gpt-5.6-sol`, Chat Completions,
tools and JSON-object contract. Initial cutover retains the legacy client key;
consumer-secret changes happen separately after acceptance.

This is a foundational controlled migration: follow the dedicated cutover and
recovery procedure below before any live deployment.

## Runtime ownership

| Input or state | Owner | Location |
| --- | --- | --- |
| Image pins, ports, startup topology | Ansible | `compose.yaml` |
| Non-secret SQLite path and advertised identity | Ansible | `appdata/config/cluster.yaml` |
| Required native connection carrier | Human enrollment, vault binding | `vault_overmind_cliproxy_home_jwt` → `.env` → CPA `HOME_JWT` |
| Runtime settings, provider credentials, client keys, accounting and trust | Home | `/data/overmind/cliproxy/home/home.db`, including WAL/SHM |
| Issued CPA certificate/key/CA cache | CPA | `/data/overmind/cliproxy/cpa/` |
| Matched recovery candidates | Human maintenance | `/backups/overmind/cliproxy/<name>/` |

Home advertises `cliproxy-home:8327` on the project's default network. Native
CPA/Home RESP uses mTLS directly over that network; an HTTP proxy cannot carry
it. The permanent Home service publishes 8327 on the LAN. Browser routing is
[#483](https://github.com/faviann/homelab-iac/issues/483); it must pass its LAN
panel/callback acceptance gate before live cutover is accepted.

Home's database is the runtime authority. CPA has no standalone config mount or
`-config` argument, downloaded-panel setting or old loopback callback port
publications. Redeployment does not overwrite Home settings or reimport OAuth.
Administration uses Home's embedded `/management.html` and native management
API with the imported management password/hash. There is no Authentik or
`MANAGEMENT_PASSWORD` override. Provider callbacks are completed through Home's
native panel workflow; keep callback URLs private.

The non-secret cluster file is mounted read-only. Home reads it at startup;
`.env.j2` hashes its exact content so Compose recreates Home and refreshes the
single-file bind after Ansible's atomic replacement. This is a startup input,
not an alternative runtime settings store. A changed cluster identity also
requires human review of existing carrier/certificate compatibility.

## Required carrier and private state

A human performs the existing
[native enrollment procedure](../../../docs/cliproxy-maintenance.md#native-node-enrollment-and-durable-trust)
and saves its returned carrier with `./vault.sh edit`. Never paste it into chat,
Git, command arguments or diagnostic output. `stack_vars.home_jwt | compose_env`
rejects missing or placeholder input and escapes Compose interpolation;
`${HOME_JWT:?…}` also rejects an empty environment before startup. An empty
carrier must never select standalone mode.

Keep `vault_overmind_cliproxy_api_key` and
`vault_overmind_cliproxy_management_key_hash` frozen for the recorded original
standalone revision's initial rollback. They are no longer rendered by this
runtime checkout. Home imports their values once and owns subsequent changes.
Do not rotate them during initial acceptance.

The stack `.env` is managed at 0600. Host vars enforce root:root 0700 on Home,
CPA and recovery directories; state stays outside stack synchronization and
managed-file parent normalization. Both binaries start with `umask 077` and
`exec`, preserving signal handling and private new files. Existing secret files
must also be 0600: umask does not repair old modes. Verify metadata without
reading contents. The legacy auth directory remains protected through the
initial standalone rollback window.

The CPA carrier retains its target/identity after enrollment. Its one-time
secret is consumed, so losing the cache cannot be repaired by replaying the
carrier. Use a matched restore or a fresh human-issued enrollment and a new
accepted recovery set.

## Initial cutover and acceptance

Follow the integrated
[permanent activation and acceptance procedure](../../../docs/cliproxy-maintenance.md#permanent-activation-and-initial-acceptance).
Use the recorded standalone revision for import and rollback; this checkout
cannot create the frozen legacy source. Live import, enrollment, vault edits,
provider handling, activation and consumer-secret changes are human work.
Repository PR completion does not assert production acceptance.

From the reviewed runtime checkout, ordinary activation uses:

```bash
./run.sh configure --limit overmind --stack cliproxy
```

Stack targeting narrows stack synchronization; host configuration can still
upgrade packages, reconcile Docker and reboot. `depends_on` orders startup and
`unless-stopped` allows native retries. Neither it nor `up -d` proves readiness:
require Home management authentication, the recorded healthy CPA identity and
an authenticated provider request before admitting clients. CPA may exit zero
on enrollment or Home-fetch failure. Only the permanent Home writer may run;
retain the stopped, unaliased bootstrap until the matched baseline is verified.

Acceptance covers both client entry paths, the original key, known models and
protocol behavior, every previously healthy provider, Home login and callback
workflow, restart, Home-outage failure, private modes and matched restoration.
On initial failure use the
[standalone rollback branch](../../../docs/cliproxy-maintenance.md#one-time-standalone-import-and-initial-rollback).
After baseline verification record **standalone rollback closed** before any
real consumer-key change. Later recovery restores matched Home state.

## Verification and assisted updates

```bash
./validate.sh
./validate.sh tests tests/regression/cliproxy_home_runtime_gate.py tests/regression/cliproxy_home_recovery_gate.py tests/regression/cliproxy_home_migration_gate.py
```

The explicit native gates need a local Docker daemon and the exact image pins.
They use synthetic credentials and an internal network with a fake provider;
they prove repository wiring, native protocols, enrollment/restart and matched
restore without contacting production or providers. Default handoff validation
has no Docker dependency. Browser interactions and real provider health remain
human acceptance gates.

Both images are pinned by literal tag and digest. Renovate holds this stack's
updates for assisted review. Before every pair/schema update take a matched
snapshot using the old Home pin, run these gates and follow
[snapshot, restore and assisted updates](../../../docs/cliproxy-maintenance.md#matched-recovery-and-assisted-updates).
There is no Home backup timer; the existing Postgres backup does not cover it.
