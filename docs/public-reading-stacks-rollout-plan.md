# Public Reading Stacks Rollout Plan

This plan rolls out the new public reading services one at a time:

- Audiobookshelf
- Komga
- Calibre-Web Automated

It also covers:

- Authentik deployment order
- how to configure Audiobookshelf OIDC
- how to discover the missing Calibre-Web Automated callback URI
- a repeatable debug loop

## Scope

Relevant repo files:

- [stacks/public/audiobookshelf/compose.yaml](../stacks/public/audiobookshelf/compose.yaml)
- [stacks/public/calibre-web-automated/compose.yaml](../stacks/public/calibre-web-automated/compose.yaml)
- [stacks/public/komga/compose.yaml](../stacks/public/komga/compose.yaml)
- [stacks/public/komga/appdata/config/application.yml.j2](../stacks/public/komga/appdata/config/application.yml.j2)
- [stacks/auth/auth/appdata/authentik/blueprints/36-public-reading-oidc.yaml.j2](../stacks/auth/auth/appdata/authentik/blueprints/36-public-reading-oidc.yaml.j2)
- [docs/stacks-authentik.md](../docs/stacks-authentik.md)
- [inventory/host_vars/public.yml](../inventory/host_vars/public.yml)
- [inventory/host_vars/auth.yml](../inventory/host_vars/auth.yml)

## Important Constraint

`ansible-playbook site.yml --limit public` reconciles every stack under `stacks/public/`.

For this rollout, treat the process as service-focused rather than stack-isolated:

- deploy `public` normally
- debug only the current target service until it works
- ignore healthy sibling stacks unless the deploy introduced a regression there

This means you do not need to move stack directories around just to test Audiobookshelf, Komga, or Calibre-Web Automated one at a time.

If you eventually want literal single-stack reconciliation from Ansible, that would require a code change in the stack sync path; the current repo does not expose a per-stack filter.

## Rollout Order

1. Deploy Authentik changes first.
2. Deploy and test Audiobookshelf.
3. Deploy and test Komga.
4. Deploy and test Calibre-Web Automated.
5. After CWA callback details are known, add its Authentik provider and test OIDC.

## Phase 1: Deploy Authentik

Apply the new OIDC providers for Audiobookshelf and Komga first:

```bash
ansible-playbook site.yml --limit auth
```

Expected result:

- Authentik imports the reading-app OIDC blueprint
- the Audiobookshelf public app exists
- the Komga public app exists
- the provider metadata is backed by the signing certificate referenced by `auth_public_oidc_signing_certificate_name`

If this fails:

- inspect Authentik logs on the `auth` host
- confirm the new host vars rendered correctly

Useful checks on `auth`:

```bash
cd /conf/docker/stacks/auth
docker compose ps
docker compose logs --tail=200
```

## Phase 2: Audiobookshelf

Audiobookshelf should be tested first because its OIDC setup is partly manual in the app UI.

### Deploy

Deploy `public`, then focus debugging on Audiobookshelf first:

```bash
ansible-playbook site.yml --limit public
```

### Smoke Test

Open:

- `https://audiobookshelf.public.faviann.com`

Verify:

- the app loads
- `/data/media/audiobooks` is visible
- no reverse-proxy issues appear in the UI

### Configure OIDC in Audiobookshelf

Use the Authentik application created by the repo blueprint:

- client ID: `audiobookshelf-public`
- client secret: retrieve `vault_public_audiobookshelf_oidc_client_secret` from vault only when entering it in the UI

Redirect URIs already configured in Authentik:

- `https://audiobookshelf.public.faviann.com/auth/openid/callback`
- `https://audiobookshelf.public.faviann.com/auth/openid/mobile-redirect`

If Audiobookshelf asks for issuer, discovery URL, or OpenID configuration URL:

- issuer: `https://auth.faviann.com/application/o/audiobookshelf-public/`
- discovery or OpenID configuration URL: `https://auth.faviann.com/application/o/audiobookshelf-public/.well-known/openid-configuration`

Keep the issuer trailing slash intact. This repo uses the Authentik application URL shape for native OIDC clients.

Expected OIDC behavior:

- user clicks the OpenID login option
- user is redirected to Authentik
- Authentik redirects back to Audiobookshelf
- Audiobookshelf creates or signs in the user

### Audiobookshelf Execution Loop

Run this slice in order and do not move on to Komga until each check passes:

1. Apply the current repo state:

   ```bash
   ansible-playbook site.yml --limit auth
   ansible-playbook site.yml --limit public
   ```

2. Confirm the stack came up on `public`:

   ```bash
   cd /conf/docker/stacks/audiobookshelf
   docker compose ps
   docker compose logs --tail=200 audiobookshelf
   ```

3. Open `https://audiobookshelf.public.faviann.com` and verify the base app works before touching OIDC.

4. In the Audiobookshelf admin UI, configure OpenID Connect with:

   - client ID: `audiobookshelf-public`
   - client secret: `vault_public_audiobookshelf_oidc_client_secret`
   - issuer: `https://auth.faviann.com/application/o/audiobookshelf-public/`
   - discovery URL: `https://auth.faviann.com/application/o/audiobookshelf-public/.well-known/openid-configuration`

5. Attempt one login from a fresh browser session.

6. If login fails, capture the exact callback URL and immediately check both sides:

   ```bash
   cd /conf/docker/stacks/audiobookshelf
   docker compose logs --tail=200 audiobookshelf

   cd /conf/docker/stacks/auth
   docker compose logs --tail=200
   ```

7. Compare the observed callback against the Authentik blueprint redirect URIs and fix the mismatch before retrying.

Exit criteria for this phase:

- route loads cleanly
- audiobook library is visible
- OpenID login succeeds end to end
- no fresh Audiobookshelf or Authentik errors appear during login

### Debug Audiobookshelf

On `public`:

```bash
cd /conf/docker/stacks/audiobookshelf
docker compose ps
docker compose logs --tail=200 audiobookshelf
```

On `auth`:

```bash
cd /conf/docker/stacks/auth
docker compose logs --tail=200
```

Check these failure modes:

- callback URL mismatch
- wrong issuer or discovery URL
- invalid client secret
- email claim or verification mismatch
- missing signing key or empty JWKS metadata from Authentik
- reverse-proxy header problems

If login fails, capture the exact browser callback URL and compare it to the redirect URIs in:

- [stacks/auth/auth/appdata/authentik/blueprints/36-public-reading-oidc.yaml.j2](../stacks/auth/auth/appdata/authentik/blueprints/36-public-reading-oidc.yaml.j2)

## Phase 3: Komga

Komga is the second service because its OIDC wiring is already repo-managed.

### Deploy

After Audiobookshelf is stable, deploy `public` again and focus on Komga:

```bash
ansible-playbook site.yml --limit public
```

### Smoke Test

Open:

- `https://komga.public.faviann.com`

Verify:

- the app loads
- `/data/media/comics` is visible

### Test OIDC

Komga reads OIDC config from:

- [stacks/public/komga/appdata/config/application.yml.j2](../stacks/public/komga/appdata/config/application.yml.j2)

Verify:

- Authentik login option appears
- login redirects to Authentik
- callback returns to Komga
- rendered config uses `https://auth.faviann.com/application/o/komga-public/` as `issuer-uri`
- rendered config includes the client secret sourced from `public_komga_oidc_client_secret`

### Debug Komga

On `public`:

```bash
cd /conf/docker/stacks/komga
docker compose ps
docker compose logs --tail=200 komga
```

Inspect rendered config:

```bash
sed -n '1,220p' /conf/docker/stacks/komga/appdata/config/application.yml
```

Common issues:

- issuer mismatch
- redirect mismatch
- wrong client secret
- `public_komga_oidc_client_secret` missing or not rendered into `application.yml`
- rendered YAML not matching expected Spring structure

## Phase 4: Calibre-Web Automated

Calibre-Web Automated is last because its exact OIDC callback URI is still unknown.

### Deploy

After Komga is stable, deploy `public` again and focus on Calibre-Web Automated:

```bash
ansible-playbook site.yml --limit public
```

### Smoke Test

Open:

- `https://calibre-web-automated.public.faviann.com`

Verify:

- the app loads
- `/data/media/books` is visible
- ingest path works: `/ephemeral/calibre-web-automated/ingest`

### Discover CWA OIDC Details

Goal:

- determine the exact callback or redirect URI expected by CWA

Collect:

- callback URI
- required scopes
- whether it uses issuer discovery or explicit auth/token/userinfo endpoints
- any email or username claim requirements

Best places to inspect:

1. CWA admin auth settings page
2. CWA logs while enabling or testing OIDC
3. browser network trace during a login attempt
4. application docs or UI help text that mentions redirect URI

Useful checks on `public`:

```bash
cd /conf/docker/stacks/calibre-web-automated
docker compose ps
docker compose logs --tail=200 calibre-web-automated
```

Once the callback URI is known:

1. add a repo-managed Authentik provider and application for CWA
2. add any needed secrets to `inventory/host_vars/auth.yml`, `inventory/host_vars/public.yml`, and vault
3. deploy `auth`
4. deploy `public`
5. test the full OIDC loop

## Reusable Debug Loop

Use this same loop for each service:

1. Confirm routing:
   - open `https://<service>.public.faviann.com`
2. Confirm container health:
   - `docker compose ps`
3. Confirm logs are clean:
   - `docker compose logs --tail=200 <service>`
4. Confirm media paths are mounted:
   - verify from app UI and logs
5. Confirm OIDC redirect is exact:
   - compare browser callback URL to Authentik redirect URIs
6. Confirm secrets are wired:
   - `inventory/host_vars/auth.yml` and `inventory/host_vars/public.yml` reference vault where expected
   - rendered config contains the expected values

## Suggested Operator Notes

Record these while testing:

- deployment timestamp
- app version shown in UI
- whether route loaded successfully
- whether media library mounted correctly
- whether OIDC succeeded
- exact callback URI observed
- exact error message if login failed

These notes are especially important for Calibre-Web Automated, since the callback URI discovered during testing is the missing input needed to finish its Authentik integration.
