# Stack Secrets and `.env`

Read when adding secrets or environment variables to a stack.

Use `.env.j2` whenever values come from inventory or vault.

Example:

```yaml
# inventory/host_vars/seedbox.yml
lxc_docker_env_stack_vars:
  bittorrent:
    qbit_username: "{{ vault_seedbox_qbit_username }}"
    qbit_password: "{{ vault_seedbox_qbit_password }}"
```

```jinja2
# stacks/seedbox/bittorrent/.env.j2
QBIT_USERNAME={{ stack_vars.qbit_username }}
QBIT_PASSWORD={{ stack_vars.qbit_password | replace('$', '$$') }}
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
```

Rules:
- never commit real secrets to static `.env`
- escape `$` as `$$` in rendered `.env` values
- prefer one source of truth: `.env` or `.env.j2`, not both
- set container user IDs from inventory with `PUID={{ docker_uid }}` and `PGID={{ docker_gid }}` instead of hardcoding `1000`
- stack templates may read `stack_vars`
- `stack_vars` is provided only while rendering the current stack
- do not put runtime vars or secrets in `stack.yaml` or stack-local variable files
- required `stack_vars.<key>` references should not use `default()` or `.get()` fallbacks
- optional runtime inputs can use explicit fallbacks only when the application has a known safe default
