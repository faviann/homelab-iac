# Stack Networking

Read when a stack needs external networks, VPN tunneling, or non-default network configuration.

| Pattern | Use |
| --- | --- |
| `shared` external bridge | stable cross-stack communication on one LXC |
| `admin` internal bridge | docker-agents |
| `network_mode: service:<vpn>` | stacks that must share a VPN container's network namespace |

External networks must be declared in host vars before deploy, but only on hosts whose compose files actually use them:

```yaml
lxc_docker_env_external_networks:
  - shared
```

`shared` is a host-local Docker network, not a cross-host network. Use it when one stack needs stable Docker-network access to another stack on the same LXC. A local reverse proxy reaching local services is one example; Servarr services sharing an internal app network are the same pattern.

Older stacks used inconsistent legacy names for this pattern. Use `shared`, and
normalize legacy names when behavior allows.

Do not add `shared` only to support `traefik-kop`; exported labels do not make a remote host-local network reachable.

## Label-Exported Routes

When `traefik-kop` exports labels from a Docker host to portal Traefik, it exports routing metadata, not Docker network reachability. Portal Traefik connects back to the source host through a published port.

If a routed service publishes a different host port than its container port, set `traefik.http.services.<name>.loadbalancer.server.port` to the host port:

```yaml
services:
  sonarr-anime:
    ports:
      - 8990:8989
    labels:
      traefik.enable: true
      traefik.http.routers.sonarr-anime.middlewares: protected-edge-auth@file
      traefik.http.services.sonarr-anime.loadbalancer.server.port: 8990
```

Use the container port only when the active Traefik instance reaches the container directly, such as over a same-LXC shared Docker network.

## VPN Namespace Pattern

Use `network_mode: service:<vpn>` when an application must share a VPN container's network namespace.

In this pattern:

- publish reachable ports on the VPN service, not on the tunneled application
- keep the tunneled application on `network_mode: service:<vpn>`
- labels may stay on the user-facing application when that is the service Traefik/Homepage should describe
- helpers that share the VPN namespace should talk to sibling services through `127.0.0.1` and the shared namespace port

Do not flag a routed tunneled application as broken only because it has no `ports:` block. The corresponding host port can intentionally live on the VPN service.
