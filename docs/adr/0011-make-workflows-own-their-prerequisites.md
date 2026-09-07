# Make workflows own their prerequisites

Every supported non-live workflow is directly invocable from a fresh checkout
and reconciles the worktree dependencies it semantically consumes, itself or
through shared internal machinery. Machine prerequisites are checked when the
workflow runs, and their absence is reported as an environmental problem; no
mandatory worktree-preparation journey or hidden warm-up sequence exists.

Crossing into managed infrastructure is a separate user intent. A live workflow
requires only the dependencies, credentials, controller identity, and trust that
it semantically consumes, and it may verify but must not silently create,
restore, replace, or enroll controller identity. Identity creation, recovery,
and enrollment remain explicit transitions because they affect different
authoritative state.

The public `bootstrap` operation and the no-argument guided `setup.sh` journey
are retired because their grouped responsibilities have no shared user intent or
authorization boundary. `./setup.sh sync` remains as an optional locked Python
environment repair or eager-reconciliation operation; bare `./setup.sh` is
invalid usage and synchronization is never prerequisite sequencing for another
supported workflow.

This decision preserves shared implementation where useful but rejects shared
implementation, storage, or declarations as evidence of shared semantic
ownership. It also avoids introducing readiness tiers, per-workflow dependency
manifests, a repository-wide prerequisite taxonomy, or replacement setup
functionality without a demonstrated user decision that needs them.
