---
name: create-stack
description: Use when creating, converting, reviewing, or modifying repo-managed Docker Compose stacks under stacks/.
---

# Create Stack

`stacks/README.md` is the stack contract and owns the Review Checklist. This skill is the process for applying it.

## Reads

Read `stacks/README.md` first, every time. Then read each topic doc the change touches:

| Change touches | Read |
| --- | --- |
| Secrets, `.env.j2`, `stack_vars` | `docs/stacks-secrets.md` |
| Homepage labels | `docs/stacks-homepage.md` |
| Authentik, OIDC, forwardAuth, auth bypass | `docs/stacks-authentik.md` |
| External networks, `shared`, label-exported routes, VPN namespaces | `docs/stacks-networking.md` |
| Any stack listed in ADR-006, or cleanup across stacks | `docs/decisions/adr-006-stack-normalization-exceptions.md` |

Copy patterns only from the docs, or from stacks that pass the README Review Checklist. Older stacks carry drift.

## Steps

1. **Input.** Identify the source: local files, pasted Compose, or a greenfield service name. For greenfield, read the official image docs and present only viable image options; build from the image's documented requirements.
2. **Target.** Confirm `inventory/host_vars/<host>.yml` exists and sets `default_domain`. Check `gpu_enabled` before adding GPU config.
3. **Decisions.** Infer what the input settles. Ask the user only for what it leaves open: host, stack name, exposure (internal, public, protected, native auth/OIDC, or split-route), vendor-preserving intent, which service is user-facing, storage for unclassified absolute paths and named volumes, secret classification, and unusual networking.
4. **Classify.** Name the portability tier from the README. A foundational stack, or a stack listed in ADR-006, keeps its routes, ports, auth boundaries, storage, network namespaces, and secret flow unless the user explicitly asks to change them.
5. **Storage.** Classify every bind mount with the README path table. Declare each pre-created path in `x-prereq-dirs`. Ask the user to classify any other absolute path, and whether a named volume stays Docker-managed or becomes a repo-owned bind mount.
6. **Ports.** List the host's existing bindings across `stacks/<host>/`. A new binding is free when its `(host_ip, port, protocol)` triple is unused; `443/tcp` and `443/udp` are different bindings.
7. **Preview.** Before writing a new stack or converted Compose file, show the user the stack files, host-var changes, `x-prereq-dirs`, and vault key names.
8. **Write.** Write the stack, including `stack.yaml` (README "Stack Metadata"). Apply the README Normalization Defaults to ordinary app stacks. Bind new secrets in `lxc_docker_env_stack_vars` to `vault_*` variables, and tell the user which vault keys to add.
9. **Review.** Walk every item of the README Review Checklist against the final files. Each item passes, or is an accepted exception you name. Then run `./validate.sh` as the mechanical gate until it exits 0.
10. **Deploy.** When the user wants it running, deploy with `./run.sh --limit <host> --stack <stack>` and confirm the containers are up.

When reviewing or editing an existing stack, run steps 4 through 9 on the result.
