---
name: verify
description: Prove, read-only and against the live fleet, the HTTPS services the homelab serves to its users, such as Authentik, Jellyfin, Immich, and RomM, reached by name through the edge and Traefik on portal, anonymously or signed in as verify-agent. Evidence outlives the run. Use after a change lands on the fleet, when a service looks down, or when asked to prove a service works. Not for proving playbook logic, which ./validate.sh owns.
---

# Verify the fleet's services

The user surface of this repo is the services the fleet serves, not the Ansible playbooks. A user types a name such as `jellyfin.public.faviann.com`. DNS sends it to the edge, the edge forwards to Traefik on the `portal` LXC, and Traefik routes it to a container on some LXC, behind Authentik forward auth when the route is protected. A proof drives that same path from a control node, as one of two kinds of journey:

- An **anonymous probe**, `./inspect.sh probe`, sends each request as a signed-out browser would.
- A **signed-in journey**, `./inspect.sh journey`, signs in to Authentik as `verify-agent` first, then sends each request in that session. `verify-agent` is an Authentik service account in no group. It reaches only the applications that carry its access binding.

Playbook behavior is proven by `./validate.sh`, never by this skill.

## Rules

- There is one live fleet and no second instance to drive. Everything here is read-only: `./inspect.sh` operations and `./run.sh --check`. Never run a mutating `./run.sh`, any `./recover.sh` operation, or `./vault.sh` beyond `check` to make a proof pass. A failing proof is the result. Report it.
- No raw `curl`, `wget`, or browser against a fleet service: `./inspect.sh probe` and `./inspect.sh journey` own that request ([command policy](../../../docs/command-policy.md)). Read-only SSH to a named host is allowed only under the policy's standing permission, to explain a failure the probe already showed.
- A signed-in journey runs as `verify-agent` and no one else. Never borrow a person's credentials or session.
- A signed-in journey stays read-only after sign-in: it sends `GET`s only. Its permitted side effects are the ones signing in causes: an Authentik session, the app password the run mints and deletes, and an app's first-login account, such as the viewer RomM creates. A journey that needs any other write, or a human step such as issuing an app API key, is out of scope. Report it as not verified.
- A signed-in journey to an application without `verify-agent`'s access binding ends `FAIL`, because Authentik denies the sign-in to that application. Report its signed-in sub-features as not verified. Granting the binding is an auth-stack change and deploy ([stacks-authentik.md](../../../docs/stacks-authentik.md#access-groups)), outside this skill.
- Every live command takes the machine-local lifecycle lock shared. It exits `75` at once when a mutation such as a deploy holds it. Report that and wait for the deploy to finish. Do not loop on retries. The nightly deploy runs from the bootstrap node at 03:00 outside this lock, so a probe near that time can see services restarting.

## Launch

Nothing is launched. The fleet is already running and the skill never starts, restarts, or deploys it. A run starts by creating its evidence directory, from the repository root:

```bash
ev=~/.ansible/verify-evidence/$(date -u +%Y%m%dT%H%M%SZ)-<slug>
mkdir -p "$ev"
git rev-parse HEAD > "$ev/commit"
git status --short >> "$ev/commit"
```

`<slug>` names what is being proven, for example `jellyfin-after-bump`. The first live command in a fresh worktree also reconciles Python dependencies, which adds a minute. That is not a hang.

## Doctor

Run this first, and again whenever anything looks off:

```bash
./inspect.sh connectivity --limit portal,<feature-hosts> > "$ev/doctor.log" 2>&1; echo "exit=$?" >> "$ev/doctor.log"
getent ahostsv4 <service-hostnames> >> "$ev/doctor.log"
tail -5 "$ev/doctor.log"
```

Run one doctor per run. `<feature-hosts>` lists, comma-separated, the inventory host of every feature this run proves, named in each feature file's preconditions; `<service-hostnames>` lists their public names, space-separated. Exit `0` with `✅ SSH reachable` for each host means the control node is healthy (locked environment, fleet key, Proxmox trust), the lock is free of mutations, and the hosts are up. The `getent` line shows which address the name resolves to: the LAN edge `10.1.0.2` for most names, the WAN address for `*.public.faviann.com`.

- `exit=75`: a live mutation holds the lock. Stop and report its holder.
- `❌ SSH unreachable`: the host is down. Every probe of its services will fail. Report it.
- A host-key mismatch: report it to a person. Never clear `~/.ansible/known_hosts`.

## Drive

### Anonymous probe

```bash
./inspect.sh probe <https-url> [<https-url>...]
```

It sends one anonymous `GET` per URL from the control node through normal DNS, verifies TLS, and does not follow redirects. Each URL prints one `"msg"` line in the Ansible output. Ansible escapes the quotes inside it as `\"`. Unescaped, the lines read:

```text
PASS https://jellyfin.public.faviann.com/health status=200 elapsed=0s location=- content_type=text/plain detail="OK (unknown bytes)" body=Healthy
FAIL https://no-such-router.admin.faviann.com/ status=404 elapsed=0s location=- content_type=text/plain; charset=utf-8 detail="HTTP Error 404: Not Found" body=404 page not found
FAIL https://nonexistent.invalid/ status=-1 elapsed=0s location=- content_type=- detail="Request failed: <urlopen error [Errno -2] Name or service not known>" body=
```

- `PASS` is any status from 100 to 399. A `302` to `https://auth.faviann.com/application/o/authorize/` is a protected route correctly asking for sign-in.
- `FAIL` is a 4xx or 5xx, or `status=-1` (no response: DNS, TCP, or TLS failure, named in `detail`).
- Exit `0` when every URL passed, `1` when any failed (the playbook names them), `2` for bad usage (no URL, a non-`https://` URL, or a URL with a comma, whitespace, quote, backslash, or brace), `75` for the lock.
- `location` drops the redirect's query. `body` is the last field. It holds the first 160 characters, whitespace collapsed.
- `404 page not found` with `content_type=text/plain` is Traefik itself: no router matches that name.

### Signed-in journey

```bash
./inspect.sh journey <https-url> [<https-url>...]
```

It mints an Authentik app password for `verify-agent` that expires after Authentik's default token lifetime (30 minutes on this install), signs in through the default authentication flow once, then sends one `GET` per URL, in order, in that one session. It follows each URL's redirects, up to 15, so a native OIDC login completes and a later URL sees the app's session. The app password is deleted at the end of the run. Each URL prints one line in the probe's format, with a `hops` field before `body`. Unescaped, a forward-auth journey reads:

```text
PASS https://homepage.media.faviann.com/api/healthcheck status=200 elapsed=1s location=- content_type=- detail="OK" hops=302:https://homepage.media.faviann.com/api/healthcheck,302:https://auth.faviann.com/application/o/authorize/,302:https://media.faviann.com/outpost.goauthentik.io/callback,200:https://homepage.media.faviann.com/api/healthcheck body=up
```

- `hops` lists every request of the chain as `<status>:<URL without query>`, comma-separated. `status`, `content_type`, and `body` describe the last response.
- `PASS` means the last response is a 2xx that is not the Authentik sign-in flow (`/flows/` or `/if/flow/` on `auth.faviann.com`). Anything else is `FAIL`, including a 3xx, which only a chain longer than 15 redirects ends on.
- When sign-in stops, every URL prints `FAIL` with `status=-1` and `detail="not walked: sign-in stopped at <stage>"`. The stage names what Authentik asked for instead, for example `ak-stage-captcha` when the request did not come from the LAN.
- A run that fails before sign-in, when Authentik rejects the API token, lacks `verify-agent`, or refuses the app password, prints no URL line. Its failure message names the cause and Authentik's answer.
- Exit statuses and usage errors are the probe's: `0`, `1`, `2`, `75`.
- It reads the vault, because it mints the app password with the Authentik API token, so it runs only where the vault passphrase is. Each run writes a `SECRET_VIEW` event to Authentik's event log when it reads the minted key. That event is expected.
- It reaches only what plain `GET` redirects reach: forward-auth hosts on a tier bound to `verify-agent`, and native OIDC apps whose login is `GET` redirects, such as RomM, Komga, Calibre-Web Automated, and ReadMeABook. An app whose login takes a `POST` from its own page, such as Immich, is out of its reach.

### Finding URLs

Find a service's URL from the repo, not memory. A Docker-labelled service is `https://<compose project>.<default_domain>`, where `default_domain` is in `inventory/host_vars/<host>.yml`, unless its compose labels set `traefik.domain` or an explicit `Host(...)` rule. File-provider routes (Authentik, the Proxmox UI, services outside Docker) are in `stacks/portal/traefik3/appdata/traefik3/config/conf.d/`.

Drive features from the map in [features/README.md](features/README.md). Each feature file names its URLs, its doctor host, and the observable end state. A proof of a feature runs every URL its file lists.

### Drift against the repo: `./run.sh --check`

To show that a host's deployed stack matches the checkout, without changing it:

```bash
./run.sh --check --limit <host> --stack <stack> > "$ev/check.log" 2>&1; echo "exit=$?" >> "$ev/check.log"
rg "changed=|failed=|unreachable=" "$ev/check.log"
```

Exit `0` (or `3`, a busy host deferred) and no `changed:` task other than `lxc_base_system : Update apt cache` means no drift. That task reports `changed` in check mode whenever the cache is stale, without refreshing it, so a host with no drift can still show `changed=2` from it alone. List the changed tasks with `grep -B3 '^changed:' "$ev/check.log" | grep TASK`. Any other changed task is what a real run would change: a finding, not something to fix here. It takes a few minutes and the shared lock.

What `--check` still executes, audited from the roles: tasks marked `check_mode: false` run for real, and all of them only read the Proxmox host and the LXCs (`pct list`, `docker --version`, `grep` on the container config). The one write is on the control node. See [Gotchas](#gotchas). `--stack` narrows only stack sync and per-stack extras. Host-level roles (host config, packages, Docker and NVIDIA runtime, origin firewall) still run in check mode, so their drift shows too.

## Gotchas

- `./run.sh --check` is not write-free. Host-key pinning runs with `check_mode: false` and rewrites the target's block in the control node's `~/.ansible/known_hosts`, writing an empty block for a stopped guest. The Proxmox trust check can add the Proxmox host key there when it has no entry. Every SSH-consuming live command (`./inspect.sh connectivity`, `./inspect.sh plan`, and `./run.sh`) does the same. `./inspect.sh probe` and `./inspect.sh journey` do not. This comes from reading the roles, not from observing a run.
- `Update apt cache` reports `changed` under `--check` without refreshing anything. See [Drift against the repo](#drift-against-the-repo-runsh---check).
- `*.public.faviann.com` resolves to the WAN address, so those probes leave the LAN and return through the router. A public-tier failure while `auth.faviann.com` passes points at the WAN path first.

## Evidence

Everything goes in `$ev` (`~/.ansible/verify-evidence/<UTC timestamp>-<slug>/`): machine-local, outside every worktree, so it survives worktree removal and cleanup. One proof holds:

- `commit`: the commit under test and any uncommitted changes.
- `doctor.log`: the doctor output, its exit status, and DNS answers.
- `<feature>.log`: the full probe or journey output with `exit=<status>` appended, one file per feature, from the feature file's Proof step.
- `summary.md`: one line per URL (`PASS`/`FAIL`, status, the observed value that proves the feature), every sub-feature not verified and why, and the evidence path.

Proof standards:

- Drive the path the user takes: the public hostname through DNS, the edge, and Traefik. Never substitute an LXC address, a published port, or `docker exec`.
- Capture the entry point and the backend: the web UI or login redirect, and a health or version endpoint that only the backend answers. A shell page alone proves only routing.
- Where a feature names a repo pin, compare the served version to the pin at the commit under test. A mismatch is a finding.
- Record a `FAIL` line exactly as printed. Do not rerun until it passes and report only the pass.
- Never write secrets into evidence: no `.env` contents, no `docker inspect` environment, no tokens copied from a browser. A journey's lines carry no app password, authorization code, or cookie: hops drop queries, the walker replaces the app password and every cookie value of 8 characters or more with `<redacted>`, and the run fails without printing its lines if the app password still appears.

## Cleanup

The skill starts no instance, so there is nothing to stop. Delete only scratch files this run wrote outside `$ev` (for example `/tmp/<task>.log`). Never delete or move `$ev`, and never "clean up" by restarting a container or redeploying. After cleanup, confirm the proof is still there:

```bash
ls -l "$ev" && grep -h '"msg": "\(PASS\|FAIL\)' "$ev"/*.log | wc -l
```

## When it is wrong

- A feature file no longer matches what the service serves: update the file in the same change that proved it, or report it.
- A new user-facing service: add a feature file and an index line in [features/README.md](features/README.md).
- `./inspect.sh probe` lives in `inspect.sh` and `playbooks/service-probe.yml`. `./inspect.sh journey` lives in `inspect.sh`, `playbooks/service-journey.yml`, and `scripts/journey_walker.py`. `./validate.sh` covers their grammar, routing, and the journey's line format and redaction.
