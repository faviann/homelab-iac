# Support only the repository Ansible configuration for live commands

Live commands support the repository's own Ansible configuration, `ansible.cfg`
at the repository root. The operator owns any alternate runtime configuration:
an alternate `ANSIBLE_CONFIG`, alternate collection or role search paths,
dependency copies that shadow repository-managed pins, and custom SSH
`ControlPath` values. The live dependency reconciler does not read, repair, or
reproduce these settings. Its collections path, roles path, and SSH control-path
parent are repository-relative constants.

The lifecycle wrapper forwards arguments after `--` to `ansible-playbook`. It
rejects only arguments that set target selection, lifecycle intent, or check
mode, so an operator can supply a custom `ControlPath` through SSH arguments.
When an operator does this, creating that path's parent directory is their
responsibility. The reconciler creates only the parent of the configured
`control_path`.

No repository code or workflow sets `ANSIBLE_CONFIG`, and there is no CI.
Non-live regression launchers set `ANSIBLE_COLLECTIONS_PATH` and
`ANSIBLE_ROLES_PATH` to reach fixture collections and roles. That is a test
fixture, not an operator contract, and none of those paths crosses the live
boundary. The concern has never been seen in operation. It began as a review
hypothesis, and the confirming test set the overrides itself.

When an operator overrides one of these settings, the command may fail with an
error, such as an unresolvable module or an SSH control-socket error. It may
instead run with the operator's own copies, or the override may have no effect,
as with a custom `ControlPath` when SSH multiplexing is off. The reconciler
writes only repository paths, so nothing it owns is corrupted, and the decision
holds without detection.

The path-drift regression in `tests/regression/test_live_dependencies.py` is
this decision's enforcement point. It asserts that the reconciler's path
constants match `ansible.cfg`, which keeps the two in agreement. It does not
examine the configuration a running command resolves.

Supporting arbitrary runtime configuration and repairing shadowing
installations were rejected because nothing consumes them. Deriving the
effective `ControlPath` was rejected because Ansible cannot report it.
`ansible-config dump` resolves `ANSIBLE_CONFIG`, environment, and `ansible.cfg`
precedence for search paths. When `-o ControlPath=...` arrives through SSH
arguments, the dump still reports the configured `control_path`, and recovering
the real value would reimplement OpenSSH argument precedence. A guard that
detects a mismatched search path and refuses was rejected. It could cover only
the environment-variable cases that no workflow reaches, and it would miss the
`ControlPath` case that the passthrough does reach.

Revisit this decision when a concrete repository workflow needs a non-default
Ansible runtime configuration on the live path.
