# Authentik Stack

Authentik is a foundational identity stack on the `auth` Docker host. Its base
`compose.yaml` intentionally stays close to upstream Authentik shape, while
repo-owned behavior lives in the override layer.

## Normalization Boundary

This stack intentionally does not follow every ordinary app-stack default.

Preserve:

- Do not force full contract normalization into `compose.yaml`.
- Do not remove `env_file:` from the upstream-shaped base compose.
- Do not force `container_name` into upstream services.
- Do not convert or remove the base named volume solely for style; runtime
  database data is redirected to `./appdata/database` by the override.
- Do not move repo-specific override behavior into the base compose just to
  reduce files.

Do not use this stack as a template for normal application stacks.

## Ownership

Stack-owned:

- `compose.yaml`
- `compose.override.yaml.j2`
- `.env.j2`
- committed Authentik blueprints and custom templates under `appdata/`

Host-owned:

- `proxy` external network declaration
- auth vault-backed variable bindings in `inventory/host_vars/auth.yml`
- cross-host OIDC and automation inputs declared through host vars

## Deploy

```bash
ansible-playbook site.yml --limit auth -e stack_filter=auth
```
