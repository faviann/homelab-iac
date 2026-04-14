# RomM MariaDB Operations

Use this when debugging the repo-managed RomM stack in `stacks/public/romm`.

## Stability Defaults

- `romm-db` is pinned to `mariadb:11.4` instead of `latest`
- `romm-db` uses `stop_grace_period: 90s` to give MariaDB time to flush cleanly on shutdown
- the RomM database bind mount on `public` is forced to UID/GID `999:999` via `lxc_docker_env_path_ownership_overrides`

## `tc.log` Recovery

If `romm-db` fails to start after an unclean shutdown and logs mention `tc.log`, use this recovery flow on `public`:

1. Stop the RomM stack.
2. Move `/shared/public/stacks/romm/appdata/db/tc.log` out of the data dir.
3. Start the RomM stack again.
4. Confirm `romm-db` becomes healthy and RomM completes startup.

Example:

```bash
cd /conf/docker/stacks/romm
docker compose down
mv /shared/public/stacks/romm/appdata/db/tc.log /shared/public/stacks/romm/appdata/db/tc.log.bak.$(date +%Y%m%d%H%M%S)
docker compose up -d
docker compose ps
```

After recovery, verify the application path and the schema:

```bash
curl -I https://romm.public.faviann.com
docker exec romm-db mariadb -u root -p"$DB_ROOT_PASSWD" -e "USE romm; SHOW TABLES LIKE 'users';"
```
