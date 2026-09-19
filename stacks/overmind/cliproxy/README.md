# cliproxy

Shared AI provider proxy. Homelab agents point at one endpoint and CLIProxyAPI
presents Claude and Codex subscription accounts as OpenAI/Anthropic-compatible
APIs, load-balancing across the accounts in its pool.

## Settings live in Git, accounts live in the panel

Read this before changing anything.

| Thing | Owner | Where | In Git? |
| --- | --- | --- | --- |
| Port, `auth-dir`, client key, management key, logging | Ansible | `appdata/config/config.yaml.j2` | yes (secrets from vault) |
| Provider OAuth accounts | the service | `appdata/auth/*.json` | no |

`config.yaml` is rendered on every deploy and mounted read-only. Settings you
change in the management panel do not persist. The panel reports a write failure
rather than accepting the edit and silently losing it on the next `./run.sh`. To
change a setting, edit the template and redeploy.

### Why the config directory is mounted, not the file

Ansible renders by atomic rename, which gives the file a new inode. A
single-file bind mount stays attached to the old inode, so the container would
keep reading the previous config forever while the host file looked current.
Mounting the directory and passing `-config /conf/config.yaml` makes the
container resolve the name on each open.

That alone is not enough. Compose cannot see inside a bind mount, so a changed
config produces no reason to recreate the container, and the app does not
hot-reload on atomic replacement (tested: a key added to the config was still
rejected, with no reload entry in the log). `.env.j2` therefore renders
`CLIPROXY_CONFIG_FINGERPRINT`, a hash of the rendered config, into the service
environment. The app never reads it. Its only job is to change when the config
changes, so Compose recreates the container and the new config takes effect.

Without it, rotating `vault_overmind_cliproxy_api_key` would report success
while the running proxy kept accepting the old key and rejecting the new one.

### The management panel is downloaded, not shipped

The panel asset is not part of the pinned image. Upstream fetches
`management.html` from GitHub on first access and caches it under
`MANAGEMENT_STATIC_PATH`, which this stack points at
`appdata/auth/static/`. Left at its default it would land in the config
directory, which is mounted read-only, and the download fails with
`mkdir /conf/static: read-only file system` while `/management.html`
returns 404.

`disable-auto-update-panel: true` only stops the periodic background refresh.
It does not pin the panel to the image, and a missing panel is still fetched on
next access. Deleting `appdata/auth/static/` is therefore a safe way to force a
fresh panel download.

After any deploy that changes the config path, the mount layout, or the image,
check the panel actually loads. No offline test covers it, because the failure
only appears at runtime:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://cliproxy.local.faviann.com/management.html
```

Adding, re-authenticating, and removing provider accounts is the exception: that
is entirely a panel operation, writes only to `auth-dir`, and Ansible never
touches those files. No commit, no vault edit, no redeploy.

`auth-dir` is set explicitly even though it is redundant today. The image runs
as root with `HOME=/root`, so the default `~/.cli-proxy-api` already resolves to
the bind mount. Stating the path keeps the mount and the config in visible
agreement, and the contract survives a future change to the container user or
`HOME` rather than silently relocating the credential store.

## Where it runs and how clients reach it

Runs on the `overmind` LXC. Clients use `https://cliproxy.local.faviann.com`,
routed by the static `cliproxy` router in
`stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml`
(overmind has `traefik_kop_enabled: false`, so there is no label discovery) and
restricted to the LAN by `local-ip-restriction`.

Port 8317 is also directly reachable at `overmind.faviann.vms:8317` over plain
HTTP, because Traefik runs on another LXC and has to reach it. The LAN is the
trust boundary — see
[ADR-0013](../../../docs/adr/0013-share-one-ai-provider-credential-pool.md).

Clients authenticate with the key in `vault_overmind_cliproxy_api_key`.

## Vault entries

Both must exist before the first deploy. Generate them yourself; never paste a
secret into a chat, a commit, or an issue.

```bash
# client API key
openssl rand -hex 32

# management password, then its bcrypt hash — store the HASH in vault and
# log into the panel with the plaintext
uv run --with bcrypt --no-project python -c \
  'import bcrypt,getpass;print(bcrypt.hashpw(getpass.getpass().encode(),bcrypt.gensalt()).decode())'
```

```bash
./vault.sh edit   # add vault_overmind_cliproxy_api_key
                  # and  vault_overmind_cliproxy_management_key_hash
```

The hash, not the plaintext, is stored because the server rewrites a plaintext
`secret-key` into `config.yaml` at startup — which would fight the read-only
mount and make every deploy report `changed`.

## Deploy

Two hosts, two runs. The stack and the Traefik router live on different LXCs.

```bash
./run.sh --limit overmind > /tmp/cliproxy-overmind.log 2>&1
./run.sh --limit portal   > /tmp/cliproxy-portal.log 2>&1
```

`cliproxy.local.faviann.com` must resolve to the Traefik host. DNS is not
managed in this repo.

## Authenticating a provider account

1. Open `https://cliproxy.local.faviann.com/management.html` from a LAN machine
2. Log in with the management password (the plaintext behind the stored hash)
3. Start the login for Claude or Codex and complete it at the provider

Step 3 is the fragile part. Provider OAuth redirect URIs are hardcoded loopback
addresses (Claude `localhost:54545`, Codex `localhost:1455`), and your browser
is not on the container. Two paths, in order:

**Paste the callback URL (reliable).** The provider redirects your browser to a
`http://localhost:…` address that fails to load. Copy that whole failed URL out
of the address bar and paste it into the panel's callback submission field. The
panel extracts the code and completes the exchange.

**Tunnel (last resort).** If the panel cannot accept the callback at all:

```bash
ssh -N -L 1455:localhost:1455 -L 54545:localhost:54545 -L 51121:localhost:51121 \
    -l root -i ~/.ansible/ssh/proxmox_lxc overmind
```

The compose file publishes those ports on the LXC's loopback only, so the
tunnel reaches them and the network does not. Retry the login with the tunnel
up, then close it.

Credentials land in `./appdata/auth/` on the shared volume and survive container
and LXC recreation. Losing them costs a re-login, not data — there is no backup
timer and none is warranted.

## Upgrades

The image is pinned by tag and digest in `compose.yaml`. Upstream releases
roughly daily and publishes no minor-series tag, so there is nothing safe to
float to; bump the pin deliberately. Verify the management login still works
after a bump — management key validation has regressed upstream before.

```bash
./validate.sh stack stacks/overmind/cliproxy
```
