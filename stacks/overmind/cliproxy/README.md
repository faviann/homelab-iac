# cliproxy

One shared Claude/Codex provider pool on `overmind`, served by CPA v7.3.8 and
managed by SQLite-backed Home v1.1.0. The existing project, CPA container and
client addresses stay the same:

- `https://cliproxy.local.faviann.com`, through portal Traefik's existing LAN
  `local-ip-restriction` route
- `http://overmind.faviann.vms:8317`, directly on the LAN

Broodling keeps its fixed gateway `/v1` URL, `gpt-5.6-sol`, Chat Completions,
tools and JSON-object contract. The imported legacy client key keeps serving
until consumers move to named keys.

Enrollment, recovery, assisted updates and the native Docker gates are in
[the maintenance procedure](../../../docs/cliproxy-maintenance.md).

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
it. The permanent Home service publishes 8327 on the LAN. Administration uses
`https://cliproxy-home.local.faviann.com/management.html` through portal's
existing TLS and `local-ip-restriction` policy.

Home's database is the runtime authority. CPA has no standalone config mount or
`-config` argument, downloaded-panel setting or old loopback callback port
publications. Redeployment does not overwrite Home settings or reimport OAuth.
Home's embedded panel and management API use the imported management
password/hash. The old client hostname's `/management.html` now returns an
expected 404 in Home mode. Follow
[LAN administration and acceptance](../../../docs/cliproxy-maintenance.md#lan-administration-and-acceptance)
for login and native callback paste; the old standalone CPA callback tunnels
and mappings are retired.

The non-secret cluster file is mounted read-only. Home reads it at startup;
`.env.j2` hashes its exact content so Compose recreates Home and refreshes the
single-file bind after Ansible's atomic replacement. This is a startup input,
not an alternative runtime settings store. A changed cluster identity also
requires human review of existing carrier/certificate compatibility.

## Required carrier and private state

A human performs the
[native enrollment procedure](../../../docs/cliproxy-maintenance.md#native-node-enrollment-and-durable-trust)
and saves its returned carrier in the vault. Never paste it into chat,
Git, command arguments or diagnostic output. `stack_vars.home_jwt | compose_env`
rejects missing or placeholder input and escapes Compose interpolation;
`${HOME_JWT:?…}` also rejects an empty environment before startup. An empty
carrier must never select standalone mode.

The stack `.env` is managed at 0600. Host vars enforce root:root 0700 on Home,
CPA and recovery directories; state stays outside stack synchronization and
managed-file parent normalization. Both binaries start with `umask 077` and
`exec`, preserving signal handling and private new files. Umask does not
repair existing files; they must already be 0600.

The carrier's one-time secret is consumed at first connection, so replaying it
cannot recreate a lost CPA cache. Recover with a matched restore or a fresh
human-issued enrollment.

## Consumer identities and inventory

Home's native key records give each actual consumer an independently named,
attributable and revocable credential over the same provider account pool.
Keep keys unowned (`user_id: null`) with empty `channels` and `model_groups`.
Label the imported key `legacy-shared` without changing its value or stable
Home ID; unknown and unmigrated consumers keep using it until a separate
explicit retirement decision.

Follow the [human identity rollout](../../../docs/cliproxy-maintenance.md#consumer-identity-rollout)
after the verified matched recovery baseline.

| Consumer name | Stable Home key ID | Credential-source owner | Migration status |
| --- | --- | --- | --- |

Use the actual Home numeric ID, rather than a display name or list index. For
each known consumer, record the responsible owner and its approved secret-store
or binding reference, never the key value. Record the observed status: `legacy`,
`prepared` (key created, consumer unchanged), `migrated` (behavior and ID
attribution accepted), or `revoked`, with a date and non-secret evidence
reference. Multiple legacy consumers may reference the same legacy ID. Retain
revoked/deleted rows and the shared record so recovery can reapply later
revocations. Update this table after each accepted administrative change; it
does not reconcile Home state or provision secrets.

### Broodling gateway contract

Broodling requires `GATEWAY_BASE_URL=https://cliproxy.local.faviann.com/v1`,
`gpt-5.6-sol`, Chat Completions, tools and JSON-object output. When its
operator migrates it, only its separately owned gateway key changes. Its
deployment is owned by [#353](https://github.com/faviann/homelab-iac/issues/353).

## Deploy

```bash
./run.sh configure --limit overmind --stack cliproxy
```

Startup is not readiness: CPA can exit 0 on an enrollment or Home-fetch
failure. Judge a deploy by the connected CPA identity in Home and an
authenticated provider request. Both images are pinned by tag and digest, and
Renovate holds their updates for
[assisted review](../../../docs/cliproxy-maintenance.md#assisted-updates).
There is no Home backup timer; the Postgres backup does not cover it.
