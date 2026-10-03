# Use self-hosted Renovate for stack image updates

Stack image updates are proposed by Renovate, self-hosted on the `devserver`
LXC and run weekly by a systemd timer, instead of the custom planning pipeline
specified in #96. Renovate scans the GitHub default branch, opens one PR per
stack folder, and owns PR refresh, closure, deduplication and the Dependency
Dashboard. Merging a PR is the update decision; deploying it is still
`./run.sh`. Decided in #298, built in #453 after #429 deleted the old pipeline.

The custom pipeline was rejected because nearly all of its specified surface
(plan files, checksums, issue lifecycle, change classification) re-implemented
what Renovate already does, and none of it existed yet.

## Accepted trade-offs

- A GitHub token with write access to this repository lives in the vault and
  on a homelab LXC.
- Proposals are PRs that change files. There is no draft or resumable plan.
- Risk grading is patch, minor and major plus package rules, not a custom
  routine, low-confidence and assisted classification.
- Floating tags such as `latest` become `latest@sha256:...` rather than a
  readable version. Switching an image to a real version tag is the remedy.
- Scans run weekly, not only on demand. A deploy of `devserver` also runs one.
- Release notes appear in the PR for a person to read. Nothing assesses them.

## Rules that follow

**Vendor marker.** A vendor stack's `compose.yaml` is upstream's file
byte-for-byte below a first line `# vendor: <url>`. The URL is versioned when
upstream publishes a versioned file (Immich release assets) and unversioned
when it does not (Authentik publishes only `https://docs.goauthentik.io/compose.yml`).
The version pin lives in the stack's `.env.j2`, where a Renovate regex manager
bumps it, and a post-upgrade task (`scripts/vendor-sync.sh`) re-downloads the
marker URL into the same PR. The strict proof against an upstream commit that
#96 specified is dropped: the upstream URL is trusted. Upstream formatting
fails the lint gate, so each vendored path is excluded in `.ansible-lint` and
`.yamllint` rather than reformatted. Renovate does not edit images inside a
vendored file; they change only with upstream's file.

**Foundational hold.** Every update under `stacks/auth/` and `stacks/portal/`,
of any type, waits for a tick on the Dependency Dashboard, because a bad
Authentik or Traefik bump takes every other service down with it. Database
majors are held the same way, because they need a dump and restore. An
assisted stack, one whose upgrade needs a runbook, is held with a note linking
the runbook.

Nothing merges automatically. Application majors open as PRs labelled `major`
once the release is 14 days old.
