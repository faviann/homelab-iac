# Share one AI provider credential pool behind a LAN-only proxy

CPA on the `overmind` LXC serves every homelab agent from one shared pool of
Claude and Codex provider credentials. The
[accepted Home integration plan](https://github.com/faviann/homelab-iac/issues/476#issuecomment-5985413171)
keeps that pool while making SQLite-backed Home the authority for runtime
configuration, provider refresh state, client keys, accounting and cluster
trust. Ansible owns topology, image pins, private directories and startup
inputs. There is no user tenancy, per-consumer provider pool, quota or billing.

The original standalone deployment used one shared client key. That rationale
is superseded by one named native Home key per actual consumer: independent
attribution and revocation no longer require separate provider accounts. Keys
are unowned, with no channel or model-group restrictions, so all consumers use
the same provider account pool. The imported record is named `legacy-shared`
without changing its value or stable ID. Unknown and unmigrated clients retain
that key until a separate explicit retirement decision.

The [non-secret consumer inventory](../../stacks/overmind/cliproxy/README.md#consumer-identities-and-inventory)
maps actual consumer names to stable Home IDs, credential-source owners and
observed migration states. Native usage can display `api-key-ID` instead of
the friendly name; verify attribution by ID. Individual native key operations
avoid replacing unrelated consumers' keys. Revocation rejects new requests;
accepted streams and retained Responses WebSocket selections can survive it.
Emergency CPA restart interrupts every session under the
[bounded maintenance procedure](../cliproxy-maintenance.md#emergency-cpa-restart).

Initial migration does not change any consumer address or key. Real key rollout
changes one actual consumer at a time, following human acceptance and a
verified matched recovery baseline, after explicitly closing the initial
standalone rollback window. Broodling retains its fixed gateway/model/tool/JSON
contract and later changes only its separately owned gateway key; its deployment
remains [#353](https://github.com/faviann/homelab-iac/issues/353).
Recovery is manual from matched Home snapshot and
CPA cache sets; see
[the recovery contract](../cliproxy-maintenance.md#matched-recovery-and-assisted-updates).

The LAN remains the trust boundary. Traefik publishes the client service as
`https://cliproxy.local.faviann.com` restricted to `local-ip-restriction`.
Traefik runs on the `portal` LXC and reaches CPA over the network, so port 8317
is directly reachable at `overmind.faviann.vms:8317` over plain HTTP on the LAN.
The router narrows the convenient path. The LXCs share an unfirewalled bridge,
so an attacker positioned to abuse the direct port can already reach other
services on it.

Home administration uses its native embedded panel and management API at
`https://cliproxy-home.local.faviann.com/management.html`, with the imported
management bcrypt hash/password and the same `local-ip-restriction` policy.
The whole Home HTTP surface, including unused user-registration endpoints,
stays inside this LAN boundary. Its published plain HTTP listener at
`overmind.faviann.vms:8327` is accepted on the same flat bridge as CPA's client
port. The portal allowlist does not restrict either direct listener.

The separate Home port removes the old shared-client/management-port rationale
for avoiding edge authentication. The approved migration chooses native Home
administration over Authentik forwarding or a custom authentication layer, with
no password override, public administration or path authentication exceptions.
CPA Home mode no longer serves its old panel. Home embeds the panel and handles
provider callback paste itself; see
[the administration acceptance procedure](../cliproxy-maintenance.md#lan-administration-and-acceptance).
Native CPA/Home RESP travels directly over the Compose default network with
mTLS; the ordinary HTTP browser route cannot transport it. Runtime authority
and durable identity follow
[the native enrollment contract](../cliproxy-maintenance.md#native-node-enrollment-and-durable-trust).

The flat-bridge acceptance remains provisional and is expected to be retired
by Proxmox host-level segmentation restricting client and management origins.
An in-guest rule modelled on `config/lxc_origin_firewall` could close the gap
sooner, but is not built here: guest compromise disarms guest-enforced rules,
and host-level segmentation supersedes that approach.
