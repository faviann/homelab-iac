# Stack Networking

Read when a stack needs external networks, VPN tunneling, or non-default network configuration.

| Pattern | Use |
| --- | --- |
| `proxy` external bridge | host-local proxy attachment for stacks that explicitly join the shared proxy network |
| `admin` internal bridge | docker-agents |
| `network_mode: service:<vpn>` | stacks that must share a VPN container's network namespace |

External networks must be declared in host vars before deploy:

```yaml
lxc_docker_env_external_networks:
  - proxy
```

`proxy` is a host-local Docker network, not a cross-host network. Portal-hosted services use it so local Traefik can reach them directly. Some non-portal stacks also declare it when their compose file explicitly attaches services to a local shared proxy network, but `traefik-kop` label replication alone does not require every routed service to join `proxy`.

## VPN Namespace Pattern

Use `network_mode: service:<vpn>` when an application must share a VPN container's network namespace.

In this pattern:

- publish reachable ports on the VPN service, not on the tunneled application
- keep the tunneled application on `network_mode: service:<vpn>`
- labels may stay on the user-facing application when that is the service Traefik/Homepage should describe
- helpers that share the VPN namespace should talk to sibling services through `127.0.0.1` and the shared namespace port

Do not flag a routed tunneled application as broken only because it has no `ports:` block. The corresponding host port can intentionally live on the VPN service.
