# Take the local lock, then read the other control node

Each control node serialized only its own runs. The nightly deploy read the
workstation busy probe before it took the deploy lock, and a workstation run
never read the bootstrap node. So a workstation run started after 03:00 could
configure LXCs alongside the nightly deploy, and nothing reported the
collision. Specified in #174.

This decision amends
[ADR-0019](0019-deploy-every-lxc-nightly-from-the-bootstrap-node.md): the gate
now reads the workstation after the deploy lock, and the residual window that
ADR named is closed.

## The protocol

Each control node takes its own lock first, then reads the other node, and
backs off when the other is busy. The workstation takes its lifecycle lock at
t1 and reads the bootstrap node at t2. The bootstrap node takes its deploy lock
at t3 and reads the workstation at t4. Both proceed only if each read found the
other free, so t2 < t3 and t4 < t1. With t1 < t2 and t3 < t4, that gives
t1 < t2 < t3 < t4 < t1, which cannot hold. At least one side always backs off.

Any other control node, such as a laptop, takes the workstation's side: it
takes its own lifecycle lock, then reads the bootstrap node. The nightly deploy
reads only the workstation, so for a laptop only the first half holds. A laptop
run backs off from a deploy in flight, but a deploy that starts during a laptop
run does not see it.

Both may back off in the same second. That costs one night and one retry, and
it is safe. No lock is held across SSH, so ADR-0019's rejection of a shared
lock stands.

## The two sides

On every control node but the bootstrap node, every exclusive live operation
reads the bootstrap node after it takes the lifecycle lock and before it
reconciles dependencies. That is every mutating `./run.sh` and every
`./recover.sh`. It runs the bootstrap
node's own busy command over SSH with the fleet's trust options. Busy prints
`bootstrap: busy (a deploy is in flight); this run not started` under the
busy-check deferral header and exits `3`, and nothing else runs.
`--interrupt-busy` does not skip the read. It consents to interrupting a busy
target, never to two control nodes changing one LXC at once.

The read runs on every host except the one named `bootstrap`. On the
bootstrap node, `./run.sh` runs inside a deploy that holds the deploy lock, so
the same read there would find that lock and refuse every deploy. The read
first ran only on the host named `workstation`, so a run from a laptop never
read the bootstrap node.

On the bootstrap node, `homelab-deploy --when-workstation-idle` reads the
workstation busy probe once it holds the deploy lock, before git touches the
checkout. Only the nightly unit passes the flag. Its deferral lines and exit
`3` are unchanged.

## Failing open on one side

When a control node cannot read the bootstrap node, the run prints
`bootstrap: check failed (<reason>); this run proceeds` and continues. The
workstation creates and repairs the bootstrap node with
`./run.sh --limit bootstrap`, so failing closed would lock out that repair.
SSH reports a host-key failure the same way as an unreachable node, so that
proceeds too. The warning repeats on every run until a run that targets the
bootstrap node pins its key again. The nightly gate stays fail-closed, as
ADR-0019 decided.

The nightly read now checks the workstation's host key against the node's
copy of the fleet `~/.ansible/known_hosts`, as the lifecycle does, instead of
accepting a new key into root's own file. After a workstation rebuild, every
night defers as `check failed` until a run pins the new key on the node: a
`workstation-deploy@` unit, or a workstation run that configures the
bootstrap node.

## Probes that take the lock they read

Both busy probes take the lock they read, for an instant. A deploy that started
in that instant lost its lock and exited `75`. `homelab-deploy` now waits up to
one second for its lock, which outlasts any probe. A real second deploy still
exits `75`, after that second. The workstation probe keeps the mirror race: a
workstation command started in the same millisecond as the nightly's one probe
exits `75`, and a retry succeeds.

`/proc/locks` and `lslocks` cannot replace the probes. Inside the container
they omit a `flock` whose `flock(1)` process has exited, which is how both
nodes hold their locks.

## Accepted costs

- `scripts/lib/live-execution.sh` carries the `bootstrap` hostname and a copy
  of the bootstrap node's busy command. Tests pin that copy to the inventory,
  and the inventory's lock path to `homelab-deploy`.
- Every mutating run on a control node but the bootstrap node waits up to 10
  seconds more while the bootstrap node is down.
- Lifecycle locks are machine-local, so a laptop run and a workstation run do
  not see each other and can configure the same LXC at once.
- `./recover.sh` can now exit `3`.
- A `workstation-deploy@` unit started during the nightly's read waits one
  second, then exits `75`.
- A `workstation-deploy@` unit started while a `./run.sh --include-controller`
  runs on the workstation is still not coordinated. The reverse order now
  defers.

## Rejected

- **A check inside the lifecycle playbook**: Ansible cannot end a whole run
  with status `0`. The check would also run only after dependency reconcile
  and the prerequisite plays, and `--interrupt-busy` would skip it.
- **A read-only probe that scans `/proc/<pid>/fdinfo`**: it removes the race on
  both nodes, but it adds an installed script and a probe rewrite. The
  one-second wait removes the consequence that matters, a lost night.
- **A peer file written by the workstation baseline**: it is one more
  installed artifact, and the check stays off until the first configure after
  a rebuild.
- **Failing closed on the workstation**: it locks out
  `./run.sh --limit bootstrap`, the only path that repairs the bootstrap node.
