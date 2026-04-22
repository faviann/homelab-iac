# Stack Secrets and `.env`

Read when adding secrets or environment variables to a stack.

Use `.env.j2` whenever values come from inventory or vault.

Example:

```yaml
# inventory/host_vars/seedbox.yml
seedbox_qbit_username: "{{ vault_seedbox_qbit_username }}"
seedbox_qbit_password: "{{ vault_seedbox_qbit_password }}"
```

```jinja2
# stacks/seedbox/bittorrent/.env.j2
QBIT_USERNAME={{ seedbox_qbit_username }}
QBIT_PASSWORD={{ seedbox_qbit_password | replace('$', '$$') }}
HOMEPAGE_FQDN={{ stack_name }}.{{ default_domain }}
```

Rules:
- never commit real secrets to static `.env`
- escape `$` as `$$` in rendered `.env` values
- prefer one source of truth: `.env` or `.env.j2`, not both
- set container user IDs from inventory with `PUID={{ docker_uid }}` and `PGID={{ docker_gid }}` instead of hardcoding `1000`
