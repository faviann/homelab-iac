# Backlog

## [DES-003] Add Hardcover metadata provider to CWA
- **Category**: design
- **Location**: `stacks/` (CWA stack)
- **Context**: User wants to use Hardcover as a metadata source in Comic Wrapper App (CWA); requires configuring the provider integration.
- **Added**: 2026-04-18

## [DES-004] Add Komf stack for Komga/Kavita metadata fetching
- **Category**: design
- **Location**: `stacks/` (new stack)
- **Context**: Komf (https://github.com/Snd-R/komf) is a metadata fetcher/updater for Komga and Kavita; user wants it deployed as a stack.
- **Added**: 2026-04-18

## [DES-006] Configure OIDC for Storyteller
- **Category**: design
- **Location**: `stacks/public/storyteller/`
- **Context**: Storyteller stack was deployed without OIDC; needs Authentik provider and application wired up like other SSO-enabled stacks.
- **Added**: 2026-04-19

## [BUG-001] ansible-inventory host view exposes vaulted values
- **Category**: bug
- **Location**: `inventory/` verification workflow
- **Context**: While verifying workstation bootstrap, `uv run --locked ansible-inventory -i inventory/hosts.yml --host workstation --yaml` emitted decrypted unrelated secret vars, making that verification step unsafe to paste or relay verbatim.
- **Added**: 2026-04-29
