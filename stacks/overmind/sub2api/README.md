# sub2api

Trial of [sub2api](https://github.com/Wei-Shaw/sub2api) as a central pool for
Claude, Codex, and Gemini subscription OAuth accounts. It overlaps with
`cliproxy` on the same LXC, which stays the pool of record
([ADR-0013](../../../docs/adr/0013-share-one-ai-provider-credential-pool.md))
until this trial decides otherwise.

Portability tier: portable app stack.

## Where it runs and how clients reach it

Runs on `overmind`. The UI and API are at `https://gateway.ai.faviann.com`,
routed by the static `sub2api` router in
`stacks/portal/traefik3/appdata/traefik3/config/conf.d/externalservice.yaml`
and restricted to the LAN by `local-ip-restriction`. Port 8318 is also directly
reachable at `overmind.faviann.vms:8318` over plain HTTP, because Traefik runs
on another LXC. The LAN is the trust boundary.

The hostname names the role, not the product, so clients keep their base URL
if the gateway implementation changes. The `*.ai.faviann.com` tier is
described in `stacks/README.md` § Domains.

`RUN_MODE=simple` hides the SaaS billing and balance features, which are
irrelevant for a single owner.

## State

| Thing | Where |
| --- | --- |
| Accounts, OAuth tokens, API keys, users | Postgres, `appdata/postgres/` |
| Scheduling and session cache | Redis, `appdata/redis/` |
| Generated `config.yaml`, logs | `appdata/data/` |

All three live under `appdata/` on the shared volume, which is mounted at
`/shared` in every LXC. That exposure is accepted for this trial:

- `.env` is 0600 (`x-managed-files`), but it is owned by the docker uid, as is
  `appdata/data/config.yaml`, which holds the JWT secret and the database
  password. The docker uid is the same in every LXC, so a process running as
  the docker user anywhere in the fleet can read both. With the JWT secret it
  can mint admin sessions and reach the account tokens through the API.
- Root in any LXC can read everything, because every LXC shares the same
  idmap.

Moving the three directories under a root-owned 0700 `/data/overmind/sub2api`,
as `cliproxy` does with `/data/overmind/cliproxy`, closes the first gap. There
is no backup; losing the database costs re-adding the accounts.

## Vault entries

All four must exist before the first deploy. Generate them yourself; never
paste a secret into a chat, a commit, or an issue.

```bash
openssl rand -hex 32   # once per key
./vault.sh edit        # vault_overmind_sub2api_postgres_password
                       # vault_overmind_sub2api_jwt_secret
                       # vault_overmind_sub2api_totp_encryption_key
                       # vault_overmind_sub2api_oidc_client_secret
```

`JWT_SECRET` and `TOTP_ENCRYPTION_KEY` must stay fixed. Upstream regenerates
either one on every start when it is empty, which logs everyone out and breaks
enrolled 2FA.

The Postgres password takes effect only when the database is first
initialized. Rotating it in the vault afterwards does not change the running
database; change it in Postgres too.

## First login

There is no admin password in the vault. On the first start against an empty
database, sub2api creates `admin@sub2api.local` with a generated password and
prints it in the container log. Reading it is a human step: the output is a
secret, so an agent must not run this or relay its output.

```bash
ssh -l root -i ~/.ansible/ssh/proxmox_lxc overmind 'docker logs sub2api 2>&1 | grep -i password'
```

Log in, then change it from the profile page. The generated password stays in
the log until the container is recreated, and is useless once changed. Later
starts skip admin creation because an admin exists.

## Authentik login

The login page offers Authentik through the `sub2api-local` OAuth2 provider,
declared in `stacks/auth/auth/appdata/authentik/oidc-apps.yaml` and limited to
the `admins` group. The client secret is
`vault_overmind_sub2api_oidc_client_secret`, bound on both `auth` and
`overmind`.

sub2api keys an OIDC identity to a sub2api user. It never makes an OIDC user an
admin by itself. To use Authentik as the admin:

1. Log in with the admin password.
2. On the profile page, bind Authentik under the account's identity bindings.
3. From then on, "Login with Authentik" signs in as the admin.

Bind before the first Authentik login. A first Authentik login with no bound
identity auto-registers a separate regular user from the verified email, and
that user then owns the identity.

## Deploy

Three hosts. "Login with Authentik" fails until `auth` has created the
provider; sub2api itself starts either way.

```bash
./run.sh configure --limit auth --stack auth > /tmp/sub2api-auth.log 2>&1
./run.sh --limit overmind --stack sub2api > /tmp/sub2api-overmind.log 2>&1
./run.sh configure --limit portal --stack traefik3 > /tmp/sub2api-portal.log 2>&1
```

## Retiring the trial

Delete `stacks/overmind/sub2api/`, the `sub2api` entry in
`lxc_docker_env_stack_vars`, the router and service in `externalservice.yaml`,
and the four vault keys, and the `sub2api` entry in
`oidc-apps.yaml` with its `auth.yml` binding. The Authentik provider stays
until removed in Authentik. The `*.ai.faviann.com` tier is not part of the
trial and stays. The next overmind run quarantines the stack: it runs
`docker compose down` and moves the stack directory, data included, aside for
recovery. Delete it from quarantine by hand once you no longer need it.
