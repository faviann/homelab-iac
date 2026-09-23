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

## Deploy

```bash
./run.sh configure --limit portal --stack traefik3
```
