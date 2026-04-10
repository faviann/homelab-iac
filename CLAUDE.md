# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

---

## Do Not Try Again (Running Mistake Log)

This is a permanent log. When you make a mistake on this project, add an entry here before the session ends. Future Claude instances must read this and not repeat these approaches. Be specific — vague lessons are useless.

---

### 2026-04-10

- When a forwardAuth callback fails, read `middleware-authentik.yaml` before forming any hypothesis. `authRequestHeaders` in Traefik v3 is an allowlist — if `Cookie` is not in it, session state never reaches the outpost.
- Read the relevant config or source before theorizing. One targeted `grep` beats three paragraphs of speculation.
