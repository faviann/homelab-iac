# Lobu Browser Device

Read before touching `lobu-crawler-01` or any other `cap_browser_device` host.

A browser device is one LXC running a headed Chrome session that the Owletto
extension drives on behalf of the Lobu control plane
([lobu-control-plane.md](lobu-control-plane.md)). The extension is the device
worker: no Lobu daemon runs on the box. `./run.sh --limit lobu-crawler-01`
builds everything except the parts only a person can do: pairing the extension
and signing into the sites. This runbook covers those parts.

## The commissioning boundary

A fresh or rebuilt box needs one commissioning session.

- **Reboots are free.** The Chrome profile lives on the container root disk, and
  the `crawler-display`, `crawler-wm` and `crawler-browser` units bring the same
  session back.
- **A rebuild returns uncommissioned, by design.** Nothing persists outside the
  guest, so destroying and recreating it loses the pairing and the site logins.
  Re-running `./run.sh` does not. This is not a defect; walk the steps again.

## Commissioning

Each step is a condition to reach: on a commissioned box, confirm it and move on.

0. **The extension reaches our origin.** In the crawler's Chrome (reached as in
   step 1), point the extension at `https://lobu.admin.faviann.com` and start
   pairing. The gate passes when the extension shows a user code, and fails on
   a network or fetch error. Pairing is the OAuth device-authorization flow
   (RFC 8628) against our own origin. The one thing not verified in advance is
   the extension's MV3 `host_permissions`: without a broad pattern, Chrome
   itself blocks the fetch.

   **If the gate fails, stop.** This runbook has no second branch. Reopen
   `#369` and `#372` instead of improvising a transport.

1. **You are looking at the session.** Tunnel VNC over SSH, then point a VNC
   viewer at `localhost:5900`:

   ```bash
   ssh -L 5900:localhost:5900 faviann@lobu-crawler-01.faviann.vms
   ```

   The origin firewall accepts loopback, so the tunnel is the path until
   Guacamole exists (`#439`). The viewer asks for no password. If the screen is
   missing, check the units:

   ```bash
   systemctl is-active crawler-display crawler-wm crawler-browser
   ```

2. **The extension is paired, approved from the workstation.** The crawler shows
   a user code. Approve it in your own browser at
   `https://lobu.admin.faviann.com/oauth/device`, never in the crawler's Chrome.
   The crawler's profile holds site cookies only, never a Lobu session: control
   plane admin cookies do not belong on the box that browses the open internet.

   The grant is bound to your personal organization. Approval returns 403 if
   that organization does not exist.

3. **The sites are signed in, by hand.** Sign in inside the crawler's Chrome;
   MFA and CAPTCHA happen here. The sites are not listed in this repository:
   one box holds one identity, and the operator opening the session knows which.
   Whether a box is fully commissioned is therefore answerable only from the box.

4. **The device is reachable. Stop there.** From your signed-in browser,
   `GET https://lobu.admin.faviann.com/api/me/devices` shows the crawler's device
   with `online: true`, which means it checked in within the last 120 seconds.
   Commissioning owns *reachable*; `faviann/skills#198` owns *working*.

   A rebuild leaves the previous device row behind, offline. Ignore it: dispatch
   considers only workers inside the freshness window and treats an offline pin
   as rebindable, and a daily reaper deletes rows that have been unseen for 30
   days and that nothing pins.

   The one real breakage is a pin you made by hand to the dead device's uuid.
   Lobu 19.2.0 does not guard against pinning a dead device, and a bad pin fails
   silently as a run that never starts. Once the new device shows
   `online: true`, re-point that pin at it.

## Constraints on the operator

- **No `vzdump`, snapshot, or template clone of this guest.** The root disk is
  the credential-bearing artifact: it holds live site cookies and the pairing.
- **No site credentials in Ansible or Git.**
- **No hand-editing of guest configuration, ever.** If commissioning needs a
  configuration change, the role is wrong; fix `config/lxc_browser_device`.
