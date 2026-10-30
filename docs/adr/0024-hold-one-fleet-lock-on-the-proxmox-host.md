# Hold one fleet lock on the Proxmox host

Each control node's lifecycle lock was machine-local, and ADR-0022 coordinated
only the workstation and the bootstrap node, by reading each other. A laptop
run and a workstation run could configure the same LXC at once, and the
nightly deploy could start beside a laptop run. Now every exclusive live
operation, on every control node, holds one lock on the Proxmox host for its
whole run. Specified in #677.

This decision supersedes
[ADR-0022](0022-take-the-local-lock-then-read-the-other-control-node.md). It
amends [ADR-0009](0009-split-live-execution-locks-by-operation-class.md),
which left different control nodes uncoordinated, and
[ADR-0019](0019-deploy-every-lxc-nightly-from-the-bootstrap-node.md), which
rejected a shared lock and gated the nightly deploy on the workstation.

## The rule

An exclusive live operation is every mutating `./run.sh` and
`./recover.sh ssh-keys`. After it takes the machine-local lock, it opens an SSH
session to `proxmox.lan` with the fleet key and takes
`/run/homelab-lifecycle.lock` there with `flock --nonblock`. It writes
`<hostname> pid <pid> since <utc>` to `/run/homelab-lifecycle.holder` and keeps
the session open until `ansible-playbook` exits. Every control node takes this
fleet lock, the bootstrap node included.

- When another run holds the fleet lock, the run prints
  `proxmox: busy (a lifecycle run from <holder> is in flight); this run not started`
  under the busy-check deferral header and exits `3`. `--interrupt-busy` does
  not skip the fleet lock. It consents to interrupting a busy target, never to
  two runs changing one LXC at once.
- When the Proxmox host is unreachable or untrusted, the run prints
  `proxmox: lock check failed (<reason>); this run not started` and exits `1`.
  A trust failure names `./recover.sh proxmox-host-ssh`.

`./recover.sh proxmox-host-ssh` takes only the machine-local lock, because it
enrolls the trust the fleet lock needs. Shared operations take no fleet lock.

The bootstrap node keeps `/run/homelab-deploy.lock`. It stops two deploys from
moving the node's checkout at once, and the node's busy probe reads it. Reusing
it as the fleet lock would make the bootstrap node read busy during every run.

## Why the Proxmox host

Every lifecycle run already reaches `proxmox.lan` as root with the fleet key,
and stops when Proxmox SSH trust is missing. Failing closed there costs nothing
a run did not already need. One lock replaces the `bootstrap` hostname case,
the copied bootstrap busy command, and ADR-0022's fail-open read. It also
covers two runs ADR-0022 left uncoordinated: a `workstation-deploy@` unit
during `./run.sh --include-controller`, and a `workstation-deploy-interrupt@`
unit that reboots the workstation during a workstation run.

ADR-0019 rejected a shared lock because a dead holder strands it. That holds
only for a client that vanishes silently. When the control node's `ssh` dies,
even from `kill -9`, its connection closes, and the lock was free within one
second in a test. A power loss, a network drop, or a suspend leaves the
connection open until TCP keepalive drops it. Proxmox runs with
`ClientAliveInterval 0` and a `tcp_keepalive_time` of 7200 seconds, so that
takes about 7875 seconds, assuming the kernel's default of 9 probes 75
seconds apart.

[ADR-0018](0018-run-interrupting-workstation-changes-from-the-bootstrap-node.md)
is unaffected. It rejected the Proxmox host as executor, which would put a
repository, a venv, and secrets there. The fleet lock puts only a lock file
and a holder record there. The session records Proxmox's host key on first use
into the fleet `known_hosts` and checks it strictly afterward, the
trust-on-first-use that
[ADR-0021](0021-pin-fleet-host-keys-through-proxmox.md) names for a new control
node.

## Decisions

1. **A laptop may run `./run.sh` against the fleet.** It is never a managed
   target. It stays out of the inventory, and the operator sets it up by hand.
   The fleet lock makes a run from any control node safe, so refusing mutating
   runs off the workstation and the bootstrap node would only remove a working
   path.
2. **The nightly deploy has no workstation gate.** ADR-0019's gate decided
   whether another control node may run against the same LXCs. The fleet lock
   now decides that for every control node, and the lifecycle's own busy probe
   still protects agents before it interrupts the workstation. An agent's
   `./run.sh` exits `3` while the nightly deploy runs.
3. **A stranded lock is rare, and a person breaks it.** Only a person runs
   `fuser -k /run/homelab-lifecycle.lock` on the Proxmox host.
4. **sshd on the hypervisor stays unchanged.** A `ClientAliveInterval` drop-in
   would free a stranded lock sooner, but a suspended laptop would then resume
   without the lock beside a newer run. That turns a safe stranded lock into a
   silent collision. Accepted cost: a client suspended longer than about
   2h11m also resumes without the lock, once TCP keepalive drops its session.

## Boundaries

- The stack-rename recipe keeps its machine-local `flock`, so a run from
  another control node can start during a rename.
- A signal to the wrapper alone, such as `kill -9 <pid>`, does not release the
  lock while `ansible-playbook` runs. Ctrl-C reaches the SSH session too.
  The lock ends when `ansible-playbook` exits. A run does not notice a lock
  that drops mid-run.

## Accepted costs

- A stranded lock blocks every exclusive run on every control node for up to
  about 7875 seconds, unless a person breaks it.
- A nightly deploy that defers on the fleet lock has already moved its
  checkout, so its notification names a commit it did not deploy.

## Rejected

- **Reading every other control node**: the bootstrap node cannot reach a
  laptop, and every new control node adds a read on each of the others.
- **Reusing `/run/homelab-deploy.lock`**: the bootstrap node's busy probe reads
  it, so the node would read busy during every run.
