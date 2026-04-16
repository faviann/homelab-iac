# Stack Deployer Deep Module — Design

**Date**: 2026-04-15
**Status**: approved

## Problem

The current per-host Docker stack deployer in `playbooks/roles/config/lxc_docker_environment/tasks/main.yml` owns one real concept, but expresses it as a long sequence of shallow task blocks.

That concept is:

`Take the repo-managed stack contract for one host and reconcile it onto the container.`

Today that concept is spread across:

- repo stack discovery under `stacks/<inventory_hostname>/`
- `.j2` rendering and static file copying
- compose metadata parsing for `x-prereq-dirs`
- ownership override handling from host vars
- stale deployed stack quarantine
- bind mount setup from `/shared/<host>` to `/conf/docker`
- managed asset materialization for Dockge and `docker-agents`
- external Docker network creation
- `docker compose up -d` execution

The result is architectural friction:

- understanding one stack behavior requires bouncing between role tasks, defaults, docs, compose files, and host vars
- the public interface is too implicit to test cleanly, but the implementation is too exposed to refactor safely
- callers can only reason about the system by reading internal orchestration details

## Chosen Direction

Adopt a hybrid of:

- **Convention-first common caller interface**
- **Internal sync engine with a report boundary**

The public contract stays small and host-oriented.
The implementation becomes a deep module that owns planning and reconciliation internally.

## Proposed Interface

### Caller-facing contract

The host-facing API should stay minimal:

```yaml
lxc_docker_environment:
  external_networks: []
  path_ownership_overrides: []
```

Or, if migration pressure makes renaming too noisy, keep the existing variable names as compatibility aliases:

```yaml
lxc_docker_env_external_networks: []
lxc_docker_env_path_ownership_overrides: []
```

The role should not expose discovery knobs, compose manifest lists, startup sequencing flags, or caller-declared stack graphs.

### Internal module boundary

Internally, the role should be reorganized around one sync operation with a report:

```text
sync_host_docker_environment(...) -> DeploymentReport
```

The exact implementation language is open. The important part is the boundary:

- one entry point for host stack reconciliation
- one output object or fact containing caller-relevant outcomes

`DeploymentReport` should expose only useful outcomes, for example:

- `changed`
- `discovered_stacks`
- `created_dirs`
- `updated_dirs`
- `created_networks`
- `quarantined_stacks`
- `started_stacks`
- `unchanged_stacks`
- `skipped_stacks`

## Why This Interface

This combines the strongest parts of the explored designs:

- From the common-caller design:
  keep the public API tiny and convention-driven
- From the sync-boundary design:
  make the implementation testable at one stable reconciliation boundary

This avoids the weakest design path:

- do **not** introduce a large `lxc_docker_stack_deployer` schema with discovery modes, hooks, explicit stack declarations, and policy flags

That larger schema would just re-encode the role’s current internal complexity as caller-visible YAML.

## Constraints The Module Must Satisfy

The deepened module must preserve the existing repo contract:

- source of truth remains `stacks/<inventory_hostname>/`
- `.j2` files render with inventory, group, host, and vault vars
- templated outputs win over static files for the same output path
- `x-prereq-dirs` remains the mechanism for declaring bind-mount targets that need pre-creation
- host vars can still declare external networks and path-specific ownership overrides
- stale deployed stacks are still quarantined instead of silently deleted
- Dockge and `docker-agents` remain internal managed assets of this role

## What The Module Should Hide

The interface should hide:

- file discovery rules
- compose filename selection
- template-vs-static precedence
- compose YAML parsing
- `x-prereq-dirs` path resolution
- desired-vs-deployed tree diffing
- stale stack quarantine sequencing
- external network creation sequencing
- compose startup sequencing
- Dockge and `docker-agents` materialization details
- bind mount setup and related ownership normalization

Those are implementation details of stack reconciliation, not caller concerns.

## Dependency Strategy

Dependency category: **local-substitutable**

The implementation should treat these as local adapters:

- **Stack repository adapter**
  reads `stacks/<host>/`, resolves templates, and extracts compose metadata
- **Target filesystem adapter**
  writes deployed files, creates prereq dirs, applies ownership overrides, and quarantines stale stacks
- **Docker runtime adapter**
  creates external networks and runs compose lifecycle commands

Even if this stays implemented as Ansible task structure instead of a Python library, the module should be organized around those boundaries mentally and in tests.

## Testing Strategy

Replace task-fragment reasoning with boundary tests around the sync operation.

### New boundary tests to write

- given a sample `stacks/<host>/` tree, the module renders and copies the expected deployed tree
- `.j2` output wins over a same-path static file
- `x-prereq-dirs` entries create the expected directories with the expected ownership
- host-level ownership overrides are applied after prereq dir creation
- removed source stacks are quarantined from the deployed tree
- declared external networks are created before compose startup
- managed assets like `docker-agents` and Dockge are materialized or removed according to host capability behavior
- the sync operation returns a useful deployment report

### Old tests to avoid writing

Do not add isolated tests for:

- individual `find` tasks
- individual `set_fact` transforms
- individual `copy` vs `template` task branches
- isolated `docker compose up` command tasks

Those tests would lock in shallow structure instead of the behavior we care about.

## Migration Guidance

Implementation should proceed in stages:

1. Introduce a single internal “plan/report” concept without changing host vars.
2. Collapse stack-specific orchestration under one sync boundary.
3. Keep compatibility with existing `lxc_docker_env_external_networks` and `lxc_docker_env_path_ownership_overrides`.
4. Optionally add `lxc_docker_environment` as the future canonical public object only if it reduces cognitive load without forcing broad inventory churn.

## Non-Goals

- Do not make callers declare stack lists explicitly.
- Do not expose internal sequencing as policy knobs.
- Do not split Dockge, `docker-agents`, and per-host stack sync into separate caller-facing roles unless a real independent lifecycle emerges.
- Do not optimize first for rare edge cases at the cost of widening the public interface.

## Recommended Next Step

Implement the refactor as a local planner/executor boundary inside `config/lxc_docker_environment`, while preserving the current stack contract and current host vars.

That gives the repo:

- a smaller usable interface
- a deeper module
- a clean test boundary
- less architecture encoded in docs and call sites
