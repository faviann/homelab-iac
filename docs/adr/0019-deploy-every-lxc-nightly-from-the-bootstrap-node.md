# Deploy every LXC nightly from the bootstrap node

Only the workstation got merged changes on its own. Every other LXC got them,
with package upgrades and pending reboots, only when someone ran `./run.sh`
against it. The bootstrap node's timer now starts the **nightly deploy**: a
lifecycle run at `origin/main` against every managed LXC except the bootstrap
node, which the workstation keeps deploying. Specified in #539.

This decision amends
[ADR-0018](0018-run-interrupting-workstation-changes-from-the-bootstrap-node.md):
runs from the bootstrap node are no longer `--limit workstation` only, and its
standing consent through the nightly timer now covers every LXC.

## Standing consent

faviann installed the timer, so the nightly deploy is consent granted once, in
advance, for a full lifecycle run every night. It never passes
`--interrupt-busy`. Busy stacks and hosts defer as in any run, and the
workstation's interrupting steps still wait for its busy probe inside the
lifecycle, so ADR-0018's consent rule is unchanged. A person may start the unit
by hand at a pushed SHA, for verification or when recovery needs the other LXCs
patched. Agents never start it: their on-request runs stay on the workstation,
where the output streams to them.

## The gate

The lifecycle lock is machine-local (#174). A nightly deploy and an agent's run
on the workstation could configure the same LXC at once, and neither would
report anything wrong. So before the deploy lock and the checkout, the unit
asks the workstation busy probe over SSH, the way the lifecycle reaches LXCs,
with a 30-second bound. Only an idle answer lets the night run. Busy, meaning
an agent is mid-turn or a run holds the workstation's lifecycle lock, defers the
whole night. Any other answer, an SSH failure included, defers it as a failed
check: a gate that cannot read the workstation never authorizes a run that
could collide. A deferred night prints its reason under the busy-check deferral
header and exits `3`, so the notifier reports it unchanged.

ADR-0018 rejected the probe in the timer wrapper for the interrupt decision,
which the lifecycle makes with the same probe right before the interruption.
The gate makes a different decision: whether another control node may run
against the same LXCs, which the lifecycle cannot see. The probe stays where it
is for the interrupt decision.

## The residual window

The gate reads the workstation once, at 03:00. An agent run started on the
workstation while the nightly deploy is in progress can still configure the
same LXC. The window lasts the whole run, and a collision is silent. That is
unlike ADR-0018's window between the probe and the reboot, which is minutes
long and visible. #174 stays open for it.

## Accepted costs

- A broken `main` reaches every host up to the first failure each night.
- A planning problem on any one host stops actions on every host that night,
  as the planning barrier does in any run.
- The workstation is last in inventory, so any earlier failure leaves it
  undeployed that night.
- A failed night does not print its busy-check deferrals: the wrapper prints
  them only after a successful run.
- LXCs that need a reboot after their upgrade reboot at 03:00, and stacks
  without a busy check are recreated when their files changed.
- If agents are working at 03:00 most nights, the other LXCs go stale. The
  Discord streak of deferred nights is the signal.

## Rejected

- **A lock both control nodes share**: `flock` is safe because the kernel
  releases it when its holder dies, and that does not survive being held across
  SSH. A dead holder strands the lock (#174).
- **Proceeding when SSH to the workstation fails**: a gate that cannot read the
  workstation would authorize exactly the run that could collide, and a broken
  gate, such as a changed host key after a rebuild, would go unnoticed.
- **The timer passing `--interrupt-busy`**: the flag would no longer mean that a
  person consented.
- **Validating on the node before deploying**: validation gives the same
  result for a given commit whenever it runs, so running it at 03:00 only
  repeats what belongs before merge. Gating `main` on validation is a separate
  decision.
- **A second timer for the workstation**: two timers at 03:00 collide on the
  deploy lock, and pausing scheduled deploys would take two commands.
