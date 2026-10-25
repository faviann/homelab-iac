# Agent Operating Instructions

Ansible infrastructure-as-code that provisions and configures Proxmox LXCs and their Docker stacks. Two control nodes live inside the fleet. The `workstation` LXC manages every target. The `bootstrap` LXC runs the nightly deploy of every other LXC, interrupting workstation changes, and recovery.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (faviann/homelab-iac), reached with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles use their default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`).

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. Use the glossary's terms and avoid the synonyms it lists. Flag any conflict with an ADR instead of silently overriding it.

## Project Philosophy

**Code is a liability, not an asset.** When two approaches exist, recommend the one with less code and fewer objects.

## Non-negotiables

- Never request, paste, print, or commit secrets (API token secret, vault passphrase, private keys). Secrets live only in the encrypted `inventory/vault.yml`. Use placeholders like `<REPLACE_ME>` in docs and examples.
- Use the repository's commands below, both in what you run and in the command examples you write. Do not invoke Ansible, `uv`, or `pytest` directly. [docs/command-policy.md](docs/command-policy.md) gives the approved exceptions.
- Lifecycle runs silently skip the control node they run on. `./run.sh --include-controller` targets it, but its interrupting steps wait for a run from the other control node. Run `--interrupt-busy` against the workstation only on explicit request, and only from the bootstrap node.
- Roles gate on capability flags (`when: docker_enabled | default(false)`), never on group membership (`'cap_docker' in group_names`).

## Commands

Six commands are the whole interface. `<command> --help` lists each one's operations. [docs/command-policy.md](docs/command-policy.md) holds the grammar, exit statuses, lock classes, and permitted raw commands.

| Command | Use |
|---------|-----|
| `./run.sh [provision\|configure] [--limit <targets>] [--stack <stack>] [--check]` | Deploy the LXC lifecycle, or dry-run it with `--check`. Low-level Ansible arguments go after `--` |
| `./inspect.sh credentials\|connectivity\|containers\|plan\|probe <https-url>\|vars <host>` | Read-only checks. `probe` replaces curl for testing a routed service URL |
| `./validate.sh [lint\|lifecycle [--only <launcher.py>]\|tests [<target>...]]` | Non-live verification. Use `lifecycle` while iterating on LXC lifecycle code |
| `./vault.sh check\|diff\|merge\|rotate --dry-run` | Vault operations agents may run. `merge` resolves a conflicted `inventory/vault.yml`. `set` and `unset` run only on explicit request. `configure`, `edit`, and `rotate` are human-only |
| `./recover.sh` | Human-only. Enrolls the fleet key |
| `./setup.sh sync\|upgrade <package>...` | `sync` is optional, because every command reconciles its own environment. `upgrade` bumps named packages in `uv.lock` |

A live operation that cannot take the machine-local lock exits 75 at once and never waits. Exit 3 means deferred, not failed. A run defers a stack whose busy check reports busy, and the workstation while any agent on it is mid-turn, including the agent that started the run. A mutating workstation run also exits 3 while a deploy is in flight on the bootstrap node.

`./run.sh` against live hosts takes 5 to 10 minutes, less with `--limit` or `--stack`. Wait for it to finish instead of assuming a hang. Redirect live output to a log and read only the summary:

```bash
./run.sh --limit <host> > /tmp/<task>.log 2>&1
rg "failed=|unreachable=|FAILED|changed=" /tmp/<task>.log
```

Before handoff, always run `./validate.sh` with no arguments (about 5 minutes). A targeted run never substitutes, with one exception. When every path in `git diff --name-only origin/main...HEAD` and `git status --short` ends in `.md`, and none is under `playbooks/`, run only the two tests a Markdown edit can fail:

```bash
./validate.sh tests tests/unit/test_workstation_mcp_auth_proxy_contract.py tests/regression/test_vault_command.py::test_rotate_publishes_only_after_a_verified_local_rekey
```

## Related Documentation

- Read [docs/inventory-structure-guide.md](docs/inventory-structure-guide.md) when adding a host or debugging variable precedence.
- Read [stacks/README.md](stacks/README.md) before creating or modifying a Docker stack. Stacks live at `stacks/<host>/<stack>/compose.yaml` and deploy without registration.
- Read [docs/workstation-persistent-state.md](docs/workstation-persistent-state.md) before adding a persisted workstation home path or rebuilding the workstation LXC.
- Read [docs/bootstrap-node.md](docs/bootstrap-node.md) before any interrupting workstation change, or when the workstation is unreachable.
- Read [docs/lobu-control-plane.md](docs/lobu-control-plane.md) before touching the `lobu` LXC, its stack, or the `lobu.admin.faviann.com` routers.
- Read [docs/lobu-browser-device.md](docs/lobu-browser-device.md) before touching `lobu-crawler-01` or any `cap_browser_device` host.
- Read [stacks/broodling/broodling/README.md](stacks/broodling/broodling/README.md) before touching the `broodling` LXC, its stack, or its initialization.
- Read [docs/artifact-server.md](docs/artifact-server.md) before touching the `agent-services` LXC or its `artifact-server` stack, and before publishing to artifact-server.
