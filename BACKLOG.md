# Backlog

## Open

### [TD-001] Rename vault_portal_diun_discord_webhook in vault
- **Category**: tech-debt
- **Location**: `inventory/group_vars/all/vault.yml`
- **Context**: Vault key retained its Diun-era name after Diun was removed; now backs `dockhand_discord_webhook_url`. Rename to `vault_dockhand_discord_webhook_url` for clarity.
- **Added**: 2026-04-17
- **Status**: open

### [DES-003] Add Hardcover metadata provider to CWA
- **Category**: design
- **Location**: `stacks/` (CWA stack)
- **Context**: User wants to use Hardcover as a metadata source in Comic Wrapper App (CWA); requires configuring the provider integration.
- **Added**: 2026-04-18
- **Status**: open

### [DES-004] Add Komf stack for Komga/Kavita metadata fetching
- **Category**: design
- **Location**: `stacks/` (new stack)
- **Context**: Komf (https://github.com/Snd-R/komf) is a metadata fetcher/updater for Komga and Kavita; user wants it deployed as a stack.
- **Added**: 2026-04-18
- **Status**: open

## In Progress

## Done
