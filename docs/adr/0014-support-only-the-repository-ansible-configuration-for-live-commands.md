# Support only the repository Ansible configuration for live commands

Live commands support the repository's own Ansible configuration, `ansible.cfg`
at the repository root. The operator owns any alternate runtime configuration:
an alternate `ANSIBLE_CONFIG`, alternate collection or role search paths,
dependency copies that shadow repository-managed pins, and custom SSH
`ControlPath` values. The live dependency reconciler does not read, repair, or
reproduce these settings. It reads no environment. Its collections path, roles
path, and SSH control-path parent are repository-relative constants.

The lifecycle wrapper forwards arguments after `--` to `ansible-playbook`. It
rejects only arguments that set target selection, lifecycle intent, or check
mode, so an operator can supply a custom `ControlPath` through SSH arguments.
When an operator does this, they must create that path's parent directory. The
repository does not attempt it. The reconciler creates only the parent of the
configured `control_path`.

No live workflow uses these override mechanisms. `ANSIBLE_CONFIG` appears
nowhere in the repository, and there is no CI. Non-live regression launchers set
`ANSIBLE_COLLECTIONS_PATH` and `ANSIBLE_ROLES_PATH` to reach fixture collections
and roles. That is a test fixture, not an operator contract, and none of those
paths crosses the live boundary. Nobody has reported the concern from operation.
It began as a hypothesis in the pre-merge review of the reconciler, and the
confirming test set the overrides itself.

When an operator overrides one of these settings, the operation fails with an
error. The failure is an unresolvable module or an SSH control-socket error.
Nothing is silently changed or corrupted, so the decision is safe without
detection.

The regression
`test_repository_paths_match_the_normal_ansible_configuration` in
`tests/regression/test_live_dependencies.py` enforces this decision. It checks
that the reconciler's path constants match `ansible.cfg`. That check keeps the
repository-owned configuration and the reconciler in agreement. It does not
examine the configuration that a running command resolves.

Support for arbitrary runtime configuration was rejected because nothing
consumes it. Repairing a shadowing installation was rejected for the same
reason. Deriving the effective `ControlPath` was rejected because Ansible cannot
report it. `ansible-config dump` resolves `ANSIBLE_CONFIG`, environment, and
`ansible.cfg` precedence for search paths. But when `-o ControlPath=...` arrives
through SSH arguments, the dump still reports the configured `control_path`.
Recovering the real value would reimplement OpenSSH argument precedence. A guard
that detects a mismatched search path and refuses was rejected. It could cover
only the environment-variable cases that no workflow reaches. It would miss the
`ControlPath` case that the passthrough does reach.

Revisit this decision when a concrete repository workflow needs a non-default
Ansible runtime configuration on the live path.
