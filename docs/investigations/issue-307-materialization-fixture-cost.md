# Issue #307 — materialization-fixture cost by contract and setup phase

Status: investigation complete; evidence-backed retention recommendation. No production or test optimization is proposed for merge from this issue.

## Scope and revision

Evidence was collected from `dd1f82c4a709b28aab83a19ff6e6ff68deefc34f` on 2026-09-17. The worktree was clean at the start and after the disposable experiment. #306 is present: `00f09914e4d21273db44505bcb9eb2a223322875` is an ancestor of the baseline. It changes all six plays in the fixture to `gather_facts: false`, adds explicit invoking-user UID/GID lookups where needed, and does not change production role code or remove the recursive discovery setup. #296 remains the separate owner of deployment-report/classification simplification. #308 and #309 remain separate experiments.

The target test runs two sequential, independent subprocesses and roots: apply and `--check` ([`test_materialize_templates.py:19-49`](../../tests/regression/test_materialize_templates.py)). The fixture has six plays ([`stack_sync_materialize_test.yml:2-830`](../../tests/regression/fixtures/stack_sync_materialize_test.yml)):

1. wrong-type prerequisite setup, production failure, and rescue assertions;
2. synthetic Komf setup, production materialization, post-run assertions, and a repeated materialization for idempotency;
3. planner declaration/default metadata setup, production materialization, and metadata assertions;
4. exact repository artifact preparation and byte/declaration checks, with no production materialization;
5. exact Overmind discovery injection, production materialization, and assertions;
6. exact Servarr discovery injection, production materialization, and assertions.

## Measurement method and limits

Each mode was profiled alone through the repository boundary with a fresh temporary root. The exact disposable callback source is preserved in [`issue307_profile.py`](./issue307_profile.py). To reproduce the recorded shape, copy that file to the callback directory and run these two invocations separately. Bash’s built-in `time -p` wrapped each invocation and produced the reported wall/user/sys values.

```sh
mkdir -p /tmp/issue307_profile
cp "$PWD/docs/investigations/issue307_profile.py" /tmp/issue307_profile/issue307_profile.py

# apply
time -p env ANSIBLE_INVENTORY="$PWD/tests/fixtures/ansible/inventory.yml" \
    ANSIBLE_VAULT_PASSWORD_FILE="$PWD/tests/fixtures/ansible/vault-pass" \
    ANSIBLE_CALLBACK_PLUGINS=/tmp/issue307_profile \
    ANSIBLE_CALLBACKS_ENABLED=issue307_profile \
    uv run --locked ansible-playbook \
    tests/regression/fixtures/stack_sync_materialize_test.yml \
    -e "temp_root=<fresh-temporary-root>" -e "repo_root=$PWD"

# check
time -p env ANSIBLE_INVENTORY="$PWD/tests/fixtures/ansible/inventory.yml" \
    ANSIBLE_VAULT_PASSWORD_FILE="$PWD/tests/fixtures/ansible/vault-pass" \
    ANSIBLE_CALLBACK_PLUGINS=/tmp/issue307_profile \
    ANSIBLE_CALLBACKS_ENABLED=issue307_profile \
    uv run --locked ansible-playbook \
    tests/regression/fixtures/stack_sync_materialize_test.yml \
    --check -e "temp_root=<fresh-temporary-root>" -e "repo_root=$PWD"
```

The preserved callback is the final check-run version. The initial apply profile used an earlier version without item hooks, so replaying apply with the preserved file will emit additional item events; the saved apply JSON nevertheless contains 172 `ok`, 49 `skipped`, and 1 `failed` aggregate events, with 0 observed item events. The saved check JSON contains 57 `ok`, 7 `skipped`, and 1 `failed` aggregate events plus 25 `item_ok` and 1 `item_failed` events. The check item callbacks’ `seconds_from_task_start` values are cumulative and overlap the aggregate task callback, so they were not summed; aggregate-only analysis remains unchanged. Include wrappers and their included tasks were kept as separate sequential task observations; they were not treated as a wrapper around child runtime.

Machine/concurrency observations were recorded immediately before each run:

| mode | external wall | user/sys | load average (1/5/15m) | CPUs | concurrent validation |
| --- | ---: | ---: | --- | ---: | --- |
| apply | 127.06s | 105.24s / 28.27s | 8.43 / 6.65 / 6.06 | 16 | no |
| check | 34.87s | 28.99s / 7.46s | 8.51 / 8.02 / 6.75 | 16 | no |

The aggregate task observations account for 123.435s of apply and 32.715s of check. The remaining wall time is unattributed overhead: 3.625s (2.9%) for apply and 2.155s (6.2%) for check. Possible contributors include process startup/teardown, Ansible scheduling and serialization, callback/reporting, and other engine overhead; these contributors were not separately measured. These are single fresh runs under variable host load; they are concentration evidence, not a stable performance benchmark. No duplicate baseline was run because the bounded decision did not require one.

## Cost-to-contract breakdown

The following table sums only aggregate task callbacks for the apply run. “Production” includes the production `materialize.yml` include and its planner/materialization tasks. Inspection/assertion is kept separate from fixture construction. The main play splits its two production executions because the second one is the idempotency contract.

| apply play | fixture preparation | production execution | inspection/assertion | aggregate total |
| --- | ---: | ---: | ---: | ---: |
| wrong-type prerequisite | 7.618s | 2.653s | 0.899s | 11.170s |
| synthetic Komf, first execution | 10.865s | 13.781s | 8.040s | 32.686s |
| synthetic Komf, repeated execution | — | 14.664s | 0.054s | 14.718s |
| **synthetic Komf combined** | **10.865s** | **28.445s** | **8.094s** | **47.403s** |
| declaration ownership/defaults | 6.787s | 9.624s | 1.959s | 18.370s |
| exact repository artifact preparation | 11.132910s | — | 4.003303s | 15.136213s |
| exact Overmind | 0.077s | 8.768s | 0.466s | 9.312s |
| exact Servarr | 0.055s | 20.361s | 1.628s | 22.044s |
| **sum of aggregate callbacks** |  |  |  | **123.435s** |

The synthetic combined row is a subtotal of its first and repeated executions, not an additional cost. Small differences between displayed phase sums and subtotals are rounding.

The largest individual apply observations were Servarr static-file copying (5.805s), Servarr stack-directory creation (5.621s), exact compose mirroring (5.100s), synthetic template rendering on the repeated execution (4.986s), and synthetic template rendering on the first execution (4.359s). These task costs are attached to distinct contracts below; they are not reasons by themselves to remove coverage.

Check mode is intentionally narrower:

| check play | fixture preparation | production through check barrier | inspection/assertion | aggregate total |
| --- | ---: | ---: | ---: | ---: |
| wrong-type prerequisite | 8.744s | 2.212s | 0.501s | 11.457s |
| synthetic Komf | 8.787s | 11.273300s through publication | 1.197273s final prerequisite stat/assertion | 21.258s |
| plays 3–6 | stopped by early `meta: end_play` | — | — | 0s observed |

The first two plays force their fixture setup tasks with `check_mode: false`; production check-mode modules also predict changes, so `changed=13` combines real forced fixture seeding with predicted production changes. It is not an all-setup total. The synthetic play then ends after its prerequisite checks. Its final stat/assertion block costs 1.197273s and verifies the missing prerequisite remains absent in check mode, establishing the expected no-write behavior. Plays 3–6 end before preparation. The check recap was `ok=57 changed=13 unreachable=0 failed=0 skipped=7 rescued=1`.

### Contract map

| contract | source-established boundary and observed evidence | disposition |
| --- | --- | --- |
| check mode | The Python launcher uses separate apply/check roots; plays 3–6 stop before setup, and the synthetic play stops after prerequisite verification ([fixture:291-293, 437-439, 587-589, 694-696, 768-770](../../tests/regression/fixtures/stack_sync_materialize_test.yml)). | Preserve. Any fixture consolidation must keep the early check boundary and the first two plays’ forced setup. |
| wrong-type prerequisite rejected before copying | `materialize.yml` stats and validates prerequisite paths at lines 7–24, before template/static copy at lines 48–73. The run failed in `Verify existing stack prereq paths are directories`; no render/copy task ran, the target compose file was absent, and rescue assertions passed ([`materialize.yml:7-73`](../../playbooks/roles/config/lxc_stack_sync/tasks/materialize.yml), [`fixture:81-105`](../../tests/regression/fixtures/stack_sync_materialize_test.yml)). | Preserve. This is a safety ordering boundary, not classification-only work. |
| preserve existing versus create missing prerequisite metadata | The planner resolves prerequisites to Docker UID/GID and `0755`; materialization filters only missing paths before creation ([`planner.yml:226-268`](../../playbooks/roles/config/lxc_stack_sync/tasks/planner.yml), [`materialize.yml:75-105`](../../playbooks/roles/config/lxc_stack_sync/tasks/materialize.yml)). The existing `uploads` directory remained `0700` with its UID/GID; missing `downloads` was created with `0755` and the invoking identity ([`fixture:234-289`](../../tests/regression/fixtures/stack_sync_materialize_test.yml)). | Preserve. The prerequisite stat/assert/filter wave cannot be removed as a report simplification. Directory classification stats outside this safety wave belong to #296. |
| declared ownership/mode | Planner metadata is overlaid onto both render and copy plans, and production modules receive the resulting owner/group/mode directly ([`planner.yml:270-358`](../../playbooks/roles/config/lxc_stack_sync/tasks/planner.yml), [`materialize.yml:48-73`](../../playbooks/roles/config/lxc_stack_sync/tasks/materialize.yml)). The declaration play can verify the expected owner/group values, but its declaration and shared defaults resolve to the same identities, so it cannot distinguish owner/group precedence. Its declared `0600` versus undeclared static-copy `0644` mode and destination selection do discriminate ([`fixture:502-562`](../../tests/regression/fixtures/stack_sync_materialize_test.yml)). | Retain the static-copy/default and destination distinctions. No owner/group deletion or strengthening decision is made here. |
| private Overmind rendering | The real Overmind compose declares `agent-keys.yaml` as `0600` and mounts it read-only; the real `.j2` source consumes `stack_vars.agent_key`. The exact play injects the actual source paths and verifies stack identity, destination, `0600`, and direct template handling ([`stacks/overmind/overmind/compose.yaml`](../../stacks/overmind/overmind/compose.yaml), [`fixture:667-737`](../../tests/regression/fixtures/stack_sync_materialize_test.yml)). | Preserve. This is a private rendered artifact, not interchangeable with a generic public static file. |
| executable/nested Servarr static files and differing source topology | Beets’ `appdata/startup.sh` and Lidarr’s nested `appdata/lidarr/scripts/beets-post-import.sh` are different static source paths, each declared `0755`; the exact play verifies both target paths and modes ([`stacks/servarr/beets-flask/compose.override.yaml`](../../stacks/servarr/beets-flask/compose.override.yaml), [`stacks/servarr/lidarr/compose.yaml`](../../stacks/servarr/lidarr/compose.yaml), [`fixture:739-830`](../../tests/regression/fixtures/stack_sync_materialize_test.yml)). | Preserve both topologies. Similar assertion syntax is not evidence that one path can stand in for the other. |
| repeated-apply idempotency | The synthetic play runs `materialize.yml` a second time. That second production execution cost 14.664s and the final assertion observed zero changed results ([`fixture:403-416`](../../tests/regression/fixtures/stack_sync_materialize_test.yml)). | Preserve. Removing the second execution would remove the only direct repeated-apply proof in this fixture. |

The first synthetic production execution also performs planner rendering of the source compose to parse metadata, then renders the same `.j2` inputs for output. The second execution repeats the planner/materialization path by design. This is a cost hypothesis for a future, separately measured design; the planner needs rendered compose content and the output path needs rendered files, so source inspection alone does not establish safe reuse.

## Bounded candidate examined: declaration play

The declaration-ownership/defaults play was selected for the bounded review because its 18.370s aggregate cost is material and its title overstates the current owner/group discrimination. It is not equivalent to the main play merely because both exercise mode overlay.

A disposable production fault changed the planner’s planned synced-file mode to unconditional `0644` at [`planner.yml:355`](../../playbooks/roles/config/lxc_stack_sync/tasks/planner.yml). The fault was run against two temporary extracted slices, then restored immediately:

- planner-only slice: 20.54s, failed on `declared_entry.mode == '0600'`;
- synthetic-main-only slice: 31.14s, independently failed on the rendered `0600` assertion.

This proves overlap for one global mode-overlay fault only. It does not prove equivalence of the whole declaration play. The declaration play directly checks an undeclared **static copy** retaining default `0644` and declared-versus-undeclared destination selection. The main play checks an undeclared **template** at `0644` and a declared static copy at `0755`. Those source-established distinctions must survive any consolidation. The declaration play can still check expected owner/group results; equal declaration/default identities simply mean that it cannot distinguish precedence.

The exact artifact preparation is another visible cost (15.136213s), but its mirror step removes the real declarations’ unrelated prerequisite entries before running in temporary roots: both absolute paths (`/data/overmind/postgres/pgdata` and `/data/media/_ingest/music`) and Lidarr’s relative `./appdata/lidarr`. It verifies actual repository bytes and `x-managed-files`, and preserves the Overmind/Servarr topology. Removing it or replacing it with hand-written lookalikes would save setup but lose the actual-artifact contract; no coverage-equivalent simpler alternative was established.

## Disposition and bounded recommendation

1. **Retain the declaration play for now.** Do not delete or merge it under #307. If a later implementation review consolidates it, it must carry forward the undeclared static-copy `0644` assertion and declared/undeclared destination-selection assertion. The current potential saving is therefore an unmeasured hypothesis, not an approved optimization.
2. **Retain the repeated materialization.** Its 14.664s cost buys direct idempotency evidence and cannot be replaced by an assertion-only shortcut without changing the contract being tested.
3. **Retain exact Overmind/Servarr handling and preparation.** Their distinct private-rendered, executable/nested-static, source-byte, and topology boundaries are meaningful. Do not fold #308 or #309 work into this issue.
4. **Leave prerequisite safety intact.** The wrong-type ordering and preservation/creation behavior are not the report/classification wave owned by #296. Any removal of directory classification bookkeeping belongs to #296 and must be remeasured there.

A possible bounded follow-up is a separately reviewed fixture-consolidation experiment that moves the declaration play’s two unique static-copy checks into a surviving boundary, explicitly preserves their destination selection, and reports before/after timings under comparable load. Such a review can decide separately whether the expected owner/group checks remain useful; equal identities should be described as non-discriminating precedence evidence, not as proof that the checks must be deleted or strengthened. No such optimization was implemented or measured here.

## Validation and completion conditions

- [x] Cost-to-contract breakdown recorded, with measured results separated from source facts and hypotheses.
- [x] Bounded recommendation recorded: evidence-backed retention, with a narrowly specified future experiment rather than a mergeable redesign.
- [x] Check mode, idempotency, prerequisite safety, ownership/mode, private Overmind rendering, executable/nested Servarr files, source topology, and exact-artifact handling are explicitly addressed.
- [x] Experimental production edit was restored; `git status` and `git diff --check` were clean afterward.
- [x] Targeted restored-baseline validation: `./validate.sh tests tests/regression/test_materialize_templates.py` — **1 passed in 151.26s**.
- [x] Required no-argument handoff validation: `./validate.sh` — **passed**: lint reported 0 failures/0 warnings in 442 processed files; the full lifecycle regression set passed all 25 launchers; pytest reported **811 passed, 4 skipped in 1241.65s (0:20:41)** from 815 collected tests. The pytest duration is the whole pytest process, not any individual test.

No PR is required for the retention disposition. The report is the evidence artifact; #307 remains open for supervisory review and any separately authorized implementation decision.
