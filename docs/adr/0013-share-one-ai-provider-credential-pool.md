# Share one AI provider credential pool behind a LAN-only proxy

CLIProxyAPI on the `overmind` LXC holds every homelab agent's access to Claude
and Codex as a single pool of OAuth subscription credentials, and every agent
authenticates to it with one shared client API key. This deliberately gives up
per-agent attribution, per-agent quota, and per-agent revocation: any agent that
can reach the proxy can spend any account in the pool, and revoking one
consumer means rotating the key for all of them. The alternative — a credential
set per consumer — was rejected because CLIProxyAPI offers no per-key quota or
routing, so the extra keys would buy independent revocation and nothing else,
against a fleet that is administered by one person.

The LAN is the trust boundary. Traefik publishes the service as
`https://cliproxy.local.faviann.com` restricted to the `local-ip-restriction`
allowlist, but Traefik runs on the `portal` LXC and therefore reaches the proxy
over the network, so port 8317 is necessarily reachable directly at
`overmind.faviann.vms:8317` over plain HTTP by anything already on the LAN. The
router narrows the convenient path, not the only one. This is accepted because
the LXCs already share one unfirewalled bridge, so an attacker positioned to
abuse the direct port can already reach every other service on it. Fronting the
proxy with Authentik ForwardAuth was rejected separately: the management panel
and the agent API share a port, so edge authentication that works for a browser
breaks every non-interactive client, and a path-scoped exception list would fail
open and unnoticed as the panel grows new paths across releases.

That acceptance is provisional. It holds only while the bridge is flat, and is
expected to be retired by host-level segmentation: Proxmox firewall rules
declared per guest alongside the rest of its provisioning, restricting 8317 to
the Traefik origin. An in-guest nftables rule modelled on
`config/lxc_origin_firewall` would close the same gap sooner, but it is
deliberately not built here, because rules enforced inside the guest are
disarmed by whatever compromises the guest, and because host-level segmentation
supersedes that role rather than extending it.
