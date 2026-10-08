# Homelab Infrastructure Lifecycle

This context describes how the repository plans and applies changes to the managed homelab infrastructure.

## Language

**Artifact publication**:
A completed file or prepared directory tree copied for browser delivery, independently of its original source and worktree. Publications remain available until deliberately removed; deleting the source or rebuilding the workstation does not define their lifetime.
_Avoid_: Temporary report, live workspace

**Artifact publishing mapping**:
The shared agreement between infrastructure and workstation user configuration that associates an existing publication directory with its browser URL prefix. Each relative file path under the directory identifies the same relative resource under the URL prefix.
_Avoid_: Upload endpoint, artifact registry

**Busy check**:
A declared command that answers, before a lifecycle run would interrupt, whether it may interrupt now: either a repo-managed stack's opt-in command, run inside one of its services, or a host's declared probe, run on the host. Only exit `0` means idle; every other answer, including no answer, defers the host's interrupting steps for that run, and a stack's check also defers that stack. A stack with no deployed containers is not checked.
_Avoid_: Health check, readiness probe, drain

**Workstation busy probe**:
The workstation's host-level busy check. Busy while a herdr pane is `working` or the lifecycle lock is held; idle when herdr is not running; busy on any execution error. A run that includes its own control node defers without consulting it.
_Avoid_: Idle gate, sentinel stack

**Targeted LXC set**:
The managed LXCs selected for a lifecycle run. Safety checks and the pre-action planning barrier apply to this set, not automatically to every LXC in inventory.
_Avoid_: Fleet, all LXCs

**Fleet preflight**:
The planning phase that validates cross-LXC invariants and shared infrastructure access, then provides a common observation of Proxmox state. It does not decide the lifecycle transition for an individual LXC.
_Avoid_: Per-LXC validation, lifecycle planning

**LXC identity reservation**:
An inventory claim on the VMID and hostname of a managed LXC, whether or not that LXC is targeted or currently exists. A targeted lifecycle run cannot use an identity reserved by another managed LXC.
_Avoid_: Runtime identity, active-container identity

**LXC lifecycle plan**:
A validated, non-executing description of the semantic transitions required to bring one targeted LXC from its observed state to its desired state, including destructive intent and reasons without exposing internal task names. It belongs only to the lifecycle run that produced it and is not reusable by a later run.
_Avoid_: Validation snapshot, action lists

**LXC lifecycle result**:
The semantic record of an LXC lifecycle plan and its observable execution outcome, with compact before-and-after observations. Every targeted LXC receives a result, including targets blocked from execution by another target's planning failure; results exclude internal task names, intermediate facts, and duplicated compiled contract data.
_Avoid_: Internal snapshot, action report

**LXC contract compilation**:
The single interpretation of layered inventory into the authoritative desired infrastructure state for one LXC. Infrastructure validation, provisioning, host configuration, and guest bootstrap consume the resulting compiled LXC contract rather than interpreting the inventory layers again.
_Avoid_: Flattening, spec merge

**Manual SSH recovery**:
An operator-initiated access restoration operation for an existing LXC. It remains usable when unrelated desired infrastructure state is invalid.
_Avoid_: Normal lifecycle configuration, full convergence

**Managed host configuration**:
The portion of an LXC's Proxmox-host configuration whose complete desired state is expressed by the compiled LXC contract. Manual changes within a managed category are not durable; configuration outside managed categories remains untouched.
_Avoid_: Additive configuration, minimum configuration

**Guest-command readiness**:
The proof that an LXC accepts a minimal command executed inside it through the Proxmox host. It is bounded by a deadline and is the only readiness managed host configuration establishes after a restart. It does not imply SSH access, boot completion, or application health; those remain owned by the modules that require them, and SSH access stays owned by the guest-configuration connection wait.
_Avoid_: Container running, boot complete, SSH ready

**LXC observation**:
A point-in-time representation of an LXC's current infrastructure and runtime state, used to compare reality with its compiled desired state.
_Avoid_: Validation snapshot, independently queried state

**Lifecycle planning barrier**:
The safety guarantee that no lifecycle actions begin until every targeted LXC has a valid LXC lifecycle plan. A planning failure for any target prevents actions for the entire targeted LXC set.
_Avoid_: Strict-validation mode, partial-skip execution

**Lifecycle policy**:
Persistent operator-authored rules that determine whether observed drift may produce destructive lifecycle transitions. A valid plan executes without a second per-run confirmation when its destructive transition is authorized by policy.
_Avoid_: Interactive approval, per-run confirmation

**Lifecycle intent**:
The exact set of infrastructure and configuration transitions permitted for a lifecycle run. If the requested outcome requires a transition outside that set, lifecycle planning fails rather than silently skipping it.
_Avoid_: Best-effort mode, lifecycle hint

**Configure-only lifecycle**:
A lifecycle run that reconciles configuration without creating or starting an LXC. Every targeted LXC must already be running or the run fails at the lifecycle planning barrier.
_Avoid_: Best-effort configuration, start-and-configure

**Provision-only lifecycle**:
A lifecycle run that reconciles LXC existence and managed host configuration without guest configuration. It starts an LXC when creating or rebuilding it but preserves the stopped state of an existing LXC.
_Avoid_: Ensure-running lifecycle, guest configuration

**Full lifecycle**:
A lifecycle run that reconciles both LXC infrastructure and guest configuration. It may start an existing stopped LXC because guest configuration requires the LXC to be running.
_Avoid_: Provision-only lifecycle, configure-only lifecycle

**Browser device**:
One LXC holding one Chrome profile, one authenticated identity, and one query at a time. A second browser device exists for a second identity, never for capacity.
_Avoid_: Crawler pool, browser worker, headless browser

**Origin firewall**:
The in-guest port allowlist that restricts declared TCP ports to loopback and exactly one inventory host. Any LXC can consume it through `config/lxc_origin_firewall`. It is enforced inside the guest, so it does not replace host-level segmentation.
_Avoid_: Workstation firewall, host firewall, Proxmox firewall

**Workstation setup marker**:
The record written by a completed workstation setup run, holding the identity of the inputs that run applied. It is the authority consulted before any work begins, so an input the marker does not record is an input no later run can detect a change to.
_Avoid_: Completion flag, sentinel file, done marker

**Workstation tool readiness**:
The proof that the workstation's required commands are present, runnable, and resolved from their managed locations. It says nothing about which declared configuration produced those commands.
_Avoid_: Environment healthy, validated environment, workstation configuration freshness

**Workstation configuration freshness**:
Whether the workstation's active Home Manager generation was built from the currently checked-out dotfiles source. It is evaluated against the local checkout only, never against the remote, and it is independent of workstation tool readiness — working tools prove nothing about it.
_Avoid_: Drift, environment health, in sync with origin

**Fresh-worktree preparation**:
The command-surface guarantee that every supported non-live workflow is directly invocable from a fresh checkout and owns reconciliation of its worktree dependencies. It requires no separate user-visible preparation step, does not provision machine prerequisites, and does not grant live-operation capability.
_Avoid_: Development readiness, handoff readiness, workstation setup

**Locked-environment reconciliation**:
An optional targeted operation that eagerly materializes or repairs the worktree's locked Python environment without running a consuming workflow. The repository may declare compatible launcher requirements while the machine supplies and selects the launcher; reconciliation is never required sequencing for another supported workflow.
_Avoid_: Fresh-worktree preparation, mandatory setup

**Supported non-live workflow**:
A repository-supported development or validation operation that does not cross the live-operation boundary. It semantically owns reconciliation of its worktree dependencies and may require documented machine or environmental conditions, but another user-visible workflow is never its hidden prerequisite.
_Avoid_: Credential-free workflow, offline workflow

**Workflow prerequisite**:
A machine or environmental condition that a supported workflow checks when invoked rather than worktree state the workflow owns. Its absence is reported meaningfully distinctly from a candidate failure, without implying a repository-wide error taxonomy.
_Avoid_: Readiness state, preparation layer

**Workflow dependency**:
A worktree-owned collection or external role semantically consumed by one supported workflow, which owns reconciling it under the governing dependency policy. Shared storage, declarations, or implementation do not make unrelated dependencies part of that workflow's contract.
_Avoid_: Bootstrap dependency, controller prerequisite

**Live-operation boundary**:
The transition at which a workflow uses real credentials or controller identity to interact with managed infrastructure or other live mutable state. Crossing it is a distinct user intent from fresh-worktree preparation.
_Avoid_: Deployment readiness, worktree readiness

**Control node**:
A managed LXC holding the fleet key and vault passphrase from which `./run.sh` runs against managed hosts. There are two; a lifecycle run skips the control node it runs on unless it includes it deliberately.
_Avoid_: Controller machine, dev machine

**Controller SSH identity**:
The machine-global SSH key pair shared by this controller's worktrees and trusted by the managed fleet. A missing key requires an onboarding-or-recovery decision because creating a new identity and restoring an existing trusted identity are different intents.
_Avoid_: Worktree SSH key, bootstrap artifact

**Controller identity transition**:
An explicitly authorized creation, restoration, or enrollment of a controller SSH identity. Ordinary live workflows may verify identity and trust but never infer authorization for one transition from missing or untrusted identity.
_Avoid_: Dependency reconciliation, automatic key repair

**Identity enrollment**:
An explicitly invoked transition that establishes trust for a selected controller SSH identity on named managed infrastructure. Ordinary inspection or deployment does not authorize enrollment, except that creating or rebuilding a guest may install the already selected identity as part of that authorized effect.
_Avoid_: SSH prerequisite repair, automatic trust setup

**Live credential requirement**:
The credential material and authority semantically consumed by one live workflow. Inventory layout or incidental startup behavior must not impose unrelated credentials on that workflow.
_Avoid_: Global live readiness, controller bootstrap prerequisite
