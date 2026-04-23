---
name: create-stack
description: Use when creating, converting, reviewing, or modifying repo-managed Docker Compose stacks under stacks/, including explicit /create-stack requests.
---

# Create Stack

Design Docker Compose stack changes that match the repo contract while preserving intentional exceptions.

## First Reads

Always read `stacks/README.md` before creating or changing a stack.

Load topic docs only when relevant:

| Situation | Read |
| --- | --- |
| Secrets, `.env`, templating, `stack_vars` | `docs/stacks-secrets.md` |
| Homepage labels or visibility | `docs/stacks-homepage.md` |
| Authentik, OIDC, forwardAuth, auth bypass | `docs/stacks-authentik.md` |
| External networks, proxy network, VPN namespaces | `docs/stacks-networking.md` |
| Existing exceptions or style cleanup | `docs/decisions/adr-006-stack-normalization-exceptions.md` |

Existing stacks are examples only when they match the docs or are listed as accepted exceptions. Do not use historical drift as a template.

## Modes

- **Scaffold**: explicit `/create-stack`, new stack, or converting an existing Compose file.
- **Guardrail**: any create or edit under `stacks/`; validate the result before presenting it.

In scaffold mode, ask only for decisions that cannot be inferred safely: target host, stack name, exposure, vendor intent, ambiguous user-facing service, unknown storage paths, secret classification, and unusual network requirements.

## Workflow

1. Identify input: local files, pasted Compose, or greenfield service name.
2. Validate target: `inventory/host_vars/<host>.yml` exists and has the needed host context such as `default_domain`.
3. Classify the stack: portable app, host-bound app, or foundational/controlled migration.
4. Decide exposure: internal, public routed, protected routed, native app auth/OIDC, or split-route.
5. Normalize ordinary app stacks to the repo style; preserve vendor or foundational shape when intentional and documented.
6. Classify bind mounts and declare required pre-created paths with `x-prereq-dirs`.
7. Put deployment-specific templated values in `.env.j2`; wire secrets through `lxc_docker_env_stack_vars` and `stack_vars.<key>`.
8. Verify network reachability for routed services without assuming every routed app owns its own `ports:` block.
9. Preview stack files, host-var changes, prereq dirs, and vault key names before writing broad scaffold changes.

For greenfield stacks, research official image docs first. Present only viable image options and build from image requirements, not community compose snippets.

## Contract Rules

- Never print, request, or commit real secrets. Use vault-backed vars or `<REPLACE_ME>` placeholders.
- `stack.yaml` is non-secret metadata only. It does not define runtime variables and must not contain vault references.
- Use `.env.j2` for inventory, vault, `stack_vars`, `stack_name`, or host-default values. Static `.env` is only for non-secret local constants. Keep one source of truth per output path.
- Required `stack_vars.<key>` references should fail loudly; do not hide missing required secrets with `default()` or `.get()`.
- Escape `$` as `$$` when rendering secret-like values into `.env.j2`.
- Host deployment mechanics stay in inventory or host vars, not stack-local metadata.
- Do not create `.gitkeep`. Use `x-prereq-dirs` for empty bind-mount targets that must exist before container start.

## Normalization Defaults

Use these defaults for ordinary app stacks. Treat violations as review findings, not automatic blockers, when the stack is vendor-preserving, foundational, VPN namespace-based, or documented as an exception.

| Area | Default |
| --- | --- |
| Labels | Map syntax, only on the user-facing service |
| Traefik | `traefik.enable: true` only when routed; do not restate normal `websecure` or TLS defaults |
| Protected routes | Add `protected-edge-auth@file` to each protected router; no domain-wide middleware is implicit |
| Homepage | Use the intended instance prefix from `docs/stacks-homepage.md` |
| Restart | `restart: unless-stopped` |
| `container_name` | Match service name when that stays clear; allow clearer operational names when documented |
| `hostname` | Omit unless concretely needed |
| LSIO images | Prefer PUID/PGID/TZ env vars; do not add a redundant `user:` directive |
| Non-LSIO images | Preserve `user:` when needed for file ownership or application behavior |
| Image tags | Preserve intentional tags; pin stateful databases |

## Storage

Classify every bind mount:

| Path | Handling |
| --- | --- |
| `./appdata/...` with committed files | Commit files; copy task creates dirs |
| empty `./appdata/...` | Add relative path to `x-prereq-dirs` |
| `/ephemeral/<stack>/...` | Add absolute path to `x-prereq-dirs` |
| new `/data/...` subpath | Add absolute path to `x-prereq-dirs` |
| existing `/data/...` path | Pass through |
| other absolute path | Ask the user to classify |
| named volume | Ask whether to keep Docker-managed storage or convert to repo-owned bind mount |

For vendor-preserving stacks, keep the upstream base recognizable and put repo-owned prereq metadata in the override layer.

## Networking And Exposure

Routed services must be reachable by Traefik or by the host-side label replication path, but the reachable port may live somewhere other than the labeled app:

- portal-hosted services may attach to the host-local `proxy` network instead of relying only on host port publishing
- non-portal services often keep `ports:` because `traefik-kop` replicates labels and the target must still be reachable
- VPN namespace apps using `network_mode: service:<vpn>` publish reachable ports on the VPN service while labels may remain on the user-facing app

External networks used in Compose must also be declared in `lxc_docker_env_external_networks` for that host.

Check host port conflicts by `(host_ip, port, protocol)`, not port number alone. `443/tcp` and `443/udp` are different bindings.

## Accepted Exceptions

Before changing behavior-sensitive fields, read `docs/decisions/adr-006-stack-normalization-exceptions.md`.

Protected examples include:

- `auth/auth`: vendor-preserving Authentik base.
- `seedbox/bittorrent`: VPN namespace; qBittorrent ports live on `gluetun`.
- `public/music`: split public native-auth and protected browser routes.
- `portal/traefik3`: domain-edge reverse proxy infrastructure.

Preserve routes, ports, auth boundaries, storage, network namespaces, and secret flow unless the user explicitly asks to change that behavior.

## Guardrail Checklist

Before finishing any stack edit, verify:

1. Stack path is `stacks/<valid_host>/<stack_name>/`.
2. Exposure intent is explicit.
3. Traefik and Homepage labels are on the correct service.
4. Protected routers explicitly use `protected-edge-auth@file`; public/native-auth routers intentionally do not.
5. Bind-mount targets needing pre-creation are in `x-prereq-dirs`.
6. Secrets and runtime templated values flow through `.env.j2`, `lxc_docker_env_stack_vars`, and `stack_vars`.
7. External networks are declared in host vars.
8. Routed service reachability is valid for the chosen pattern, including portal/proxy and VPN namespace cases.
9. Port bindings do not conflict on the same host IP, port, and protocol.
10. GPU config is only used on GPU-capable hosts.
11. Stack-local docs and metadata contain no plaintext secrets or secret-shaped values.
12. Accepted exceptions are preserved or the behavior change is intentional.
