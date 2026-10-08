# Make sub2api the AI gateway pool of record

sub2api on the `overmind` LXC is the pool of record for the homelab's Claude,
Codex and Gemini subscription accounts. Clients reach it at
`https://gateway.ai.faviann.com`, which is the stable client address. The
hostname names the role, not the product, so clients keep it if the
implementation behind it changes. Decided in #526.

This narrows [ADR-0013](0013-share-one-ai-provider-credential-pool.md) rather
than replacing it. cliproxy (CPA + Home) stays deployed, but it is no longer the
pool of record and has no recorded consumers. No consumer is being moved in
either direction. ADR-0013 still describes how cliproxy itself is run.

The LAN remains the trust boundary. The router carries `local-ip-restriction`,
and the direct port on `overmind` is reachable on the flat bridge, the same
acceptance ADR-0013 makes for CPA.

## Accepted trade-offs

- The JWT secret and the database password are readable by the docker uid in
  every LXC through the shared volume. With the JWT secret, a process can mint
  admin sessions.
- The sub2api Postgres has no backup. Losing it means re-adding the accounts.

Hardening both is deferred behind separate secret-store and bootstrap work.
The [stack README](../../stacks/overmind/sub2api/README.md#state) describes
the exposures in detail.
