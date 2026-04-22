# Homepage Labels

Read when adding or changing Homepage visibility for a service.

Homepage runs three protected instances on `portal`: home, media, and admin. Services are autodiscovered from `cap_docker` hosts through the Docker socket proxies.

| Visibility | Label pattern |
| --- | --- |
| Shared/default cards | `homepage.*` |
| Admin only | `homepage.instance.admin.*` |
| One named instance only | `homepage.instance.<instance>.*` |
| Multiple named instances | repeat labels for each `homepage.instance.<instance>.*` prefix |

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
  homepage.group: Media
  homepage.name: ${COMPOSE_PROJECT_NAME}
  homepage.href: https://${HOMEPAGE_FQDN}
```

For admin-only visibility, switch the prefix to `homepage.instance.admin.`. For a specific non-admin instance, use its instance name, such as `homepage.instance.home.` or `homepage.instance.media.`.

Keep widget labels opt-in; they often need extra secrets or internal-only URLs.
