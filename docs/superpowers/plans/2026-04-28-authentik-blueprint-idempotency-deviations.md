# Authentik Blueprint Idempotency Plan Deviations

## Summary

The implementation stayed aligned with the plan's end goal and architecture, but a few execution details changed to fit repo rules and issues found during review.

## Deviations

### 1. Repo command policy overrode the plan's example commands

- **Plan**: Use bare `python -m pytest` and `ansible-playbook` examples.
- **Actual**: Ran Python and Ansible commands via `uv run --locked ...`.
- **Why**: [AGENTS.md](/home/aperture/ServerManagementScripts/AGENTS.md) requires Python and Ansible tooling in this repo to run through `uv run --locked`.

### 2. Tasks 2 and 3 landed in one script commit

- **Plan**: Commit normal blueprint idempotency and Navidrome helper changed-reporting as separate commits.
- **Actual**: Combined those script changes into commit `a98df89`.
- **Why**: Both changes contributed to the same top-level script contract: a reliable JSON `changed` signal for Ansible. They were implemented and validated together against the same focused test slice.

### 3. The Ansible JSON contract was hardened beyond the plan

- **Plan**: Parse script JSON directly inside `changed_when` and then assert the top-level `changed` key.
- **Actual**: The role now decodes JSON in a separate task, fails explicitly if stdout is not valid JSON, and treats invalid JSON as a changed-unknown failure path.
- **Why**: Review found that parsing inside `changed_when` could fail before the intended contract check ran, obscuring the error and under-reporting possible live mutation.

### 4. Additional regression tests were added beyond the plan

- **Plan**: Cover the no-op/apply decisions and direct Navidrome binding reporting.
- **Actual**: Added two extra regression checks:
  - CLI `apply` mode emits valid JSON with a top-level boolean `changed`.
  - Multi-blueprint metadata repair does not retain stale lookup keys or drop planned instances.
- **Why**: Review exposed two gaps not covered by the original plan: the Ansible/CLI stdout contract and a multi-blueprint aliasing bug during metadata repair.