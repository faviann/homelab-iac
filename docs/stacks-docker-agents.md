# Docker Agents

Read when debugging the managed docker-agents stack or changing agent configuration on a host.

By default, every `cap_docker` host gets the managed `docker-agents` stack from the role. Do not define it under `stacks/`.

Base services:
- `docker-metadata-proxy`: read-only Docker API for Homepage discovery
- `dockwatch-socket-proxy`: write-capable proxy for Dockwatch
- `dockwatch`: container monitoring UI

Optional when `traefik_kop_enabled: true`:
- `traefik-kop`: copies Docker labels into portal's Redis for Traefik routing

Hawser is enabled on every non-`portal` Docker host where `docker_agents_enabled: true`:
- `hawser`: Standard-mode remote agent for Dockhand multi-host management across the remote fleet

Set `docker_agents_enabled: false` on hosts that need Docker without the managed `docker-agents` stack and its Dockhand/Homepage/Hawser sidecars, such as `workstation`.

Set `traefik_kop_enabled: false` on `portal`, because portal runs Traefik itself.
`portal` is also excluded from Hawser because it hosts Dockhand rather than acting as a remote service host.

Portal Traefik uses its own stack-local `traefik-docker-socket-proxy` in
`stacks/portal/traefik3/`. Keep that proxy separate from the managed
`docker-metadata-proxy` so edge routing does not depend on the docker-agents
stack or its broader Homepage-oriented allowlist.
