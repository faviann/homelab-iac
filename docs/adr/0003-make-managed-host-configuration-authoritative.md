# Make managed host configuration authoritative

Each host-configuration category represented in the compiled LXC contract is a complete desired set, not an additive minimum. Reconciliation removes undeclared settings within managed categories, overwrites manual changes there, preserves unrelated configuration, and compares normalized semantic state so Proxmox line reordering does not cause false changes or restarts.
