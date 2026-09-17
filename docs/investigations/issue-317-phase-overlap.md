# Issue 317: lifecycle and pytest phase-overlap evidence

Status: experiment-only report for [homelab-iac #317](https://github.com/faviann/homelab-iac/issues/317).

Revision under test: `dd1f82c4a709b28aab83a19ff6e6ff68deefc34f`. The repository
source and `validate.sh` orchestration were unchanged throughout this work.
The commands under test remain the supported boundaries in
[`validate.sh`](../../validate.sh); no permanent scheduling behavior is part
of this report.

## Executive result

The valid full overlap trial passed both complete gates:

| Phase | Command | Result | Polling-observed wall time |
| --- | --- | --- | ---: |
| Lifecycle | `./validate.sh lifecycle --full` | 25 launchers passed | 600.705s |
| Pytest | `./validate.sh tests` | 811 passed, 4 skipped | 1064.220s |
| Combined | both started as supervised siblings | both return code 0 | 1064.221s |

The historical same-revision sequential opportunity was 628.5s + 1130.4s =
1758.9s. The one valid overlap therefore observed 694.679s of opportunity,
39.5%, but this is not a repeatability estimate: there was one valid full
overlap trial, and the phase times were affected by cache/host warmness and
polling observation. The result supports a bounded follow-up implementation;
it does not justify claiming a stable 39.5% production saving.

The 50ms GitHub-reader termination probe was separately proven to overlap real
lifecycle work. It ran as a supported targeted pytest node while the full
lifecycle command was active, and passed.

## Baselines and no-argument handoff evidence

The baseline was retained rather than recreated solely for this experiment:

- #316 recorded lifecycle `--full` at 628.5s and pytest at 1130.4s on this
  revision.
- The retained #307 report at
  [`2c90e1e`](https://github.com/faviann/homelab-iac/blob/2c90e1e68edf21a1b0dbc45f77823b10474a187c/docs/investigations/issue-307-materialization-fixture-cost.md)
  records a successful no-argument `./validate.sh` handoff on this revision:
  lint passed, all 25 lifecycle launchers passed, and pytest reported 811
  passed / 4 skipped. Its whole pytest process took 1241.65s in that separate
  run. This report reuses that retained evidence; it is not a fresh
  no-argument run.
- #316 recorded the complete no-argument baseline as 1845.3s, including
  86.4s lint. Keeping lint serial, the overlap result projects to 86.4s +
  1064.221s = 1150.621s, or 37.6% below that historical full-handoff time.

The no-argument handoff requirement is therefore accounted for by retained
same-revision evidence, not by a mechanically repeated 30-minute handoff. The
overlap experiment itself ran the two phase commands separately so that phase
results and interference remained attributable.

Source records: [#316 handoff](https://github.com/faviann/homelab-iac/issues/316#issuecomment-5707335022),
[#307 handoff](https://github.com/faviann/homelab-iac/issues/307#issuecomment-5707451352),
[the retained #307 report](https://github.com/faviann/homelab-iac/blob/2c90e1e68edf21a1b0dbc45f77823b10474a187c/docs/investigations/issue-307-materialization-fixture-cost.md),
and the original [#317 publication](https://github.com/faviann/homelab-iac/issues/317#issuecomment-5714931851).

The original execution paths, before evidence was copied into this report,
were:

| Evidence | Original path |
| --- | --- |
| Isolated lifecycle | `/tmp/homelab-317/isolated-lifecycle/summary.json`, `phase.log`, `samples.csv` |
| Initial failed overlap | `/tmp/homelab-317/concurrent/summary.json`, `lifecycle.log`, `pytest.log`, `samples.csv` |
| Valid overlap | `/tmp/homelab-317/concurrent-bootstrap/summary.json`, `lifecycle.log`, `pytest.log`, `samples.csv` |
| Reader probe overlap | `/tmp/homelab-317/reader-probe-overlap/summary.json`, `lifecycle.log`, `github-reader-probe.log`, `samples.csv` |
| Bootstrap | `/tmp/homelab-317-bootstrap.log` |
| Persistent-home recovery | `/tmp/homelab-317/targeted-persistent-home.json`, `targeted-persistent-home.log` |
| Failure drill | `/tmp/homelab-317/failure-drill/summary.json` |
| Interruption drill | `/tmp/homelab-317/interrupt-drill/summary.json` |

The corresponding retained copies are under
[`issue-317-evidence/`](issue-317-evidence/), with the same summaries and raw
sampling/log content.

## Actual reader-probe overlap

The original full overlap log only showed the reader test late in pytest’s
collection order. A separate targeted run filled that evidence gap without
running another full pytest phase:

- Driver output: [`reader-probe-overlap/summary.json`](issue-317-evidence/reader-probe-overlap/summary.json)
- Lifecycle command: `./validate.sh lifecycle --full`
- Target command:
  `./validate.sh tests tests/unit/test_stack_update_policy_snapshot.py::test_github_reader_times_out_safely_and_terminates_gh`
- Lifecycle: started `2026-09-17T13:26:09.214697Z`, finished
  `2026-09-17T13:37:02.550090Z`, return code 0, all 25 launchers passed.
- Reader probe: started `2026-09-17T13:26:19.925407Z`, finished
  `2026-09-17T13:26:22.916696Z`, return code 0; its log reports `1 passed in
  0.21s`.

The probe began 10.710710s after lifecycle launch and finished 639.633394s
before lifecycle finished. It therefore overlapped active lifecycle work for
the complete approximately 2.991s probe interval. This was a full lifecycle
plus one short supported target, not a replacement full phase-overlap trial.

The retained lifecycle log is
[`reader-probe-overlap/lifecycle.log`](issue-317-evidence/reader-probe-overlap/lifecycle.log),
the targeted output is
[`reader-probe-overlap/github-reader-probe.log`](issue-317-evidence/reader-probe-overlap/github-reader-probe.log),
and the sampler is
[`reader-probe-overlap/samples.csv`](issue-317-evidence/reader-probe-overlap/samples.csv).

## Pressure, isolation, and timing limits

For the valid full overlap trial, the temporary sampler observed:

- load maxima 11.28 / 6.93 / 6.15 for load 1/5/15 on a 16-core host;
- minimum `MemAvailable` 57.76 GiB and no swap;
- maximum sampled validation descendants 91 processes / 2177.97 MiB RSS;
- Docker running count 2 before and after, peaking at 6 during Docker tests;
- no log-reported fixed-name/port conflict, cache collision, diagnostic
  corruption, or Docker residue.

The sampler nominally slept for five seconds, but its observed valid-trial
sample intervals ranged from 5.073109s to **9.241888s**. All elapsed values
and pressure extrema in this report are therefore polling observations, not
five-second hard precision. The reader-probe sampler used a different short
run and is not used to refine the historical full-trial timings.

Concurrent disk-stat deltas were not captured. The isolated lifecycle wrapper
did record 512 block inputs and 700,539 block outputs, but that is not a
concurrent I/O measurement. The valid overlap logs showed no I/O error or
obvious saturation symptom; the absence of a direct concurrent I/O counter is
an evidence limitation.

The isolation model comes from the source: `validate.sh` creates an invocation
local cache, and [`run_lxc_lifecycle_regressions.py`](../../tests/regression/run_lxc_lifecycle_regressions.py)
replaces it with a per-run lifecycle cache. The timing-sensitive lifecycle
lock/metadata and readiness-deadline launchers, materialization and
persistent-home regression items, Docker tests, and pytest’s GitHub-reader
termination test all passed in their applicable runs.

## Initial failure and recovery

The first full overlap attempt is retained as an environment-readiness result,
not counted as a valid concurrency trial:

- Original summary: [`initial-failed-overlap/summary.json`](issue-317-evidence/initial-failed-overlap/summary.json)
- Original pytest log: [`initial-failed-overlap/pytest.log`](issue-317-evidence/initial-failed-overlap/pytest.log)
- Lifecycle still passed; pytest returned 1 because `ansible.posix.mount` was
  unavailable in the clean controller environment.
- Preserve the original summary verbatim even though its `failure_seen` field
  is `false`. The original polling loop could observe the last child as
  already exited in the `while` condition, skip the loop body, and then record
  final return codes in `finally` without updating that flag. The named final
  return codes and the retained pytest failure log are authoritative; this is
  an instrumentation defect, not evidence that the pytest phase passed.
- The declared recovery was `./setup.sh bootstrap`; its retained output is
  [`bootstrap-targeted/bootstrap.log`](issue-317-evidence/bootstrap-targeted/bootstrap.log).
- The supported targeted recovery command was
  `./validate.sh tests tests/regression/test_workstation_persistent_home.py`;
  it passed 1/1 in 220.243s. Summary and output are
  [`targeted-persistent-home.json`](issue-317-evidence/bootstrap-targeted/targeted-persistent-home.json)
  and [`targeted-persistent-home.log`](issue-317-evidence/bootstrap-targeted/targeted-persistent-home.log).
- The replacement valid full overlap is retained under
  [`valid-overlap/`](issue-317-evidence/valid-overlap/).

This distinguishes a missing controller dependency from phase interference
without spending another full pytest trial.

## Driver provenance and cleanup boundary

The historical 637.841s isolated lifecycle result and the historical
1064.221s full overlap result were produced by temporary inline Python
supervisors invoked with `uv run --locked python -`; their exact output paths
are retained below. The full-overlap supervisor started each command in its
own process group, polled both processes, and wrote the summaries shown here.
It did not catch SIGINT/SIGTERM, and its interruption path re-raised before
writing a summary. Therefore the historical full-trial driver does **not**
establish interruption safety.

The later full-lifecycle reader-probe run used the then-present temporary file
`/home/faviann/worktrees/homelab-iac/issue-317/docs/investigations/issue-317-phase-overlap-driver.py`
at launch. That source was not retained as a tracked file after the run; it is
not reconstructed or decompiled here. Its output and command/timestamp record
are retained under [`reader-probe-overlap/`](issue-317-evidence/reader-probe-overlap/).
The small committed drill script
[`issue-317-interruption-drill.py`](issue-317-interruption-drill.py) is a later
drill harness and did not produce either historical timing result.

The drill script was exercised in two short cases:

- [`drills/failure-drill.json`](issue-317-evidence/drills/failure-drill.json):
  `failing-child` returned 7, the sibling returned 143 after SIGTERM, both
  were awaited, and no child process group remained.
- [`drills/interruption-drill.json`](issue-317-evidence/drills/interruption-drill.json):
  the driver caught SIGTERM, both named children returned 143, both were
  awaited, and no child process group remained.

These drills establish attributable handling and draining of child process
groups started by the drill. They do **not** establish cleanup of real
validation fixture sessions, temporary roots, Ansible caches, or Docker
resources after forced interruption. The retained valid full-trial summary is
[`valid-overlap/summary.json`](issue-317-evidence/valid-overlap/summary.json);
its cleanup action list is empty because both phases completed normally.

## Bounded recommendation

Keep #317 experiment-only and implement no scheduler here. A later follow-up
may overlap the existing lifecycle-full and pytest commands while keeping lint
serial, but its failure contract should be bounded to what this evidence
supports:

1. start both real phases with separate logs and status records;
2. retain both phase results and drain already-started real phases after a
   failure, rather than abandoning the sibling or reporting only first-`wait`;
3. preserve the current fact-cache isolation and controller readiness boundary;
4. do not claim that forced interruption cleans fixture-created sessions,
   temporary caches, or Docker resources until a separate experiment measures
   those resources;
5. leave pytest worker parallelism (#318) and lifecycle launcher parallelism
   (#319) out of this change.

This is an evidence-backed implementation direction, not a merge decision or
a claim of repeatable production savings. No permanent validation behavior was
changed in this report.
