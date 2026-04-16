# LXC Lifecycle Transition Report

Date: 2026-04-16
Plan: 2026-04-16-04-lxc-lifecycle-transition

## Process

1. Asked a planning subagent for the smallest lifecycle boundary that could become authoritative without a big-bang rewrite.
2. Narrowed that to one internal `_lxc_lifecycle_state` object, while keeping the existing action facts as derived compatibility state during the migration.
3. Asked a second subagent for an implementation outline focused on state publication and low-cost scenario testing.
4. Implemented the state boundary incrementally: initialize in `main.yml`, publish compile/inspect/decision data into it, keep provision/configure behavior stable, and render the public result from the state object.
5. Added scenario-based regressions for the decision/result boundary and fixed the two local publish bugs they exposed.

## What Changed

- `playbooks/roles/provisioning/proxmox_lxc_lifecycle/tasks/main.yml` now initializes `_lxc_lifecycle_state` and uses its host/guest action lists to gate execution.
- `compile.yml` now publishes the compiled spec, compiled contract, and desired Debian release into the lifecycle state.
- `inspect.yml` now publishes validation snapshot, runtime state, actual release, release probe state, and release mismatch into the state object.
- `decide.yml` now publishes validation, skip flags, rebuild status, and host/guest/cache action plans into the state object.
- `provision.yml` now records rebuild outcome back into the lifecycle state when destroy/recreate occurs.
- `publish.yml` now finalizes lifecycle status/reason on the state object first, then renders `lxc_lifecycle_result` from that state instead of reconstructing it from ambient facts.
- Added `tests/regression/test_lxc_lifecycle_decision.py` and its fixture to cover key decision/result scenarios without requiring live Proxmox.

## Debugging Notes

- The first lifecycle regression exposed a publish ordering bug: `publish.yml` was updating `_lxc_lifecycle_state` and reading the new status from it in the same `set_fact`, so the public result saw blank status/reason values.
- Splitting state finalization from public result rendering fixed that, but it revealed a second local defect: the task-scoped `_lifecycle_status` and `_lifecycle_reason` vars were still attached to the wrong task after the split.
- Once those vars were moved onto the state-finalization step, the scenario regression passed cleanly.

## Validation

Focused regression passed:

- `tests/regression/test_lxc_lifecycle_decision.py`

Structural validation also passed for the touched lifecycle task files via editor diagnostics.

## Remaining Gaps

- Provision and configure tasks still rely on the existing compatibility action facts internally; this slice made `_lxc_lifecycle_state` authoritative for planning and publishing without forcing a broader execution rewrite.
- The new regression targets decision/result behavior, not live Proxmox execution or guest configuration sequencing. Those are better exercised by staging playbook runs once the remaining plan slices are in place.