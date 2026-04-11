# Homepage Labels

Read when adding or changing Homepage visibility for a service.

Homepage runs three protected instances on `portal`: media, editors, and admin. Services are autodiscovered from `cap_docker` hosts through the Docker socket proxies.

| Tier | Label pattern |
| --- | --- |
| Media / visible to all signed-in users | `homepage.*` |
| Admin only | `homepage.instance.admin.*` |
| Editors + admin | `homepage.instance.editors.*` and `homepage.instance.admin.*` |

Recommended baseline labels:

| Label | Purpose |
| --- | --- |
| `homepage.group` | section |
| `homepage.name` | display name |
| `homepage.href` | canonical URL |
| `homepage.description` | short description |
| `homepage.icon` | icon |

Example:

```yaml
labels:
  - homepage.group=Media
  - homepage.name=${COMPOSE_PROJECT_NAME}
  - homepage.href=https://${HOMEPAGE_FQDN}
```

For admin-only visibility, switch the prefix to `homepage.instance.admin.`.

Keep widget labels opt-in; they often need extra secrets or internal-only URLs.
