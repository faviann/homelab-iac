# Per-LXC deployment provenance

This project does not stamp LXCs with the `homelab-iac` revision that created
or last converged them, whether that stamp lives in the Proxmox description, in
a guest-local file, or in a history ledger built from those stamps.

## Why this is out of scope

The motivation was speed: a whole-fleet redeploy after a small change should
skip the stacks and LXCs that did not change. Provenance cannot deliver that.
A commit SHA identifies the whole repository, not the inputs of one stack.
Stack output also depends on inventory variables, vault values, role and
template code, and uncommitted worktree files, so a clean path history for
`stacks/<host>/<stack>/` does not prove the stack is unchanged.

Skipping would need a separate identity: a digest of the rendered stack inputs,
stored per stack. Even that saves little. `docker compose up -d` already leaves
unchanged services running, so the only gain is Ansible task overhead inside
stack sync. The other configure roles still run. The existing fast path for a
one-stack change is `./run.sh --limit <host> --stack <stack>`.

The secondary benefit, knowing whether a host runs code from `main`, does not
pay for its cost while deployment is manual. Rerunning `./run.sh --limit <host>`
from `main` answers the question by converging the host. The stamp would add a
Proxmox write path to the lifecycle core, parsing to preserve the generation,
idempotence-test exemptions because every run reports `changed`, and a
permanent semantic contract for later consumers.

If deployment becomes automated, with one scheduled runner deploying `main`,
that runner owns the deployment record. It records each run's time, revision,
and per-host lifecycle result in one place. Per-container stamps are a
workaround for many deployers with no central record, and are not needed
there. One exception remains: if a scheduled run keeps reverting hosts that
were deliberately deployed from a branch, the runner needs a narrow way to
recognize that state. Design that need when it happens. Do not reopen this
concept to solve it.

To improve run time, measure first. Enable a timing callback such as
`profile_roles` for one full run and optimize where the time actually goes.

## Prior requests

- #182 — "Stamp successful LXC deployments with Homelab-IaC provenance in Proxmox"
- #183 — "Mirror LXC deployment provenance inside the guest"
- #184 — "Track LXC deployment history and expose fleet provenance status"
