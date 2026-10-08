# Run interrupting workstation changes from the bootstrap node

The workstation is both a control node and the place where agents work around
the clock. A lifecycle run that restarts it kills the run itself and every
agent turn in flight. A second control node, the `bootstrap` LXC, carries the
runs that interrupt the workstation, and the workstation deploys the bootstrap
node like any other LXC. Decided in #521, #523 and #525 under map #518, and
specified in #529.

## The consent rule

A run interrupts a working agent only when a person asked for it.

- **Host-level busy probe.** The workstation declares a busy probe in its host
  variables, beside the stack checks of
  [ADR-0015](0015-defer-busy-stacks-with-a-declared-check.md). The probe reports
  busy while a herdr pane is `working` or a run holds the workstation's
  lifecycle lock, idle when herdr is not running or not installed, and busy on
  any probe error. While it reports busy, a run defers the workstation's
  interrupting steps and exits `3`.
- **`--interrupt-busy` is the consent.** It skips the probe, and it is passed
  only on a person's explicit request.
- **Never in place.** An interrupting run never targets the host it runs on.
  `./run.sh` rejects `--include-controller` together with `--interrupt-busy`
  before any work. Behind that usage error, the lifecycle defers every
  interrupting step of a run that includes its own control node, without
  running the probe and whatever the override says. The deferral keys on the
  controller skip being off, so a raw run that turns the skip off can only
  defer more. It is not the alternative #521 rejected, ignoring the busy
  override for the run's own host, which fails later and more quietly, mid-run,
  with no usage error: the deferral does not read the override at all.
- **Consented runs go through the bootstrap node.** Consented interrupting
  runs, rebuilds, and recovery of an unreachable workstation run there, against
  `--limit workstation` only.

## Standing consent through the nightly timer

A timer on the bootstrap node runs the workstation lifecycle every night
without `--interrupt-busy`. faviann installed it, so it is consent granted once,
in advance, on a condition the probe checks: no agent mid-turn and no run in
flight. A night when the probe reports busy defers and says so.

#521 rejected an idle gate as consent: an idle agent is not consent, and the
agent requesting a run is itself `working`, so the gate never clears. The timer
narrows that rejection to agent-requested interrupting runs, where it still
holds. There it keeps a run that an agent starts from the bootstrap node
non-interrupting: the requester is working, so the probe never reads idle.

## The probe and ADR-0015

ADR-0015 kept busy checks in the stack's Compose file rather than in host
variables, because host variables drift from the stack they describe. The
workstation probe describes the host, not a stack, so there is no stack for it
to drift from. That reasoning does not apply here, and ADR-0015 stands for
stacks.

## Rejected

- **Check-first as consent**: a `--check` run cannot predict the reboot-required
  file that apt creates mid-run, and check mode skips busy checks.
- **An idle gate as consent for agent-requested runs**: see above.
- **Writing the configuration while skipping the reboot**: the next run sees the
  configuration already matches and silently forgets the restart.
- **Pushing the result back through herdr** (`herdr agent prompt`): pane ids
  change when herdr restores a session.
- **The Proxmox host as executor**: it puts a repository, a venv, and secrets on
  the hypervisor.
- **A sentinel busy stack**: the stack itself would never update, and with no
  running containers its check disappears.
- **The timer passing `--interrupt-busy`**: the flag would no longer mean that a
  person consented.
- **The probe in the timer wrapper**: the probe would live in two places, and
  probing before the run starts widens the window between the probe and the
  interruption.
- **Counting `blocked` panes as busy**: a forgotten permission prompt would block
  every night, and interrupting one costs one re-answer.

## Accepted trade-offs

- A person's run from the bootstrap node without `--interrupt-busy` restarts
  the workstation when the probe reports idle. A flag only the timer passes
  would avoid that; it was rejected as one more object.
- A job can start in the minutes between the probe and the end-of-run reboot.
- A red `main` at 18:00 ships at 03:00. Recovery is a run from the bootstrap
  node.
- Nightly restarts make losing Claude daemon sessions and `/tmp` routine.
