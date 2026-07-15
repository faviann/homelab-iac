# Separate fleet preflight from LXC lifecycle planning

Fleet preflight consumes compiled identities, validates cross-LXC invariants and shared infrastructure access, and obtains one common Proxmox observation. Identity reservations are checked across all managed inventory hosts, while unrelated full-contract validity is required only for the targeted LXC set. Fleet preflight does not otherwise interpret raw desired-state inventory or decide per-LXC transitions; comparison, release classification, and semantic plan construction belong to the LXC lifecycle module.
