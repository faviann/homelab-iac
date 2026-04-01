# Inventory Structure Visualization

## Host Group Memberships

This diagram shows how hosts are organized into resource tiers and functional groups:

```
Resource Tiers (exactly one per host)

   tier_tiny (1c/1GB/8GB):
      - (none)

   tier_small (2c/4GB/8GB):
      - auth

   tier_medium (4c/16GB/8GB):
      - portal
      - servarr

   tier_large (8c/32GB/8GB):
      - seedbox


Functional Groups (host can belong to multiple)

   cap_docker:
      - auth
      - portal
      - servarr
      - seedbox

   cap_wireguard:
      - seedbox

   cap_gpu:
      - (none)

```

## Host Configuration Matrix

| Host      | Resource Tier | CPU | RAM  | Docker | GPU | WireGuard | traefik-kop | VMID |
|-----------|---------------|-----|------|--------|-----|-----------|-------------|------|
| auth      | small         | 2   | 4GB  | yes    | no  | no        | yes (default) | 303 |
| portal    | medium        | 4   | 16GB | yes    | no  | no        | no (host override) | 300 |
| servarr   | medium        | 4   | 16GB | yes    | no  | no        | yes (default) | 302 |
| seedbox   | large         | 8   | 32GB | yes    | no  | yes       | yes (default) | 301 |

## Variable Flow Diagram

This shows how variables flow from groups to a specific host (`servarr` example):

```
                    ┌──────────────────────────┐
                    │   group_vars/all/        │
                    │   proxmox.yml            │
                    │                          │
                    │ • proxmox_api_host       │
                    │ • proxmox_default_node   │
                    │ • proxmox_default_mounts │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ group_vars/              │
                    │ tier_medium/vars.yml  │
                    │                          │
                    │ • lxc_cores: 4           │
                    │ • lxc_memory: 16384      │
                    │ • lxc_disk: "8"          │
                    └────────────┬─────────────┘
                                 │
                ┌────────────────┼────────────────┐
                │                │
               ▼
      ┌───────────────────┐
      │ group_vars/       │
      │ cap_docker/vars.yml│
      │                    │
      │ • install_docker   │
      │ • lxc_features     │
      │ • docker_user      │
      │ • docker_agents... │
      │ • traefik_kop...   │
      └─────────┬──────────┘
              │
                                  ▼
                    ┌──────────────────────────┐
                  │ host_vars/servarr.yml    │
                    │                          │
                  │ • vmid: 302              │
                  │ • hostname: servarr      │
                    │ • cores: "{{ lxc_cores }}"│  ← Uses 4 from tier_medium
                  │ • memory: "{{ lxc_memory }}"│ ← Uses 16384 from tier_medium
                    └──────────────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │   Final Host Config      │
                    │       (servarr)          │
                    │                          │
                    │ Merged variables from:   │
                    │ • all/proxmox.yml        │
                    │ • tier_medium/vars.yml  │
                    │ • cap_docker/vars.yml   │
                    │ • host_vars/servarr.yml │
                    └──────────────────────────┘
```

## Group Relationships

```
                        ┌─────────────────┐
                        │   cap_docker    │
                        │                 │
                        │ All LXCs with   │
                        │ Docker runtime  │
                        │ + docker-agents │
                        └────────┬────────┘
                                 │
                    Every host gets:
                    • docker-metadata-proxy
                    • dockwatch-socket-proxy
                    • dockwatch
                    • traefik-kop (unless
                      traefik_kop_enabled: false
                      in host_vars)

   portal: traefik_kop_enabled: false
   auth, servarr, seedbox: traefik_kop_enabled: true (default)
```

## Provisioning Workflow

```
┌──────────────┐
│ Control Node │
│              │
│ Runs Ansible │
└──────┬───────┘
       │
       │ 1. Connects to Proxmox API
       │
       ▼
┌──────────────────┐
│ Proxmox Host     │
│                  │
│ API Endpoint     │◄─── Uses proxmox_api group vars
└──────┬───────────┘
       │
       │ 2. Provisions LXC using:
       │    • Resource tier vars (CPU, RAM, disk)
       │    • Host vars (vmid, hostname)
       │
       ▼
┌──────────────────┐
│ LXC Container    │
│                  │
│ (e.g., servarr)  │◄─── Created with merged variables
└──────┬───────────┘
       │
       │ 3. Configure LXC using:
       │    • Functional group vars
       │    • (Docker, GPU, etc.)
       │
       ▼
┌──────────────────┐
│ Configured LXC   │
│                  │
│ Ready to use     │
└──────────────────┘
```

## Exception Handling Pattern

Example: portal opts out of traefik-kop while keeping docker-agents enabled

```
┌────────────────────────────┐
│ group_vars/cap_docker/vars.yml │
│                                 │
│ docker_agents_enabled: true     │
│ traefik_kop_enabled: true ◄─────┼─── Default for all cap_docker hosts
└────────────┬───────────────┘
             │
             │ Inherited by portal
             │
             ▼
┌────────────────────────────┐
│ host_vars/portal.yml       │
│                            │
│ traefik_kop_enabled: false │◄─── Host-level opt-out
└────────────────────────────┘
             │
             ▼
┌────────────────────────────┐
│ Final portal behavior:     │
│                            │
│ • docker-agents enabled    │
│ • traefik-kop disabled     │
└────────────────────────────┘
```

## Scaling Strategy

### Small Scale (Current: 4 hosts)
```
inventory/
├── hosts.yml (all hosts in one file)
└── group_vars/ (resource + functional groups)
```

### Medium Scale (10-50 hosts)
```
inventory/
├── production.yml
├── staging.yml
├── group_vars/
│   ├── production/
│   └── staging/
└── host_vars/
```

### Large Scale (50+ hosts)
```
Use dynamic inventory via Proxmox API
+ Keep static inventory for core services only
+ Automate host_vars generation
+ Consider Ansible Tower/AWX
```

## Key Design Principles

1. **Resource Tiers are Mutually Exclusive**
   - Each host belongs to exactly ONE resource tier
   - Defines CPU, RAM, disk allocations

2. **Functional Groups are Compositional**
   - Hosts can belong to MULTIPLE functional groups
   - Each group adds specific capabilities

3. **Exceptions via host_vars**
   - Override specific values when needed
   - Document the reason for each exception

4. **Variables Reference Groups**
   - Use `"{{ lxc_cores }}"` instead of hardcoded values
   - Makes overrides explicit and visible

5. **Docker Agents are Universal**
   - All cap_docker hosts get docker-agents by default
   - traefik-kop is opt-out via `traefik_kop_enabled: false` in host_vars
   - Example: portal disables traefik-kop because it runs the Traefik instance itself
