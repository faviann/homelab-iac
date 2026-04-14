# Backlog

## Open

## In Progress

## Done

### [DES-001] Remove dead public-wildcard-forwardauth provider
- **Category**: design
- **Location**: `stacks/auth/auth/appdata/authentik/blueprints/30-providers.yaml`, `stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml`, `stacks/auth/auth/appdata/authentik/blueprints/60-outposts.yaml`
- **Context**: Discovered while planning RomM OIDC — the provider's `skip_path_regex` matches every path on `public.faviann.com`, making it a no-op; none of the public services (RomM, Mealie, it-tools) reference the Authentik middleware in their Traefik labels anyway. Dead weight in blueprints and outpost enrollment.
- **Added**: 2026-04-13
- **Completed**: 2026-04-13
- **Status**: done
