# Enforce the non-live boundary in the validation command

`./validate.sh` establishes the repository's non-live Ansible environment once
for its entire run. It exports `ANSIBLE_INVENTORY` and
`ANSIBLE_VAULT_PASSWORD_FILE` to repository-owned fixtures under `tests/`, so
lint, lifecycle launchers, pytest, and their descendants inherit the same
inputs. The fixture inventory names only the test hosts and supplies no host
addresses belonging to managed hosts, no SSH settings or credentials, and no
inventory-level local connection. Instead, the fixture aliases `auth`, `portal`,
and `workstation` map exactly to `auth.invalid.`, `portal.invalid.`, and
`workstation.invalid.`. These reserved, non-resolving connection targets make a
forgotten `connection: local` fail at name resolution rather than reach a
managed host. Play-level `connection: local` remains necessary for successful
fixture execution. The fixture passphrase is an inert placeholder, not a
credential.

Pytest startup establishes the same boundary on its own. The repository-root
`conftest.py` overwrites both variables with the fixture paths before
collection, whatever the launching shell exported, so every pytest session
rooted in this checkout and its descendant processes use the fixtures. The
hook sits at the root rather than in `tests/` so a test tree added elsewhere in
the checkout is covered too. Startup fails when a fixture file is missing. A
test that needs a different controlled environment may still set these
variables after startup, for itself or for one child process.

The shared regression-test helper also asserts these fixture paths before it
builds the locked `uv run --locked ansible-playbook` invocation. Tests that pass
their own inventory must declare that exception explicitly; they still require
the fixture vault-password file.

Per-fixture safety was rejected because hand-written `connection: local` and
individually supplied inventories make isolation depend on every test author.
Editing each playbook invocation to repeat the fixture paths was rejected as
duplicated policy that can drift. Depending on the workstation inventory and
machine-local vault passphrase was rejected because validation must not require
operator credentials. Making validation fully offline was also rejected: the
required boundary is no managed host, no vault secret, and no machine-specific
credential; public-network reads remain permitted.

This decision governs Ansible processes descended from `./validate.sh` or from a
pytest session rooted in this checkout. It does not cover launchers run
directly outside either, pytest runs that disable conftest loading, or Ansible
run by hand, and it does not prohibit controlled fixture-local execution or
public-network access. It changes neither live lifecycle commands nor their
locking and wrapper safeguards.
