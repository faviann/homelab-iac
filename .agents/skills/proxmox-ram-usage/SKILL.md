---
name: proxmox-ram-usage
description: Use when diagnosing Proxmox RAM usage, memory pressure, ZFS ARC, LXC or QEMU guest memory, or questions like where is my RAM going on this repo's Proxmox host.
---

# Proxmox RAM Usage

## Overview

Use one read-only snapshot and reconcile buckets before interpreting Proxmox memory. The important distinction is host memory pressure versus reclaimable ZFS ARC and guest-charged cache.

## Quick Run

From the repo root:

```bash
bash .agents/skills/proxmox-ram-usage/proxmox-ram-report.sh
```

Defaults:

| Setting | Value |
|---|---|
| Host | `root@proxmox.lan` |
| SSH key | `~/.ansible/ssh/proxmox_lxc` |
| Override host | `PROXMOX_RAM_HOST=root@host` |
| Override key | `PROXMOX_RAM_KEY=/path/to/key` |

If sandbox DNS or network access fails, rerun the same command with network approval. If SSH still fails, say live data could not be collected and do not infer from stale values. Never ask for or print secrets.

## Interpretation

Report these buckets first:

| Bucket | Source | Meaning |
|---|---|---|
| Host total/free/available | `/proc/meminfo` | `available` is the pressure signal |
| ZFS ARC size/target/max | `/proc/spl/kstat/zfs/arcstats` | ARC is usually reclaimable cache |
| LXC cgroup total | direct `/sys/fs/cgroup/lxc/<vmid>` | Actual memory charged to containers |
| LXC anon/file/kernel | `memory.stat` | App memory versus guest file cache/kernel |
| Proxmox LXC mem | `pvesh /nodes/<node>/lxc` | Useful cross-check; can differ from cgroups |
| QEMU total | `pvesh` plus `qemu.slice` | VM memory charged to host |
| Top RSS | `ps` | Sanity check only; LXC processes are visible on host |

Expected pattern from this lab: ARC can dominate RAM while `MemAvailable` stays healthy. Treat that as cache, not a runaway process.

Do not force all buckets to add exactly; kernel, cgroup, cache, and ARC accounting are diagnostic views with some overlap.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Calling `free` used memory a problem | Check `MemAvailable` and ARC first |
| Summing `lxc/<id>` and `lxc/<id>/ns` | Use only direct numeric cgroups |
| Trusting only `pvesh` guest mem | Compare with cgroup `memory.current` |
| Treating LXC file cache as app RAM | Split `memory.stat` into anon/file/kernel |
| Blaming top RSS processes first | Use RSS only after bucket totals |

## Response Shape

Answer with a compact table, then a short read. Include whether most RAM is ARC, guest app memory, guest file cache, QEMU, or host services. Mention if ARC is near `c_max` and whether available RAM suggests real pressure.
