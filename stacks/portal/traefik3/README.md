# Traefik3 Stack

This stack is the domain-edge reverse proxy on the `portal` Docker host. It is
infrastructure, not a normal routed application stack.

## Normalization Boundary

This stack intentionally does not follow every ordinary app-stack default.

Preserve:

- Do not remove either `443/tcp` or `443/udp`; same-number TCP and UDP bindings
  are not a port conflict.
- Keep Docker provider socket access behind the stack-local
  `traefik-docker-socket-proxy`; Traefik should not mount the host Docker socket
  directly.
- Do not treat Redis, certificate storage, or `x-managed-files` as
  exception-only behavior. They are normal features for this domain-edge reverse
  proxy pattern.
- Do not read or print files under `stacks/portal/traefik3/secrets/`.
- Do not document `.env` values.
- Do not normalize this stack as if it were a normal routed application.

Do not use this stack as a template for normal application stacks.

## Ownership

Stack-owned:

- `compose.yaml`
- `.env.j2`
- Traefik dynamic and static config under `appdata/`
- ACME storage declarations through `x-managed-files`

Host-owned:

- `shared` external network declaration
- portal vault-backed variable bindings in `inventory/host_vars/portal.yml`
- domain-edge exposure and certificate DNS credentials

## Config Changes

Traefik reads `appdata/traefik3/config/traefik.yaml` only at startup, and the
file is a single-file bind mount. When it changes, stack sync recreates the
`traefik` service. That causes a brief outage of every route on portal, so
batch static config changes. Routers in `conf.d/` are watched and hot-reloaded.
Never declare them in `x-restart-on-change`, because a router edit would then
cause the same outage.

## Proxmox SPICE Proxy

Proxmox `.vv` files set `proxy=http://proxmox.local.faviann.com:3128`, so Remote
Viewer reaches Proxmox `spiceproxy` through this stack. The client sends a
plaintext HTTP `CONNECT` and runs SPICE TLS inside that tunnel. For that reason
the `spice` entrypoint forwards raw TCP to `proxmox.lan:3128` with a
`HostSNI(`*`)` router. It does not terminate TLS or use TLS passthrough, and
the per-VM TLS ports (61000+) are never exposed. The TCP `local-ip-restriction`
reuses the HTTP allowlist ranges through a YAML anchor.

Check from a LAN or VPN client:

```bash
printf 'CONNECT pvespiceproxy:x:0:proxmox:61000 HTTP/1.0\r\n\r\n' \
  | nc -w 3 proxmox.local.faviann.com 3128 | head -1
# HTTP/1.0 401 invalid ticket   <- reached spiceproxy through Traefik
```

A refused connection means Traefik is not publishing 3128. A connection that
closes with no bytes means the client IP is outside the allowlist.

## Collie Mobile Client Certificate

`collie-mobile.admin.faviann.com` lets the phone reach Collie while a
commercial VPN is active. Android runs one VPN at a time, so WireGuard cannot
run beside it. A client certificate gates this hostname instead of a source IP.
Its routers use the `mtls` TLS option in `conf.d/tls.yaml`, which holds the
client CA certificate inline. `collie.admin.faviann.com` keeps the
LAN and WireGuard allowlist and stays the recovery path.

The CA and the phone credentials live in `~/.ansible/collie-ca/` on the
workstation. Never commit them. Only `ca.crt` goes into `tls.yaml`. The
Bitwarden item `dotfiles/collie-ca` is the source of truth for the CA: chezmoi
renders `ca.key` from its Notes and `ca.crt` from its `certificate` field. The
`phone.*` files and `ca.srl` stay local and can be regenerated.

### Reissue the phone certificate

Run the commands on the workstation:

```bash
cd ~/.ansible/collie-ca
umask 077
openssl ecparam -name prime256v1 -genkey -noout -out phone.key
openssl req -new -key phone.key -subj "/CN=Collie phone" -out phone.csr
openssl x509 -req -in phone.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days 1825 -extfile <(printf 'extendedKeyUsage=clientAuth\n') -out phone.crt
openssl rand -base64 12 > phone.p12.pass
openssl pkcs12 -export -inkey phone.key -in phone.crt \
  -certpbe PBE-SHA1-3DES -keypbe PBE-SHA1-3DES -macalg sha1 \
  -passout file:phone.p12.pass -out phone.p12
```

The export uses legacy PKCS#12 encryption because the Android certificate
installer imports only that format reliably. The bundle omits `ca.crt` so
Android does not add it as a trusted CA. Copy `phone.p12` to the phone and
install it as a VPN and app user certificate with the password in `phone.p12.pass`.

### Set up a new phone

If the old phone is lost or still holds its certificate, rotate the CA first.
Otherwise reuse `phone.p12`.

1. On home Wi-Fi, serve the file from the workstation. Android's installer
   grays out a `.p12` that is not served as `application/x-pkcs12`:

   ```bash
   cd "$(mktemp -d)" && cp ~/.ansible/collie-ca/phone.p12 .
   python3 -c 'import http.server as h; h.SimpleHTTPRequestHandler.extensions_map[".p12"] = "application/x-pkcs12"; h.test(h.SimpleHTTPRequestHandler, bind="10.1.4.25", port=8799)'
   ```

   Stop it with Ctrl-C once the phone has
   `http://10.1.4.25:8799/phone.p12`, then delete the temporary directory. Read
   `phone.p12.pass` in your own terminal, never in an agent chat.
2. On the phone, in Settings, search for "certificate" and choose **Install a
   certificate**, then **VPN & app user certificate**.
3. In Chrome, open `https://collie-mobile.admin.faviann.com`, select the
   certificate, and log in.
4. Pair Collie on this hostname. On the workstation, run `collie pair` from
   the Collie plugin's `bin/`, then enter the code on the phone under
   **Settings → Paired devices**. Remove the old phone with
   `collie devices revoke <label>`.

### Rotate the CA

Rotation also revokes every issued certificate. There is no other revocation.

1. Create a new CA in `~/.ansible/collie-ca/`:

   ```bash
   cd ~/.ansible/collie-ca
   umask 077
   openssl ecparam -name prime256v1 -genkey -noout -out ca.key
   openssl req -x509 -new -key ca.key -subj "/CN=Collie client CA" -days 3650 \
     -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
     -addext "keyUsage=critical,keyCertSign,cRLSign" -out ca.crt
   ```

2. Put the new `ca.key` in the Notes of the `dotfiles/collie-ca` item and the
   new `ca.crt` in its `certificate` field, then run `bw sync`. Do this before
   the next `workstation-update`, or its apply restores the old CA and the new
   key is lost.
3. Replace the PEM block under `mtls.clientAuth.caFiles` in `conf.d/tls.yaml`
   with the new `ca.crt`.
4. Deploy with `./run.sh --limit portal --stack traefik3`.
5. Reissue the phone certificate.

## Deploy

```bash
./run.sh configure --limit portal --stack traefik3
```
