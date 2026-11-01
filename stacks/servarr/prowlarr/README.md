# Prowlarr Stack

Prowlarr is a portable app stack on the `servarr` Docker host. It exposes the web UI through Traefik with `protected-edge-auth@file`.

## API access

Apps on `servarr` call `http://prowlarr:9696` over the `shared` network. Apps on other hosts call `http://servarr.faviann.vms:9696`. Prowlarr answers 400 to any other host name, so add a new caller's name to `PROWLARR__SERVER__ALLOWEDHOSTS`. Do not route API calls through the Traefik hostname, because edge auth blocks them.

The API key comes from `vault_servarr_prowlarr_api_key`. To rotate it:

1. Replace the vault value with `./vault.sh set vault_servarr_prowlarr_api_key --from-file <path> --replace --strip-final-newline`.
2. Deploy with `./run.sh --limit servarr --stack prowlarr`.
3. In Prowlarr, run **Sync App Indexers** so the synced *arr apps get the new key.
4. Paste the new key into ReadMeABook under its Prowlarr settings. ReadMeABook stores it in its own database.

## Deploy

```bash
./run.sh --limit servarr --stack prowlarr
```
