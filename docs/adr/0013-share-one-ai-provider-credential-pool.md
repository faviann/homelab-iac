# Share one AI provider credential pool behind a LAN-only proxy

CPA on the `overmind` LXC serves every homelab agent from one shared pool of
Claude and Codex provider credentials. The
[accepted Home integration plan](https://github.com/faviann/homelab-iac/issues/476#issuecomment-5985413171)
keeps that pool while making SQLite-backed Home the authority for runtime
configuration, provider refresh state, client keys, accounting and cluster
trust. Ansible owns topology, image pins, private directories and startup
inputs. There is no user tenancy, per-consumer provider pool, quota or billing.

The original standalone deployment used one shared client key. Home enables
independently named, attributable and revocable consumer keys; the legacy key
continues serving unmigrated clients. Initial migration does not change any
consumer address or key. Real key rollout follows human acceptance and a
verified matched recovery baseline, after explicitly closing the initial
standalone rollback window. Recovery is manual from matched Home snapshot and
CPA cache sets; see
[the recovery contract](../cliproxy-maintenance.md#matched-recovery-and-assisted-updates).

The LAN remains the trust boundary. Traefik publishes the client service as
`https://cliproxy.local.faviann.com` restricted to `local-ip-restriction`.
Traefik runs on the `portal` LXC and reaches CPA over the network, so port 8317
is directly reachable at `overmind.faviann.vms:8317` over plain HTTP on the LAN.
The router narrows the convenient path. The LXCs share an unfirewalled bridge,
so an attacker positioned to abuse the direct port can already reach other
services on it.

Home administration uses its native embedded panel and management API with the
imported management bcrypt hash/password. Its separate port 8327 removes the
old shared-client/management-port rationale for avoiding edge authentication.
The approved migration still chooses native Home authentication and the existing
LAN restriction for its later browser route, with no Authentik forwarding,
password override, public administration or custom authentication layer. Native
CPA/Home RESP travels directly over the Compose default network with mTLS;
the ordinary HTTP browser route cannot transport it.

The flat-bridge acceptance remains provisional and is expected to be retired
by Proxmox host-level segmentation restricting client and management origins.
An in-guest rule modelled on `config/lxc_origin_firewall` could close the gap
sooner, but is not built here: guest compromise disarms guest-enforced rules,
and host-level segmentation supersedes that approach.
