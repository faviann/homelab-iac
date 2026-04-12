---
name: create-stack
description: Scaffold, sanitize, or validate Docker Compose stacks to match the repo contract. Use when creating new stacks, converting existing compose files, or modifying files under stacks/. Triggers explicitly via /create-stack or implicitly as a guardrail when touching stacks/.
---

# create-stack

Two modes: **scaffolding** (explicit `/create-stack`) and **guardrail** (implicit when modifying `stacks/`).

Read `stacks/README.md` and all linked docs (`docs/stacks-secrets.md`, `docs/stacks-homepage.md`, `docs/stacks-authentik.md`, `docs/stacks-networking.md`) before producing any output.

---

## Mode Detection

### Scaffolding Mode (explicit)

Triggered by `/create-stack` or when asked to create/convert a stack. Runs the full interactive flow below.

### Guardrail Mode (implicit)

Triggered when you are about to create or modify files under `stacks/`. Run the validation checklist against the result before presenting changes to the user. Do not run the full interactive flow — just validate.

---

## Scaffolding Flow

### Step 1: Identify Input

Detect which input the user provided:

| Input | Action |
|-------|--------|
| **Local file path** (primary case) | Read the compose and any .env files from the path |
| **Pasted compose content** | Work from the pasted content |
| **Service name only** (greenfield) | Go to the Greenfield Research section |

### Step 2: Vendor Check

Ask: **"Is this a vendor/upstream compose you want to keep close to the original (like Authentik), or should I fully normalize it to the repo contract?"**

- **Vendor mode**: Skip all compose normalization (Steps 5-6). Still perform Steps 3-4 and 7-10.
- **Contract mode**: Run all steps.

### Step 3: Validate Target Host

Ask the user for the **target host** (`inventory_hostname`).

Validate:
- `inventory/host_vars/<host>.yml` exists
- Extract `default_domain` from it — this is required for `.env.j2` generation
- If the host doesn't exist in inventory, **stop** and tell the user

Ask the user for the **stack name** (becomes the folder name and Compose project name).

### Step 4: Determine Exposure and Tier

Ask the user:
1. **Traefik exposure**: Should this service be routed through Traefik? (`traefik.enable=true` or internal-only)
2. **Homepage tier**: Media (`homepage.*`), Admin (`homepage.instance.admin.*`), Editors+Admin, or none

### Step 5: Normalize Compose (contract mode only)

Apply these transformations automatically — do not ask:

| Rule | Action |
|------|--------|
| Label format | Convert list syntax (`- key=value`) to map syntax (`key: value`) |
| Traefik defaults | Strip `entrypoints=websecure`, `tls=true`, explicit router rules that match `Host(<stack>.<default_domain>)` |
| `restart` | Set to `unless-stopped` on all services |
| `container_name` | Set to match the service name |
| `hostname` | Strip |
| `env_file` | Strip (Docker Compose loads `.env` implicitly) |
| LSIO `user:` | Strip `user:` directive from `lscr.io/linuxserver/*` images (LSIO handles PUID/PGID internally) |
| Non-LSIO `user:` | Preserve |
| `depends_on` / `healthcheck` | Preserve as-is |
| Image tags | Preserve as-is (do not normalize to `:latest`) |
| `ports` | Preserve always (required for traefik-kop on non-portal hosts) |
| `deploy` blocks | Preserve GPU reservations, flag anything else and ask the user |
| No comments | Do not add comments to output files |

### Step 6: Analyze Services (contract mode only)

**Multi-service stacks**: Auto-detect the user-facing service by filtering out known sidecars (postgres, redis, mariadb, mongo, services named `*-db`, `*-cache`, workers, services with no ports). Apply Traefik and Homepage labels only to the detected user-facing service. Confirm with the user. If ambiguous (multiple candidates), ask.

**Environment variables**:
- Internal wiring (sibling service hostnames, static config) stays inline in the compose `environment:` block
- Deployment-specific values (ports, domains, credentials, PUID/PGID/TZ) go to `.env.j2`

**Named volumes**: Flag any named volumes (e.g., `database:/var/lib/postgresql/data`) and ask the user whether to convert to `./appdata/` bind mounts or keep as-is.

### Step 7: Generate `.env.j2`

Always produce `.env.j2`, never plain `.env`.

Start with the standard boilerplate:

```jinja2
PUID=1000
PGID=1000
TZ=America/Montreal
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
```

Then merge additional deployment-specific vars from the input. If the input has non-standard values for `PUID`, `PGID`, or `TZ`, flag the deviation and ask whether to keep or use defaults.

**Secrets**: Classify every vault-bound env var by type using these heuristics:

| Pattern | Type | Action |
|---------|------|--------|
| `*_password`, `*_passwd`, `*_secret_key`, `*_auth_key`, `*_secret` (internal) | **Generated** | `openssl rand -hex 32` (or 20 for passwords) |
| `*_api_key`, `*_client_id`, `*_client_secret`, `*_token` | **User-provided** | `REPLACE_ME` placeholder |

Present a single grouped confirmation before Step 8 — do not ask per-secret:

```
Secrets classified:
  Generated (will be auto-vaulted with random values):
    vault_<host>_<var> ...
  You provide (REPLACE_ME in vault — fill before deploying):
    vault_<host>_<var> ...
Correct? (y / move X to the other column)
```

Compute the generated values now (store internally for Step 14). Do not print them.

For all vault-bound vars:
1. Add to `.env.j2`: `VAR={{ <host>_<var_name> | replace('$', '$$') }}`
2. Add to `inventory/host_vars/<host>.yml`: `<host>_<var_name>: "{{ vault_<host>_<var_name> }}"`

Do not write to vault yet — that happens in Step 14.

### Step 8: Networking

**Scan sibling stacks** under `stacks/<host>/*/compose.yaml` for external network declarations.

- If external networks found: present them and ask "Should this stack join any of these?"
- If none found: ask "Does this stack need a shared network with anything on this host?"

If the stack uses an external network (new or existing):
- Declare it in the compose with `external: true`
- Check `lxc_docker_env_external_networks` in `inventory/host_vars/<host>.yml`
- If the network is missing from that list, **include the host var update in the preview**

### Step 9: Port Conflict Check

Scan all `compose.yaml` files under `stacks/<host>/` for host port mappings. If the new stack conflicts, flag: "Port `<port>` is already used by `<stack>` on this host."

### Step 10: GPU Validation

If the compose includes GPU config (`runtime: nvidia`, `deploy.resources.reservations.devices`):
- Check if the target host is in `cap_gpu` group (look for `gpu_enabled: true` in host/group vars)
- If the host lacks GPU capability, warn that GPU config won't work

### Step 11: Appdata Scaffolding

Parse all bind-mount volumes pointing to `./appdata/...` from the compose. Auto-create the directory tree with `.gitkeep` files. Include in the preview.

### Step 12: Authentik Flag

If the stack is Traefik-routed, check the exposure tier:
- Standard routed on `faviann.com` or `admin.faviann.com` — note: "Catch-all auth handles this, no Authentik config needed"
- Public self-auth on `public.faviann.com` — flag: "This will need a public outpost provider. See `docs/stacks-authentik.md`"
- Group-restricted access — flag: "This will need a dedicated Authentik provider + application. See `docs/stacks-authentik.md`"

Do not create Authentik config. Just flag and link the docs.

### Step 13: Preview and Confirm

Present all changes as a unified preview:
- New files: `compose.yaml`, `.env.j2`, `appdata/` tree
- Modified files: `inventory/host_vars/<host>.yml` (vault var indirection, network declarations)
- Vault writes: list generated var names (not values) and user-provided vars that will get `REPLACE_ME`
- Any Authentik notes

**Do not write any files until the user confirms.**

### Step 14: Write and Deploy Command

On confirmation:

1. Write all stack files (`compose.yaml`, `.env.j2`, `appdata/` tree, host var updates).
2. Write vault entries:
   ```bash
   source .ansible/venv/bin/activate
   ansible-vault decrypt inventory/group_vars/all/vault.yml --vault-password-file .ansible/vault-pass.txt
   # append generated entries with computed values and REPLACE_ME entries for user-provided
   ansible-vault encrypt --encrypt-vault-id default inventory/group_vars/all/vault.yml --vault-password-file .ansible/vault-pass.txt
   ```
3. If any user-provided secrets exist, print which vault keys need real values before deploying.
4. Print:
   ```
   Deploy with: ansible-playbook site.yml --limit <host>
   ```

Do not offer to run the deploy command.

---

## Greenfield Research

When the user provides only a service name (no existing compose):

1. Research the service's Docker image documentation (Docker Hub, GHCR, official docs)
2. If multiple images exist (official, LSIO, community), present options with a note when an LSIO image is available (LSIO aligns with the `.env.j2` boilerplate). Let the user pick.
3. From the chosen image docs, extract: required/optional env vars, volume mount points, exposed ports, any special requirements (GPU, sysctls, capabilities)
4. Assemble a contract-compliant compose from these raw facts — do not copy community compose examples. The user-facing service **must** include a `ports:` mapping for its primary port — traefik-kop requires the port to be reachable on the host network.
5. Continue from Step 3 of the scaffolding flow

---

## VPN Stack Validation

If the compose contains `network_mode: service:<name>`:
- Verify that ports are declared on the VPN container, not on the tunneled service
- Flag if ports are on the wrong container

Do not proactively offer VPN setup for greenfield stacks.

---

## Guardrail Validation Checklist

Run this checklist when modifying existing files under `stacks/`. Flag violations to the user before writing.

1. Stack lives in `stacks/<valid_host>/<stack_name>/`
2. Labels use map syntax (`key: value`)
3. No restated Traefik defaults (`entrypoints`, `tls`)
4. `traefik.enable=true` present if and only if the service should be routed
5. Homepage labels use correct tier prefix
6. `restart: unless-stopped` on all services
7. `container_name` matches service name
8. No `hostname` directive
9. No `env_file` declarations
10. Secrets in `.env.j2`, not static `.env`
11. `appdata/` dirs exist for all bind mounts, with `.gitkeep`
12. External networks declared in `lxc_docker_env_external_networks` host var
13. No port conflicts with sibling stacks
14. No `user:` on LSIO images
15. GPU config only on `cap_gpu` hosts
16. VPN stacks have ports on the VPN container
17. User-facing service with `traefik.enable=true` has a `ports:` mapping
