# Stack Networking

Read when a stack needs external networks, VPN tunneling, or non-default network configuration.

| Pattern | Use |
| --- | --- |
| `proxy` external bridge | portal-hosted Traefik-routed services |
| `admin` internal bridge | docker-agents |
| `network_mode: service:<vpn>` | stacks that must share a VPN container's network namespace |

External networks must be declared in host vars before deploy:

```yaml
lxc_docker_env_external_networks:
  - proxy
```

For VPN-tunneled stacks, publish ports on the VPN container, not on the tunneled service.
