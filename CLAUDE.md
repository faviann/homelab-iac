# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

---

## Do Not Try Again (Running Mistake Log)

This is a permanent log. When you make a mistake on this project, add an entry here before the session ends. Future Claude instances must read this and not repeat these approaches. Be specific — vague lessons are useless.

---

### 2026-04-12

- When a workstation setup problem arises, read `setup.sh` before proposing solutions. It handles all gitignored workstation config (venv, vault pass, direnv hook, SSH keys) and is the right place to extend — not new files, not git-tracked editor config, not dev containers.

---

### 2026-04-10

- When a forwardAuth callback fails, read `middleware-authentik.yaml` before forming any hypothesis. `authRequestHeaders` in Traefik v3 is an allowlist — if `Cookie` is not in it, session state never reaches the outpost.
- Read the relevant config or source before theorizing. One targeted `grep` beats three paragraphs of speculation.
- For `stacks/auth/auth`, the live control plane is the `auth` LXC via Ansible, not the workstation-local `docker compose` path. A local `proxy` network failure is a routing clue to switch to `ansible-playbook ... --limit auth`, not a reason to debug the repo stack locally.
- The Authentik Postgres bind mount at `/shared/auth/stacks/auth/appdata/database` must stay owned by UID:GID `70:70`. Letting the generic Docker environment role flatten it to `dockeruser` breaks Authentik startup with `pg_filenode.map: Permission denied`.
