# lxc_stack_sync

## ComposeManifestPlanner Contract

`tasks/planner.yml` turns discovered per-host stack sources into one execution plan published as `lxc_stack_sync_manifest_plan`.

### Inputs

- `lxc_docker_environment_internal.stacks_source`
- `lxc_docker_environment_internal.shared_mount_source`
- `lxc_docker_environment_internal.shared_owner`
- `lxc_docker_environment_internal.shared_group`
- `lxc_docker_environment_internal.docker_uid`
- `lxc_docker_environment_internal.docker_gid`
- `lxc_docker_environment_internal.path_ownership_overrides`
- `_per_host_j2_files.files`
- `_per_host_static_files.files`
- `_per_host_dirs.files`

### Output

`lxc_stack_sync_manifest_plan` contains:

- `templated_outputs`: relative target paths for `.j2` sources with the `.j2` suffix removed
- `source_compose_specs`: compose sources with rendered or raw content plus target path metadata
- `stack_dirs_to_create`: absolute stack directory paths under the shared mount
- `files_to_render`: templated source files with `source_path`, `dest_path`, `relative_path`, and `stack_name`
- `files_to_copy`: static source files with `source_path`, `dest_path`, `relative_path`, and `stack_name`
- `prereq_dirs`: resolved `x-prereq-dirs` entries with `path`, `owner`, `group`, and `mode`
- `ownership_overrides`: passthrough ownership override entries from `lxc_docker_environment_internal`
- `managed_files`: resolved `x-managed-files` entries with `path`, `owner`, `group`, and `mode`
- `managed_file_parent_dirs`: parent directories for managed files with `path`, `owner`, `group`, and `mode`

### Guarantees

- `managed_files` are deduplicated by `path`
- relative `x-prereq-dirs` and `x-managed-files` paths are resolved from the compose target directory
- `prereq_dirs` exclude paths that are already covered by `path_ownership_overrides`
- `materialize.yml` consumes the plan and does not re-parse compose extensions inline