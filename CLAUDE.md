# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Commit Conventions

Never add `Co-Authored-By` trailers to commits in this repository.

## Explanation Style

Favor plain-cause explanations: name the behavior, say when it works, say when it breaks, then state the safer rule.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (faviann/homelab-iac) via the `gh` CLI; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles use their default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root (created lazily by `/domain-modeling`). See `docs/agents/domain.md`.
