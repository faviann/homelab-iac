# Use self-hosted Renovate for stack image updates

Stack image updates are proposed by Renovate, self-hosted on the `devserver`
LXC as a long-running service, instead of the custom planning pipeline
specified in #96. Renovate scans the GitHub default branch, opens one PR per
stack folder, and owns PR refresh, closure, deduplication and the Dependency
Dashboard. Merging a PR is the update decision; deploying it is still
`./run.sh`. Decided in #298, built in #453 after #429 deleted the old pipeline.

The custom pipeline was rejected because nearly all of its specified surface
(plan files, checksums, issue lifecycle, change classification) re-implemented
what Renovate already does, and none of it existed yet.

The service runs Renovate in a loop inside its own container every six hours,
and the weekly window is Renovate's `schedule` option in `renovate.json`
(Saturday, Montreal time). #453 specified a host systemd timer instead. The
loop was chosen so that everything lives in the stack folder and
`renovate.json`, with no host units to install or clean up later. Runs outside
the window only look up images, refresh the Dependency Dashboard and keep
existing PRs current; new branches and PRs open in the window, or at the next
run after a dashboard tick. A deploy or restart of the container triggers an
immediate run.

## Accepted trade-offs

- A GitHub token with write access to this repository lives in the vault and
  on a homelab LXC.
- Proposals are PRs that change files. There is no draft or resumable plan.
- Risk grading is patch, minor and major plus package rules, not a custom
  routine, low-confidence and assisted classification.
- Floating tags such as `latest` become `latest@sha256:...` rather than a
  readable version. Switching an image to a real version tag is the remedy.
- Scans run every six hours and open new PRs weekly, not only on demand.
- Release notes appear in the PR for a person to read. Nothing assesses them,
  and nobody reads them for an update Renovate merges.

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
vendored file; they change only with upstream's file. In particular, immich's
`ghcr.io/immich-app/postgres` is not held by the database-major rule: a
database image change arrives inside the immich version-pin PR, whose body
asks the reviewer to read upstream's compose diff and migration steps.

**Foundational hold.** Every update under `stacks/auth/` and `stacks/portal/`,
of any type, waits for a tick on the Dependency Dashboard, because a bad
Authentik or Traefik bump takes every other service down with it. Database
majors are held the same way, because they need a dump and restore. An assisted
stack, one whose upgrade needs a runbook, is held with a note linking the
runbook. Authentik patches are the one exception. They open at any time, with
no tick, and automerge once lint passes, because Authentik ships security
backports in patches. A bad patch can lock everyone out of most services until
someone reverts it. Renovate offers a patch only while it is the newest
Authentik release, so the unversioned upstream `compose.yml` that the vendor
sync downloads describes that patch. Once a newer minor ships, Renovate offers
the minor instead, held for a tick, and patches stop until someone takes it.
Authentik minors and majors stay held.

**Automerge.** Renovate merges digest pins, digest updates and patches once
lint passes, and the nightly deploy ships them. Nobody reads their release
notes or runs the new image first. There is no release-age wait, because
Renovate can only count from a registry release date, and most automerged
images, every `lscr.io` one among them, have none. The next release fixes a bad
one, or a revert of the merge commit restores the previous image reference.
`platformAutomerge` is off because `main` has no required checks, and GitHub's
auto-merge would not wait for lint. A group PR merges only when every update in
it qualifies. Minors stay PRs for a person, because upstreams ship breaking
changes in minors, as Seerr did in 3.3.0 and 3.5.0. Every other update held for
a tick, and every other vendor version pin, waits for a person. On 2026-10-18
this paragraph replaced "Nothing merges automatically".

**Undated majors.** Application majors open as PRs labelled `major` once the
release is 14 days old, counted only when the registry reports a release date.
Renovate's default holds an undated update forever, so the majors rule sets
`minimumReleaseAgeBehaviour` to `timestamp-optional`, and an undated major
opens at once.
