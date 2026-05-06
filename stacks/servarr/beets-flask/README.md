# beets-flask

beets-flask runs on `servarr` as the UI for tagging and importing soundtrack albums with Beets.

## Ownership

Lidarr owns the regular `Music/` library. It downloads, organizes, and tracks normal music albums there.

Beets owns `Soundtracks/`. Imports through beets-flask may tag, write metadata, and move files into the soundtrack paths below.

Any future Lidarr enrichment hook is metadata-only. It must not ask Beets to move or reorganize files that Lidarr manages under `Music/`.

## Path Contract

The stack mounts these paths with identical host and container paths:

```text
/data/media/_ingest/music:/data/media/_ingest/music
/data/media/music:/data/media/music
```

Do not remap either path inside the container. Beets stores absolute paths in `/config/beets/library.db`, so host/container path skew will create bad library entries.

The GUI inbox starts at `/data/media/_ingest/music`. The Beets library root is `/data/media/music`.

## Routing Contract

Beets path rules are order-sensitive:

```yaml
paths:
  "genre:=Game": "Soundtracks/Game/$album ($year)/$track - $title"
  "albumtype:soundtrack": "Soundtracks/Screen/$album ($year)/$track - $title"
  default: "Music/$albumartist/$album ($year)/$track - $title"
```

VGMplug maps the VGMdb `category` field to Beets `genre`, so game albums route with exact `genre:=Game`.

Do not use `albumtype2`; VGMplug does not emit it in this runtime. Avoid substring queries like `genre:Game`; use exact `genre:=Game` so non-game genres containing that word do not match.

## Runtime Notes

The installed plugin module is `VGMplug`, not `vgmdb`.

Runtime dependencies are installed from `/config/requirements.txt`:

```text
beets-vgmdb==1.3.2
pyacoustid==1.3.1
python3-discogs-client==2.8
```

`appdata/startup.sh` installs Alpine `chromaprint`, installs the Python requirements, applies the compatibility patch needed by this Beets image, and verifies:

```sh
python -c "import beetsplug.VGMplug"
```

There is intentionally no local `Dockerfile` or `stack.yaml`.

## Safe Remediation

For a misrouted album, inspect metadata before moving anything:

```bash
ssh -o BatchMode=yes -l root -i .ansible/ssh/proxmox_lxc servarr.faviann.vms \
  'cd /conf/docker/stacks/beets-flask && docker compose exec -T beets-flask beet -c /config/beets/config.yaml ls -a -f "$album | $genre | $path" "album:<ALBUM_NAME>"'
```

Run a pretend move and confirm the destination:

```bash
ssh -o BatchMode=yes -l root -i .ansible/ssh/proxmox_lxc servarr.faviann.vms \
  'cd /conf/docker/stacks/beets-flask && docker compose exec -T beets-flask beet -c /config/beets/config.yaml move -p "album:<ALBUM_NAME>"'
```

Only after the pretend output is correct, run the real move:

```bash
ssh -o BatchMode=yes -l root -i .ansible/ssh/proxmox_lxc servarr.faviann.vms \
  'cd /conf/docker/stacks/beets-flask && docker compose exec -T beets-flask beet -c /config/beets/config.yaml move "album:<ALBUM_NAME>"'
```

## Deploy

Local contract checks:

```bash
uv run --locked python -m unittest tests.unit.test_servarr_beets_flask_contract
uv run --locked python tests/regression/test_beets_flask_stack_contract.py
```

Dry run one stack:

```bash
uv run --locked ansible-playbook site.yml --limit servarr --check -e stack_filter=beets-flask
```

Deploy one stack:

```bash
uv run --locked ansible-playbook site.yml --limit servarr -e stack_filter=beets-flask
```

For noisy live deploys, redirect to a temp log and inspect high-signal output:

```bash
uv run --locked ansible-playbook site.yml --limit servarr -e stack_filter=beets-flask >/tmp/beets-flask-deploy.log 2>&1
tail -40 /tmp/beets-flask-deploy.log
rg "failed=|unreachable=|FAILED|beets-flask|config.yaml|changed=" /tmp/beets-flask-deploy.log
```

## Live Smoke Checks

Confirm the rendered path rules inside the running container:

```bash
ssh -o BatchMode=yes -l root -i .ansible/ssh/proxmox_lxc servarr.faviann.vms \
  'cd /conf/docker/stacks/beets-flask && docker compose exec -T beets-flask sh -lc "sed -n '\''/^paths:/,/^[^[:space:]\"-]/p'\'' /config/beets/config.yaml"'
```

Confirm the plugin imports:

```bash
ssh -o BatchMode=yes -l root -i .ansible/ssh/proxmox_lxc servarr.faviann.vms \
  'cd /conf/docker/stacks/beets-flask && docker compose exec -T beets-flask python -c "import beetsplug.VGMplug"'
```

Confirm the service is reachable on the published port and through the protected Traefik route before using it for imports.
