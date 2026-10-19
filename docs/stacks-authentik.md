# Authentik Integration

Read when creating or modifying Authentik providers, applications, or auth bypass rules for a stack.

Traefik edge auth is explicit per protected router via `protected-edge-auth@file`.
Public routers should stay edge-open unless there is a specific reason to protect them at Traefik.

The shared proxy providers cover the protected tiers, so most protected services need no per-app Authentik object just to require login.

Create a dedicated Authentik provider + application when:
- access is group-restricted
- the hostname needs a non-catch-all provider
- the service is self-auth and should stay edge-open at Traefik

Use the provider type that matches the integration: Proxy Provider for Authentik forwardAuth/proxy flows, OAuth2/OpenID Provider for apps that do native OIDC.

Repo-wide rules:
- admin uses shared `admin-wildcard-forwardauth`
- home uses shared `home-wildcard-forwardauth`
- media uses shared `media-wildcard-forwardauth`
- root `faviann.com` uses `Provider for Domain Wide Forward Auth Catch All` when edge auth is desired
- shared callback tiers rely on global `AUTHENTIK_COOKIE_DOMAIN=.faviann.com`

Important: only protected routers should send traffic through Traefik forwardAuth. Public apps that use native auth or OIDC should not also sit behind Traefik forwardAuth.
For protected tiers, the matching provider still needs the outpost callback URL allowlisted in `Unauthenticated URLs / Paths`, including `https://<domain>/outpost.goauthentik.io/...`.

| Need | Action |
| --- | --- |
| Basic protected-tier login | add `protected-edge-auth@file`; shared provider handles login |
| Public app with native auth/OIDC | no Traefik auth middleware |
| Shared admin-tier login | keep `admin-wildcard-forwardauth` synced |
| Group restriction | create provider + application and bind groups |

Current shared protected-tier providers: `admin-wildcard-forwardauth`, `home-wildcard-forwardauth`, `media-wildcard-forwardauth`, and `Provider for Domain Wide Forward Auth Catch All`.

## Access Groups

Use domain bundle groups for ordinary application access:

| Group | Use for |
| --- | --- |
| `media` | Media applications and the media protected tier. |
| `reading` | Reading applications such as Audiobookshelf, Komga, Calibre-Web Automated, and ReadMeABook. |
| `storage` | Home-tier file, document, and storage services. |

`admins` is bound to every gated repo-managed application as the admin override
group. Per-app groups are created only when a user needs access to one
application without joining the wider domain bundle.

For app-specific Authentik objects, bind access at the application using this
convention:

| Order | Binding |
| --- | --- |
| `0` | Per-app group, only when one exists. |
| `1` | Domain bundle group. |
| `2` | `admins`. |

Keep `policy_engine_mode: any` on gated applications so any matching group
grants access.

## Native OIDC Pattern

For public apps that should stay edge-open and handle login themselves:

- do not add `protected-edge-auth@file` to the Traefik router
- create an Authentik OAuth2/OpenID provider plus application
- select an Authentik signing key explicitly in the provider so the JWKS endpoint publishes keys for the client
- add the app's OIDC environment variables via `.env.j2`
- keep redirect URIs exact for the app's callback path

Repo-managed native OIDC app definitions live with the Authentik stack:

- Manifest: `stacks/auth/auth/appdata/authentik/oidc-apps.yaml`
- Generated blueprint template: `stacks/auth/auth/appdata/authentik/blueprints/80-oidc-apps.yaml.j2`

Set `group:` in the manifest to the app's domain bundle, or to `admins` for an
intentionally admins-only application. The generated blueprint replaces
`always-allow` with domain-group and `admins` bindings. An admins-only app
therefore gets the same `admins` group at both orders; under
`policy_engine_mode: any` that is one redundant but harmless binding.

Set `grant_types:` on any app whose provider is created by this blueprint on
Authentik 2026.5 or later. New providers default to an empty grant list, and
both the authorize and token endpoints reject a grant that is not listed.
Providers that predate 2026.5 were backfilled by migration and omit the key, so
the manifest leaves their live grant sets untouched.

RomM is the current concrete native OIDC example. Its app-specific notes live in [stacks/public/romm/README.md](../stacks/public/romm/README.md).

## Blueprint `!Find` Lookups

Read when a blueprint must reference an Authentik object without hardcoding an
instance-specific UUID.

`!Find [<model>, [<field>, <value>, ...]]` resolves to one database lookup in
`authentik/blueprints/v1/common.py`. Its behavior was confirmed against that
source in April 2026:

- The field name passes unmodified into Django's `Q()`, so `__` traversals such
  as `stage__name`, `flow__slug`, and `target__slug` work.
- The condition list alternates fields and values,
  `[field1, value1, field2, value2]`. All conditions are ANDed.
- The lookup uses `.first()`, not `.get()`. When several objects match, it
  returns the first without an error, so make each lookup unambiguous.
- The model is `app_label.model_name`, with the Django app label rather than
  the Python module path. Exported blueprints use
  `authentik_flows.flowstagebinding`, `authentik_flows.flow`,
  `authentik_policies_expression.expressionpolicy`, and
  `authentik_policies.policybindingmodel`.

Some object types carry a `managed` value that survives a fresh deploy, so
`!Find [<model>, [managed, goauthentik.io/...]]` finds them:

| Object type | Example `managed` value |
| --- | --- |
| `Flow` | `goauthentik.io/flows/default-password-change` |
| `Stage` subclasses | `goauthentik.io/stages/prompt/default-password-change-prompt` |
| `PropertyMapping` | `goauthentik.io/providers/oauth2/scope-openid` |
| `Policy` (some) | varies |

A fresh deploy regenerates these keys, so never hardcode them:

| Key | Stable alternative |
| --- | --- |
| `FlowStageBinding.pk` / `pbm_uuid` | A `stage__name` traversal. A flow stage binding has no `managed` field, as the exported blueprints in `stacks/auth/auth/appdata/authentik/blueprints/20-flows/` confirm. |
| `PolicyBinding.pk` / `pbm_uuid` | The bound object's own stable fields. A policy binding has no `managed` field. |
| Auto-created `Application`, `Provider`, and `Group` PKs | `slug` or `name`. An application has no `managed` field, but its `slug` is stable. |

Find a flow stage binding by its stage's name:

```yaml
!Find [authentik_flows.flowstagebinding, [stage__name, default-password-change-prompt]]
```

Add the flow's slug when the same stage is bound to several flows:

```yaml
!Find [authentik_flows.flowstagebinding, [stage__name, default-password-change-prompt, target__slug, default-password-change]]
```

Find a flow by its slug. This also works for a policy binding that targets a
flow, because `Flow` extends `PolicyBindingModel`:

```yaml
!Find [authentik_flows.flow, [slug, default-password-change]]
```

[ADR-0023](adr/0023-use-navidrome-native-auth-on-the-public-music-hostname.md)
uses the first lookup in the password-change blueprint.
