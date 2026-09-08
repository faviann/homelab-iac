# Lobu Control Plane

Read before touching the `lobu` LXC, the `lobu` stack, or the
`https://lobu.faviann.com` Traefik router.

Lobu's control plane is self-hosted here so ChatGPT can dispatch governed work
to the workstation's `lobu daemon` without depending on Lobu Cloud:

```text
ChatGPT -> https://lobu.faviann.com/mcp -> Lobu control plane (lobu LXC)
        -> device queue / policy / approvals
        -> workstation lobu daemon -> local tooling
```

The workstation daemon polls outward. It is never exposed through Traefik.

## Topology

| Piece | Where |
| --- | --- |
| LXC | `lobu`, vmid 308, `tier_medium` + `cap_docker`, 16 GB root disk |
| Stack | `stacks/lobu/lobu/` — `pgvector/pgvector:pg18-trixie` + `ghcr.io/lobu-ai/lobu-app:19.2.0`, both digest-pinned |
| Durable state | `./appdata/postgres` and `./appdata/workspaces`, i.e. `/conf/docker/stacks/lobu/appdata/...` |
| Public origin | `https://lobu.faviann.com` → `http://lobu.faviann.vms:8787` |
| Admin UI | LAN only: `http://lobu.faviann.vms:8787` |

`/conf/docker` is a read-write per-host subpath of the shared 256 GB volume, so
stack-relative `appdata` survives LXC recreation. The 16 GB root disk holds
images and the container runtime, not application data.

pgvector is required for the **baseline** schema migration, not only for
optional memory features: the schema declares non-nullable vector columns, so a
stock `postgres` image fails to migrate at all.

## Licensing

The Lobu repository root is Apache-2.0, but the server component this deployment
runs is **BUSL-1.1**. Its Additional Use Grant permits production use except
offering Lobu to third parties as a hosted service, and each version converts to
Apache-2.0 four years after release. A private homelab deployment is inside the
grant. Do not expose this instance as a service to other people.

## Secrets

Three vault variables, bound into the stack through
`lxc_docker_env_stack_vars.lobu` in `inventory/host_vars/lobu.yml`:

| Variable | Shape | Notes |
| --- | --- | --- |
| `vault_lobu_encryption_key` | base64 32 bytes | **Not rotatable** — see below |
| `vault_lobu_better_auth_secret` | base64 32 bytes | Rotating invalidates sessions only |
| `vault_lobu_postgres_password` | hex | URL-safe because it is embedded in `DATABASE_URL` |

The human account password is set through the UI and stays outside Ansible.

### ENCRYPTION_KEY is long-lived state, not a rotatable secret

`ENCRYPTION_KEY` encrypts every credential Lobu stores in Postgres — provider
keys, connection tokens, OAuth secrets. Replacing it does not re-encrypt
anything; it makes the existing ciphertext permanently unreadable. Treat it the
way you treat the database itself. It is not part of routine maintenance, and
recovering from a lost key means re-entering every stored credential by hand.

Rotating `vault_lobu_better_auth_secret` or `vault_lobu_postgres_password` is
ordinary work: change the vault value, `./run.sh --limit lobu`, and for the
database password also `ALTER ROLE lobu PASSWORD ...` inside `lobu-postgres`
before the app restarts, or recreate the volume.

## Bootstrap

1. **DNS.** `lobu.faviann.vms` must resolve on the LAN (router-side record for
   MAC `BC:24:11:14:5B:9C`), and `lobu.faviann.com` must resolve publicly to the
   edge. `*.faviann.com` is already covered by the existing wildcard SAN, so no
   certificate change is needed.
2. **Deploy.** `./run.sh --limit lobu`. The image entrypoint runs its own
   migrations against `DATABASE_URL`, with a connectivity preflight that refuses
   to migrate an unreachable database under `NODE_ENV=production`.
3. **Create the one human account** in the admin UI at
   `http://lobu.faviann.vms:8787`. Do this on the LAN, before or after the
   public router exists — signup is not reachable through the public origin.
4. **Confirm the lockout**: a second signup must fail with
   `SIGN_UP_DISABLED_IN_SINGLE_USER_MODE`. `LOBU_SINGLE_USER=1` counts real
   humans only.
5. **Point the workstation at this origin** — owned by `faviann/dotfiles#126`,
   not by this repository. See "Workstation boundary" below.
6. **Add the connector in ChatGPT** against `https://lobu.faviann.com/mcp`.

## Health and status

```bash
ssh -l faviann -i ~/.ansible/ssh/proxmox_lxc lobu.faviann.vms
docker ps --format '{{.Names}}\t{{.Status}}'          # both must be healthy
docker logs --tail 50 lobu-app                        # migrations + boot
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/health
```

From anywhere, against the public origin:

```bash
curl -s https://lobu.faviann.com/.well-known/oauth-protected-resource
curl -s https://lobu.faviann.com/.well-known/oauth-authorization-server
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://lobu.faviann.com/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'   # must be 401
```

`resource` and `authorization_servers` in the protected-resource document come
from `PUBLIC_GATEWAY_URL`; the authorization-server document reflects the
request host. If they disagree, MCP requests fail as an opaque origin-trust
rejection rather than as a routing error — check `PUBLIC_GATEWAY_URL` first.

## Public exposure

The Traefik router `lobu` in
`stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml`
carries **no ForwardAuth and no Authentik middleware**. ChatGPT's connector
onboarding needs unauthenticated dynamic client registration
(`POST /oauth/register`, IP rate-limited by Lobu), and Lobu is its own OAuth 2.1
authorization server; an Authentik boundary in front of the protocol endpoints
would break both.

The public surface is instead an explicit path allowlist, observed from the real
flows: MCP; OAuth protected-resource discovery (root and `/mcp` transport forms,
plus the `/.well-known/oauth-protected-resource/mcp` sub-path that Lobu
advertises in `WWW-Authenticate`); authorization-server and OpenID discovery;
`/oauth/*`; `/auth.md`; the sign-in and consent browser surface (`/auth/login`,
`/oauth/consent`, `/assets/*`, favicons, `/api/auth/*`); `/api/workers/*` and
`/api/me/devices*` for the daemon; `/api/health`; and `/legal` + `/logo.png` for
ChatGPT's connector validation.

The admin SPA at `/` and the `/api/<org>/*` workspace API are deliberately not
allowlisted. That is the separation the issue asked for: the machine-facing
protocol surface is public, the human admin surface is LAN-only. Anything not
matched is a 404 at the edge.

`/api/auth/sign-up*` is additionally routed to the `noop` service at a higher
priority, so the public origin answers 503 there even though `LOBU_SINGLE_USER`
already closes signup in the application.

**If a flow breaks after an upgrade**, check the edge before the app: a new path
that Lobu started using will show up as a 404 for `lobu.faviann.com` in
`/logs/traefik-access.log` on the `portal` LXC. Add it to the allowlist rather
than widening the rule to a bare prefix.

## Upgrades

`stack.yaml` tracks images (`postgres` on `pg18`, `lobu` on `stable`). To move
the app version:

1. Resolve the new tag to a digest and update `compose.yaml` with both.
2. `./validate.sh stack stacks/lobu/lobu` and `./validate.sh`.
3. `./run.sh --limit lobu -e stack_filter=lobu`.
4. Watch `docker logs -f lobu-app` through the migration block; the entrypoint
   fails fast and loudly rather than migrating partially.
5. Re-run the health checks above, then re-check the OAuth discovery documents —
   an upgrade that adds a path needs an allowlist entry.

Rolling back an app version after a migration has applied is not supported by
the upstream migration runner. Snapshot the LXC before a major bump.

## Recovery

Durable state is exactly two directories under
`/conf/docker/stacks/lobu/appdata/` plus the three vault values.

- **Container recreation**: `docker compose down && docker compose up -d` in
  `/conf/docker/stacks/lobu` preserves everything.
- **LXC recreation**: `appdata` lives on the shared volume's per-host subpath,
  not the root disk, so it survives. Re-run `./run.sh --limit lobu`.
- **Losing the database** loses the workspace, the human account, every
  registered OAuth client, and the device registration. ChatGPT's connector must
  be re-added and the workstation must re-register, which creates a *new*
  device. There is no backup mechanism here on purpose — see below.

Backups are out of scope for this milestone. Do not duplicate or generalize the
Overmind Postgres backup mechanism; future stack-level backup infrastructure is
expected to cover persistent `appdata` generically.

## Workstation boundary

This repository owns the origin and publishes it as inventory data
(`lobu_public_gateway_url`). It does **not** write into `~/.config/lobu`. That
directory is persisted device identity: writing to it from configuration
management is how a duplicate device registration happens.

- `faviann/homelab-iac#270` (closed) persists `~/.config/lobu` across intentional
  workstation LXC rebuilds. As long as that state is intact, restarting or
  rebuilding the workstation reuses the same device.
- `faviann/dotfiles#112` installs the Lobu CLI and supervises `lobu daemon`.
- `faviann/dotfiles#126` points that daemon at `https://lobu.faviann.com` with an
  explicit non-cloud context. Until it lands, the daemon still targets Lobu
  Cloud.

Do not run `lobu login` against Lobu Cloud as part of this rollout. Register the
device against the self-hosted origin with an explicit context
(`lobu context ...`), so the daemon cannot silently fall back to the hosted
default.

## Deliberate non-configuration

| Setting | State | Why |
| --- | --- | --- |
| `AUTH_COOKIE_DOMAIN` | unset | Keeps orgs on paths under one hostname — no wildcard DNS or extra certificate |
| `WORKER_ALLOWED_DOMAINS` | unset | Server-side worker egress stays deny-all |
| provider API keys | none | The gateway boots with zero inference providers; provider resolution no-ops at completion time |
| `LOBU_RUN_OWNS_DB` | unset | Belongs to `lobu run` local-install mode, not container deployments |
| `lobu.config.ts` | absent | Not read at gateway boot |
