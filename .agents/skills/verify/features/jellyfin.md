# Jellyfin

Jellyfin at `https://jellyfin.public.faviann.com` streams the media library. An anonymous user gets the web client and its login screen, and the server publishes its name and version without sign-in.

## Sub-features

- `jellyfin-web` serves the web client.
- `jellyfin-health` reports the server healthy.
- `jellyfin-version` publishes server info whose version matches the repo pin.

## How to get to it (user POV)

- Open `https://jellyfin.public.faviann.com/web/` in a browser.
- Jellyfin apps on phones and TVs connect to `https://jellyfin.public.faviann.com` and read the same public server info first.

## Driving it with inspect.sh

Preconditions:

- Runs as anonymous.
- Doctor passed for `portal,jellyfin`.
- The repo pin is the `image:` tag in `stacks/jellyfin/jellyfin/compose.yaml` (`rg -n "image:" stacks/jellyfin/jellyfin/compose.yaml`).

- **Web client.** Open the web UI. Run `./inspect.sh probe https://jellyfin.public.faviann.com/web/`. `PASS` with `status=200 content_type=text/html` and a body starting `<!doctype html>`.
- **Health.** Run `./inspect.sh probe https://jellyfin.public.faviann.com/health`. `PASS` with `body=Healthy`.
- **Version.** Run `./inspect.sh probe https://jellyfin.public.faviann.com/System/Info/Public`. `PASS` with JSON whose `"Version"` equals the repo pin and whose `"LocalAddress"` is `https://jellyfin.public.faviann.com`.
- **Proof.** Run the three URLs in one call: `./inspect.sh probe https://jellyfin.public.faviann.com/web/ https://jellyfin.public.faviann.com/health https://jellyfin.public.faviann.com/System/Info/Public > "$ev/jellyfin.log" 2>&1; echo "exit=$?" >> "$ev/jellyfin.log"`. Three `PASS` lines, `exit=0`, and the version matches the pin.

## Gotchas

- `*.public.faviann.com` resolves to the WAN address through a DDNS CNAME, not to the LAN edge, so a probe from the LAN takes the WAN path back in through the router. A failure here with `auth` passing points at the WAN path or the router's hairpin, not Jellyfin.
- `/web/` returns the client shell even when the library database is broken. Health and version prove the backend. The shell proves only routing.
- Playback, transcoding, and the NVIDIA runtime need a signed-in session and are not reachable by this harness.
- A version older than the pin means the deploy has not reached the host yet, or a busy check deferred it (`./run.sh` exit 3). Report it. Do not deploy.
