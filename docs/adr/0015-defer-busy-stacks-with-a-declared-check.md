# Defer busy stacks with a declared check

A lifecycle run can interrupt any container: `docker compose up -d` recreates
changed services, quarantine runs `docker compose down`, Docker runtime changes
or a package upgrade can restart the Docker daemon, and a reboot or host-side
reconciliation restarts the LXC. A stack that runs long jobs can now declare an
`x-busy-check` in its repo Compose file. Before any of those steps, the run
executes the declared command inside the named service. Exit `0` means idle.
Anything else defers the stack for that run.

The check is opt-in and declared in the repository. Declarations are read on
the controller from the stack source, so a stack or host without one costs no
remote command and behaves exactly as before. A stack opts in by having a
line that starts with `x-busy-check:` in a Compose file or template. A stack
without one is not parsed for a busy check, so a broken Compose file in it
still fails the run as it did before, rather than being deferred. A stack
removed from the repository takes its declaration with it, so quarantine can
stop it even while busy. Keeping the declaration beside the services it checks
was preferred over host variables, which would drift from the stack.

The check fails closed. Exit `1` means busy, and so does any outcome the run
cannot read as idle, a malformed block included. Stack validation and the run
share one parser, so a block in a `.j2` template or in both the base and
override Compose files is rejected by `./validate.sh stack` and defers its stack
at runtime. Neither side can read a declaration the other ignores or reads
differently. An unknown answer must not authorize an interruption. The one
exception is a Compose project with no containers. Nothing runs that could be
interrupted, so that stack deploys normally.

A busy stack is skipped whole: no file sync, no `compose up`, no quarantine.
Syncing files without restarting would leave the files on disk out of step with
the running containers. The host's interrupting steps are skipped too:
host-side reconciliation, Docker and NVIDIA runtime configuration, the package
upgrade, and the reboot. Host-side reconciliation and runtime configuration are
skipped entirely rather than only their restarts, because each derives the need
to restart from changes made in the same run, and a skipped restart would be
lost. Other stacks and hosts still converge. `./run.sh` exits `3` when a
successful run deferred anything, so a scheduled caller can tell "retry later"
from success and failure without parsing logs.
`./run.sh --interrupt-busy` skips the checks for a deliberate interruption.

The check is a command, not a URL. A command covers an app with an HTTP status
endpoint through `curl` or similar, and also covers apps with only a lock file
or a CLI. A URL field would cover only the first.

A job can start between an idle answer and the interruption. That race is
accepted. Closing it needs the app to take a lease or drain on request, and the
run never waits for a busy stack to become idle.
