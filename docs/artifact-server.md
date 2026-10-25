# Artifact Server

Read before touching the `agent-services` LXC, the `artifact-server` stack, or
its Authentik client, and before an agent publishes an artifact.

[Artifact Server](https://github.com/plannotator/artifact-server) stores
finished files and directory trees that agents publish, serves each version at
its own URL, and lets a person comment on them. It runs in compact mode on the
`agent-services` LXC (VMID 312) from `stacks/agent-services/artifact-server/`.

| Item | Value |
| --- | --- |
| App origin | `https://artifact-server.public.faviann.com` |
| Content hosts | `<36 hex>.faviannusercontent.com` (a version) and `review-<56 hex>.faviannusercontent.com` (a review preview) |
| Data | `appdata/artifact-server/data` in the stack folder: SQLite, blobs, `installation.json`, and `secrets/api-token`, the server's own credential: never copy or print it |
| Browser login | Authentik OIDC client `artifact-server`, `admins` only |
| Agent login | API keys an administrator issues |

Both routers reach portal's Traefik through traefik-kop labels. The app uses
the existing `*.public.faviann.com` certificate, and the content router uses
the `*.faviannusercontent.com` certificate from portal's `traefik.yaml`. There
is no forwardAuth. The app runs its own login and serves public artifacts to
anyone.

Authentik's issuer ends in a slash, and artifact-server v0.1.2 checks the ID
token's `iss` against the issuer with that slash stripped, so login fails. The
`Artifact Server Issuer` scope mapping in `oidc-apps.yaml` sets `iss` without
the slash for this provider only. It relies on Authentik letting a mapping
overwrite standard claims, which Authentik issue 25235 proposes to block, so
login breaks if an upgrade blocks it. Remove the mapping once an
artifact-server release accepts the trailing slash.

## Content domain

Artifact JavaScript runs with full privileges in its own origin, so the
server refuses to start unless the content domain has a different registrable
domain from the app. Content on `faviannusercontent.com` is cross-site to the
app and to every `*.faviann.com` host. It cannot set cookies for
`.faviann.com`, and its scripted requests to those hosts carry no `Lax` or
`Strict` cookies, such as Authentik's session. Each version also has its own origin, so
artifacts cannot read each other's localStorage, sessionStorage, IndexedDB, or
host-only cookies. A cookie an artifact sets with
`Domain=faviannusercontent.com` does reach every other artifact, because the
domain is not on the Public Suffix List. The server's own content cookie uses
the `__Host-` prefix and cannot be shared that way. Never serve artifact
content under `faviann.com`.

## First deploy

1. Add a Firewalla DHCP reservation for the MAC in
   `inventory/host_vars/agent-services.yml`, so `agent-services.faviann.vms`
   resolves.
2. In Cloudflare, add the `faviannusercontent.com` zone to the zone resources
   of portal's DNS API token (Zone Read and DNS Edit), and add a DNS-only
   `*.faviannusercontent.com` CNAME to the same target as `*.faviann.com`.
3. Add `vault_agent_services_artifact_server_oidc_client_secret` to the vault.
4. Deploy Traefik, Authentik, then the host. The Traefik deploy restarts
   Traefik, which briefly drops every route on portal:

   ```bash
   ./run.sh --limit portal --stack traefik3
   ./run.sh --limit auth --stack auth
   ./run.sh --limit agent-services
   ```

The `init` service initializes the data directory with `faviann@gmail.com` as
the bootstrap administrator, who is admitted on first login. It does nothing
once the directory exists, so changing the email later has no effect. Add
other people at `/review/settings/members`.

## Agent workflow

**API key.** An administrator issues a key at `/review/settings/api-keys`, with
`artifact:create`, `artifact:read`, `content-session:issue`, `comment:write`,
and `agent:connect`. Store it outside the repo, for example in
`~/.config/artifact-server/api-key` with mode `0600`. MCP clients use the same
key as a bearer token on `https://artifact-server.public.faviann.com/mcp`.
Upstream v0.1.2 cannot finish a publish with an OAuth MCP token.

**Publish.** Download `artifact-server-0.1.2-node.tar.gz` from the upstream
v0.1.2 release, check it against `SHA256SUMS`, extract it, and run its CLI with
Node 24.12 or later. Artifacts are private unless `--public` is passed at
creation.

```bash
node <extracted>/dist/cli/main.js publish ./dist \
  --server https://artifact-server.public.faviann.com \
  --token-file ~/.config/artifact-server/api-key
```

Publish a new version with `--artifact <id> --expected-version <version-id>`.

**Render check.** After publishing, render the artifact in headless Chromium.
The script prints JSON with the main response status, console errors, page
errors, and failed requests, writes a full-page PNG, and exits 1 on any console
or page error or a non-2xx response. With `--token-file`, a private artifact
opens through a content session.

```bash
nix shell nixpkgs#chromium -c npx -y -p playwright@1.64.1 \
  node scripts/artifact-render-check.mjs <artifact-id> \
  --token-file ~/.config/artifact-server/api-key --out /tmp/render.png
```

The workstation lacks the system libraries for Playwright's own browser, so the
command takes Chromium from nixpkgs. It also has no fonts, so text is invisible
in the screenshot unless `FONTCONFIG_FILE` points at a fontconfig file that lists
a font directory. The JSON checks do not depend on fonts.

**Comments.** Read them over MCP with `comment_list`, passing
`dispatched: "include"`, because the default hides threads already sent to an
agent. Answer with `comment_reply` and close with `comment_resolve`.

**Visibility.** Change it over MCP with `artifact_set_visibility`, or with
`PATCH /api/v1/artifacts/<id>/access` with an `Idempotency-Key` header and a
body of `accessSetting` (`public_link` or `account_required`) and
`expectedCurrentVersionId`. The CLI sets visibility only at creation.
