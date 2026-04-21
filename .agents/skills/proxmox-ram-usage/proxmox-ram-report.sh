#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
host="${PROXMOX_RAM_HOST:-root@proxmox.lan}"
key="${PROXMOX_RAM_KEY:-$repo_root/.ansible/ssh/proxmox_lxc}"

if [[ ! -r "$key" ]]; then
  printf 'ERROR: SSH key not readable: %s\n' "$key" >&2
  exit 2
fi

ssh -o BatchMode=yes -o IdentitiesOnly=yes -i "$key" "$host" python3 - <<'PY'
import json
import re
import subprocess
from pathlib import Path

GIB = 1024 ** 3


def gib(value):
    return value / GIB


def fmt(value):
    if value is None:
        return "n/a"
    return f"{gib(value):.1f} GiB"


def read_meminfo():
    values = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            key, rest = line.split(":", 1)
            parts = rest.split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0]) * 1024
    return values


def read_arcstats():
    path = Path("/proc/spl/kstat/zfs/arcstats")
    values = {}
    if not path.exists():
        return values
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) == 3 and parts[2].isdigit():
                values[parts[0]] = int(parts[2])
    return values


def run_json(command):
    try:
        result = subprocess.run(
            command,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def node_name():
    result = subprocess.run(
        ["hostname", "-s"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout.strip()


def read_int(path):
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError, PermissionError):
        return None


def read_memory_stat(path):
    stats = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, PermissionError):
        return stats
    for line in lines:
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            stats[parts[0]] = int(parts[1])
    return stats


def direct_lxc_cgroups():
    root = Path("/sys/fs/cgroup/lxc")
    if not root.is_dir():
        return []
    groups = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if child.is_dir() and child.name.isdigit():
            groups.append((child.name, child))
    return groups


def qemu_cgroups():
    root = Path("/sys/fs/cgroup/qemu.slice")
    if not root.is_dir():
        return []
    groups = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        match = re.fullmatch(r"(\d+)\.scope", child.name)
        if child.is_dir() and match:
            groups.append((match.group(1), child))
    return groups


def sum_stats(rows, key):
    return sum(row["stats"].get(key, 0) for row in rows)


def pvesh_guests(kind, node):
    return run_json(["pvesh", "get", f"/nodes/{node}/{kind}", "--output-format", "json"])


def guest_lookup(rows):
    return {str(row.get("vmid")): row for row in rows if row.get("vmid") is not None}


def print_table(headers, rows):
    widths = [len(header) for header in headers]
    rendered = []
    for row in rows:
        rendered_row = [str(cell) for cell in row]
        rendered.append(rendered_row)
        widths = [max(width, len(cell)) for width, cell in zip(widths, rendered_row)]
    print("| " + " | ".join(header.ljust(width) for header, width in zip(headers, widths)) + " |")
    print("| " + " | ".join("-" * width for width in widths) + " |")
    for row in rendered:
        print("| " + " | ".join(cell.ljust(width) for cell, width in zip(row, widths)) + " |")


def main():
    node = node_name()
    mem = read_meminfo()
    arc = read_arcstats()
    lxc_pve = pvesh_guests("lxc", node)
    qemu_pve = pvesh_guests("qemu", node)
    lxc_names = guest_lookup(lxc_pve)
    qemu_names = guest_lookup(qemu_pve)

    lxc_rows = []
    for vmid, path in direct_lxc_cgroups():
        stats = read_memory_stat(path / "memory.stat")
        current = read_int(path / "memory.current") or 0
        pve_row = lxc_names.get(vmid, {})
        lxc_rows.append(
            {
                "vmid": vmid,
                "name": pve_row.get("name", ""),
                "status": pve_row.get("status", ""),
                "current": current,
                "pve_mem": int(pve_row.get("mem") or 0),
                "stats": stats,
            }
        )
    lxc_rows.sort(key=lambda row: row["current"], reverse=True)

    qemu_rows = []
    for vmid, path in qemu_cgroups():
        current = read_int(path / "memory.current") or 0
        pve_row = qemu_names.get(vmid, {})
        qemu_rows.append(
            {
                "vmid": vmid,
                "name": pve_row.get("name", ""),
                "status": pve_row.get("status", ""),
                "current": current,
                "pve_mem": int(pve_row.get("memhost") or pve_row.get("mem") or 0),
            }
        )
    qemu_rows.sort(key=lambda row: row["current"], reverse=True)

    total = mem.get("MemTotal")
    free = mem.get("MemFree")
    available = mem.get("MemAvailable")
    buffers = mem.get("Buffers", 0)
    cached = mem.get("Cached", 0)
    sreclaimable = mem.get("SReclaimable", 0)
    shmem = mem.get("Shmem", 0)
    buff_cache = buffers + cached + sreclaimable - shmem
    used = total - free - buff_cache if total is not None and free is not None else None

    arc_size = arc.get("size")
    lxc_total = sum(row["current"] for row in lxc_rows)
    lxc_pve_total = sum(row["pve_mem"] for row in lxc_rows)
    qemu_total = sum(row["current"] for row in qemu_rows)
    qemu_pve_total = sum(row["pve_mem"] for row in qemu_rows)

    print(f"# Proxmox RAM Report ({node})")
    print()
    print_table(
        ["Bucket", "Value"],
        [
            ["Host total", fmt(total)],
            ["Host used", fmt(used)],
            ["Host free", fmt(free)],
            ["Host available", fmt(available)],
            ["Linux buff/cache", fmt(buff_cache)],
            ["ZFS ARC size", fmt(arc_size)],
            ["ZFS ARC target", fmt(arc.get("c"))],
            ["ZFS ARC max", fmt(arc.get("c_max"))],
            ["ZFS ARC min", fmt(arc.get("c_min"))],
            ["LXC cgroup total", fmt(lxc_total)],
            ["LXC pvesh mem total", fmt(lxc_pve_total)],
            ["QEMU cgroup total", fmt(qemu_total)],
            ["QEMU pvesh mem total", fmt(qemu_pve_total)],
        ],
    )
    print()
    print("Note: buckets are diagnostic views, not an exact additive ledger; kernel, cgroup, cache, and ARC accounting can overlap.")

    print()
    print("## LXC cgroups")
    lxc_table = []
    for row in lxc_rows:
        stats = row["stats"]
        lxc_table.append(
            [
                row["vmid"],
                row["name"],
                row["status"],
                fmt(row["current"]),
                fmt(stats.get("anon", 0)),
                fmt(stats.get("file", 0)),
                fmt(stats.get("kernel", 0)),
                fmt(row["pve_mem"]),
            ]
        )
    print_table(["VMID", "Name", "Status", "Cgroup", "Anon", "File", "Kernel", "pvesh mem"], lxc_table)

    print()
    print("## QEMU cgroups")
    qemu_table = [
        [row["vmid"], row["name"], row["status"], fmt(row["current"]), fmt(row["pve_mem"])]
        for row in qemu_rows
    ]
    print_table(["VMID", "Name", "Status", "Cgroup", "pvesh mem"], qemu_table)

    print()
    print("## LXC memory.stat totals")
    print_table(
        ["Type", "Value"],
        [
            ["anon", fmt(sum_stats(lxc_rows, "anon"))],
            ["file", fmt(sum_stats(lxc_rows, "file"))],
            ["kernel", fmt(sum_stats(lxc_rows, "kernel"))],
            ["slab", fmt(sum_stats(lxc_rows, "slab"))],
            ["shmem", fmt(sum_stats(lxc_rows, "shmem"))],
        ],
    )

    print()
    print("## Top process RSS")
    ps = subprocess.run(
        ["ps", "-eo", "pid=,user=,rss=,comm=", "--sort=-rss"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    ps_rows = []
    for line in ps.stdout.splitlines()[:10]:
        parts = line.split(None, 3)
        if len(parts) == 4:
            ps_rows.append([parts[0], parts[1], parts[3], fmt(int(parts[2]) * 1024)])
    print_table(["PID", "User", "Command", "RSS"], ps_rows)

    print()
    if arc_size and total and arc_size > total * 0.5:
        print("Read: ZFS ARC is the dominant RAM bucket. If MemAvailable is healthy, this is cache, not by itself memory pressure.")
    elif lxc_total > qemu_total:
        print("Read: LXC cgroups are the dominant non-host bucket; check anon versus file to separate app memory from guest cache.")
    else:
        print("Read: compare the bucket table with MemAvailable before treating high used memory as pressure.")


if __name__ == "__main__":
    main()
PY
