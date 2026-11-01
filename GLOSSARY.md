# Homelab Infrastructure Lifecycle

This context describes how the repository plans and applies changes to the managed homelab infrastructure.

## Language

### Fleet and inventory

**Fleet**:
Every managed LXC declared in inventory, whether or not it is targeted, running, or present on Proxmox. It does not include the Proxmox host itself.
_Avoid_: Cluster

**Targeted LXC set**:
The LXCs of the fleet that one lifecycle run selects. Safety checks and the lifecycle planning barrier cover this set, not the whole fleet.
_Avoid_: All LXCs

**LXC identity reservation**:
The VMID and hostname that inventory claims for one managed LXC, whether or not that LXC is targeted or exists. No LXC may use an identity that another managed LXC reserves.
_Avoid_: VMID allocation

**Capability flag**:
A per-LXC switch that turns on one capability, such as Docker or GPU passthrough, set by membership in the matching capability group.
_Avoid_: Feature flag

**Stack**:
A Docker Compose project the repository declares for one host, which a run deploys, checks, defers, and retires as a unit.
_Avoid_: App, service

**Browser device**:
An LXC running one persistent, signed-in browser session that is driven remotely as a device. One device holds one authenticated identity, so a second identity needs a second device.
_Avoid_: Crawler pool, browser worker, headless browser

**Origin firewall**:
The in-guest allowlist that limits a host's declared TCP ports to loopback and one other managed host. It runs inside the guest, so it does not replace network segmentation.
_Avoid_: Workstation firewall, Proxmox firewall

### Lifecycle runs

**Lifecycle run**:
One locked pass that plans and then applies one lifecycle intent to a targeted LXC set.
_Avoid_: Playbook run

**Lifecycle intent**:
The set of transitions a lifecycle run may make, such as full, provision-only, or configure-only. When a needed transition falls outside that set, planning fails rather than skip it.
_Avoid_: Run mode, lifecycle hint

**Full lifecycle**:
A lifecycle run that reconciles both LXC infrastructure and guest configuration. It may start an existing stopped LXC, because guest configuration needs it running.

**Provision-only lifecycle**:
A lifecycle run that reconciles LXC existence and managed host configuration without guest configuration. It starts an LXC it creates or rebuilds, but leaves an existing stopped LXC stopped.
_Avoid_: Create-only, ensure-running lifecycle

**Configure-only lifecycle**:
A lifecycle run that reconciles guest configuration without creating or starting an LXC. Every targeted LXC must already be running, or the run fails at the lifecycle planning barrier.
_Avoid_: Best-effort configuration

**Nightly deploy**:
The bootstrap node's scheduled full lifecycle run, at the latest merged revision, against the fleet except itself. It holds the fleet lock like any mutating run, so the whole night defers while a run from another control node is in flight.
_Avoid_: Nightly timer, fleet deploy, fleet run

### Planning

**LXC contract**:
The single authoritative desired state of one LXC, compiled once from layered inventory. Every later lifecycle step reads the contract instead of reinterpreting inventory.
_Avoid_: LXC spec, merged config, flattened vars

**Managed host configuration**:
The categories of an LXC's configuration on the Proxmox host that its LXC contract declares, each one a complete set rather than a minimum. Changes made by hand inside a managed category do not persist, and settings outside those categories are left alone.
_Avoid_: Proxmox host configuration

**Fleet preflight**:
The planning step that checks rules spanning several LXCs, such as identity reservations and shared Proxmox access. It decides nothing about any single LXC's transitions.
_Avoid_: Global validation, fleet validation

**LXC observation**:
A point-in-time record of one LXC's actual state on Proxmox, compared with its LXC contract during planning. Each run takes one common Proxmox observation, and every target's observation derives from it.
_Avoid_: Validation result, validation snapshot

**LXC lifecycle plan**:
The validated, unexecuted set of transitions that would bring one targeted LXC from its observed state to its LXC contract, including any destructive transition and the reason for it. A plan belongs only to the run that made it.
_Avoid_: Action list, task list

**Lifecycle planning barrier**:
The guarantee that no lifecycle action starts until every targeted LXC has a valid LXC lifecycle plan. A planning failure for any one target blocks actions for the whole targeted LXC set.
_Avoid_: Validation gate

**Lifecycle policy**:
The persistent inventory rules, set by the operator, that decide whether drift may produce a destructive transition such as a rebuild or removal, and how strictly mismatches fail planning. When the policy authorizes a destructive transition, the plan runs with no per-run confirmation.
_Avoid_: Approval, confirmation

**LXC lifecycle result**:
The per-LXC record that a lifecycle run reports: the plan, its outcome, and the LXC observation before and after. Every targeted LXC gets a result, including targets that the planning barrier blocked.
_Avoid_: Action report

### Interruption

**Interrupting step**:
A lifecycle step that can stop or restart a running stack or its host, such as recreating a stack's containers, upgrading packages, or rebooting. A run takes one only when the busy checks answer idle or the operator deliberately overrides them, and never on the control node it runs from.
_Avoid_: Disruptive change

**Busy check**:
A question declared in the repository and asked before a lifecycle run takes an interrupting step: may this stack or host be interrupted now? Any answer other than idle, including no answer, defers the interruption for that run.
_Avoid_: Health check, readiness probe

**Busy probe**:
A host's own busy check, which defers that host's interrupting steps but not its stacks. The workstation's probe reports busy while an agent is mid-turn or a lifecycle run holds its machine-local lock, and the bootstrap node's while it is running any deploy.
_Avoid_: Idle gate

### Control nodes and trust

**Control node**:
A machine that holds the fleet key and the vault passphrase and runs live operations against the Proxmox host and the fleet. Two are managed LXCs, the workstation and the bootstrap node. The operator's other machines, such as a laptop, can be control nodes too, but are never managed targets. A lifecycle run skips the control node it runs on unless told to include it.
_Avoid_: Controller, Ansible controller, controller machine

**Workstation**:
The control node where the operator and agents work. A run never interrupts it in place, so its interrupting steps come from the bootstrap node.
_Avoid_: Dev machine, dev box

**Bootstrap node**:
The control node that runs the nightly deploy and carries consented interrupting workstation runs, rebuilds, and recovery of an unreachable workstation. It is deployed by the workstation like any other LXC.
_Avoid_: Backup controller, jump host

**Live operation**:
An operation that reaches managed hosts or the Proxmox API with real credentials, requiring only the credentials it consumes. Every other operation is non-live. Validation in particular needs no managed host, vault secret, or machine-local credential.
_Avoid_: Live workflow, deployment, online mode

**Fleet key**:
The one SSH key pair, shared by every control node and every worktree on them, that every managed host trusts. A person restores it from backup or creates it; a run only verifies it.
_Avoid_: Controller SSH identity, controller identity, controller key, worktree SSH key

**Fleet lock**:
The one lock, kept on the Proxmox host, that every mutating run from any control node holds for its whole run, so no two control nodes change the fleet at once. A run that finds it held defers and does not start.
_Avoid_: Global lock, Proxmox lock

**Enrollment**:
A person's explicit step that makes the Proxmox host or existing LXCs trust the fleet key, without reading any LXC contract, so invalid desired state elsewhere cannot block it. Lifecycle runs never enroll the Proxmox host; they reinstall the fleet key in every guest they prepare.
_Avoid_: Manual SSH recovery, key injection, SSH repair

**Host-key pinning**:
Accepting from a managed guest only the host keys read from it through the Proxmox host by VMID, never over the network. They are read afresh before each run connects and again after a create or rebuild.
_Avoid_: Host key scanning, keyscan, accept-new

**Proxmox host-key anchor**:
The Proxmox host's own host key, recorded by a control node the first time it trusts that host. Pinning cannot supply it, and enrollment replaces it after a Proxmox reinstall.
_Avoid_: Pinned Proxmox key
