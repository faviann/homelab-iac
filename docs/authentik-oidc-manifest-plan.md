# Authentik OIDC Manifest Plan

## Summary

Do not add a generic `oidc: true` flag to containers and derive Authentik state from compose scanning.

Use a dedicated Authentik OIDC manifest as the source of truth for apps that need per-app Authentik OAuth2/OpenID providers and applications. The Python sync script should read that manifest, generate the repo-managed OIDC blueprint content, and instantiate/apply it through the existing managed-blueprints workflow.

This keeps the important Authentik decisions explicit while removing the current failure mode where a blueprint file exists on disk but is never instantiated.

## Key Changes

- Add a new manifest file for native OIDC apps under the Authentik area of the repo.
  - Recommended path: `stacks/auth/auth/appdata/authentik/oidc-apps.yaml`
  - This manifest is only for self-auth OIDC apps that need dedicated Authentik OAuth2/OpenID providers/applications.
  - It does not cover forward-auth wildcard providers in v1.

- Define a manifest schema per app entry:
  - `name`: human display name
  - `slug`: Authentik application slug
  - `provider_name`: Authentik provider name
  - `launch_url`: external app URL
  - `client_id`: OAuth client ID used by the app
  - `client_secret_var`: Jinja/auth host-var name to render into blueprint
  - `signing_certificate_var`: Jinja/auth host-var name for signing key lookup
  - `redirect_uris`: exact redirect URI list
  - `custom_scope_mappings`: optional list of custom scope mappings with `name`, `scope_name`, `expression`
  - `policy`: default to `always-allow`
  - `sub_mode`: default to `user_email`
  - `issuer_mode`: default to `global`

- Change `scripts/authentik_blueprint_sync.py` so OIDC apps are generated from the manifest, not maintained as standalone hand-authored per-app blueprint files.
  - Generate one consolidated repo-managed blueprint file for OIDC apps, adjacent to the other Authentik blueprints.
  - Include that generated blueprint in the sync/apply plan automatically.
  - Keep the existing `apply` flow and managed-blueprints API behavior unchanged.

- Update the script’s custom blueprint planning so generated OIDC content is always instantiated/applied.
  - The current failure happened because `36-public-reading-oidc` was discoverable but excluded from the apply plan.
  - The new design must make `present in manifest` imply `present in managed blueprint instances after apply`.

- Migrate current public OIDC apps into the manifest in v1:
  - `romm-public`
  - `audiobookshelf-public`
  - `komga-public`
  - `calibre-web-automated-public`

- Keep stack files and Authentik manifest separate.
  - Stack compose files remain the source of truth for deployment and runtime.
  - The OIDC manifest remains the source of truth for Authentik provider/application definitions.
  - Optional `stack_host` and `stack_name` fields can be added for validation only, not discovery.

## Validation and Behavior

- Add validation in the sync script before apply:
  - every manifest entry has a unique `slug`
  - every manifest entry has a unique `client_id`
  - every `redirect_uri` is absolute `https://`
  - referenced `client_secret_var` and `signing_certificate_var` exist in rendered auth vars
  - generated blueprint names and paths are unique
  - custom scope mapping names are unique across all manifest entries

- Acceptance behavior after `apply`:
  - every manifest entry produces one successful managed blueprint instance
  - every manifest entry creates a live Authentik application and provider
  - each app’s discovery URL under `/application/o/<slug>/.well-known/openid-configuration` returns `200`
  - Audiobookshelf and Komga stop returning `404` on discovery because their Authentik apps now exist

## Test Plan

- Static tests for the sync script:
  - manifest parses and validates
  - generated blueprint output is deterministic
  - duplicate slug, client ID, or mapping names fail fast
  - missing required fields fail fast

- Integration checks against live Authentik:
  - `available` blueprints includes the generated OIDC blueprint
  - managed blueprints includes the generated OIDC blueprint instance
  - managed blueprint instance reaches `successful`
  - applications list contains `romm-public`, `audiobookshelf-public`, and `komga-public`
  - providers list contains `romm-public-oidc`, `audiobookshelf-public-oidc`, and `komga-public-oidc`

- App-level checks:
  - Audiobookshelf auto-populate works from the discovery URL
  - Komga OIDC metadata lookup succeeds
  - RomM remains functional after migration to manifest-generated Authentik config

## Assumptions

- V1 manages only native self-auth OIDC apps, not wildcard forward-auth providers.
- The manifest replaces ad hoc per-app OIDC blueprint authoring for these public apps.
- Container-level OIDC capability is not a useful source of truth, because Authentik needs app-specific data that cannot be inferred safely from compose alone.
- Calibre-Web Automated uses `https://calibre-web-automated.public.faviann.com/login/generic/authorized` as its exact callback URI.
