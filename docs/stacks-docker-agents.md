# Docker Agents

Read when debugging the managed docker-agents stack or changing agent configuration on a host.

Every `cap_docker` host gets the managed `docker-agents` stack from the role. Do not define it under `stacks/`.

Base services:
- `docker-metadata-proxy`: read-only Docker API for Homepage and discovery
- `dockwatch-socket-proxy`: write-capable proxy for Dockwatch
- `dockwatch`: container monitoring UI

Optional when `traefik_kop_enabled: true`:
- `traefik-kop`: copies Docker labels into portal's Redis for Traefik routing

Set `traefik_kop_enabled: false` on `portal`, because portal runs Traefik itself.
