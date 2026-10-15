# Immich

Immich at `https://immich.public.faviann.com` hosts the photo library. An anonymous user gets the web app and its login screen, and the server answers ping, version, and feature queries without sign-in.

## Sub-features

- `immich-web` serves the web app.
- `immich-ping` answers the API ping.
- `immich-version` reports a version that matches the repo pin.
- `immich-features` reports the enabled server features (machine learning among them).

## How to get to it (user POV)

- Open `https://immich.public.faviann.com/` in a browser.
- The Immich mobile app connects to `https://immich.public.faviann.com` and pings the API before sign-in.

## Driving it with inspect.sh probe

Preconditions:

- Doctor passed for `portal,public`.
- The repo pin is `IMMICH_VERSION` in `stacks/public/immich/.env.j2` (`rg -n IMMICH_VERSION stacks/public/immich/.env.j2`).

- **Web app.** Open the root. Run `./inspect.sh probe https://immich.public.faviann.com/`. `PASS` with `status=200 content_type=text/html` and a body starting `<!doctype html>`.
- **Ping.** Run `./inspect.sh probe https://immich.public.faviann.com/api/server/ping`. `PASS` with `body={"res":"pong"}`, which the log prints as `body={\"res\":\"pong\"}`.
- **Version.** Run `./inspect.sh probe https://immich.public.faviann.com/api/server/version`. `PASS` with JSON `major`, `minor`, `patch` equal to the pin without its `v`.
- **Features.** Run `./inspect.sh probe https://immich.public.faviann.com/api/server/features`. `PASS` with JSON where `"smartSearch":true` and `"facialRecognition":true`, the machine-learning features this deployment enables.
- **Proof.** Run the four URLs in one call: `./inspect.sh probe https://immich.public.faviann.com/ https://immich.public.faviann.com/api/server/ping https://immich.public.faviann.com/api/server/version https://immich.public.faviann.com/api/server/features > "$ev/immich.log" 2>&1; echo "exit=$?" >> "$ev/immich.log"`. Four `PASS` lines, `exit=0`, and the version matches the pin.

## Gotchas

- Immich runs on the `public` LXC, not a host named `immich`. Its doctor target is `public`.
- `*.public.faviann.com` takes the WAN path. See the Jellyfin gotcha.
- `api/server/features` reports configuration, not that the machine-learning container is up. A feature reported `true` with machine learning down still passes. Search and face results need a signed-in session.
- The compose file is vendored (first-line `# vendor:` URL). The pin lives in `.env.j2`, not in the compose `image:` line.
