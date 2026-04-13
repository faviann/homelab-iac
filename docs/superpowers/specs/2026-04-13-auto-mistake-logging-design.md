# Auto Mistake Logging — Design

**Date**: 2026-04-13  
**Status**: approved

## Problem

During unattended or reduced-oversight sessions, Claude makes mistakes that are a normal part of development but don't get captured anywhere. The existing `/capture-issue` + `/solve-issues` pair requires the user to be present. There is no mechanism to accumulate mistakes into durable project wisdom without clogging the active session context.

## Goal

A lightweight, async feedback loop:
1. Claude self-logs mistakes during any session (attended or not)
2. Entries accumulate in a global queue file
3. The user periodically opens a fresh session, reviews the queue collaboratively, and each entry becomes a targeted artifact — a doc improvement, a skill, or an AGENTS.md edit — or gets discarded

## Components

### 1. Catalog file — `~/.claude/auto-issues.md`

Global file (not repo-committed). Acts as a queue: entries live here until processed, then are deleted.

**Entry format:**

```
## [N] <one-line title>
- Date: YYYY-MM-DD
- Repo: <only if local; omit for global>
- Type: mistake | behavior | inefficiency
- What happened: <one sentence>
- Root cause: <specific why>
- Cost: low | medium | high — <brief note on consequence>
- Fix pointer: <rough direction — non-binding>
- Context: <only if specific file/area; otherwise omit>
```

- `Repo:` absent implies global scope
- `Context:` absent implies no specific file anchor
- `Cost:` is Claude's estimate, not a precise calculation — guides triage weight in review
- `Fix pointer:` is explicitly non-binding; the review session may discard it

### 2. Skill — `/log-mistake`

Self-invoked by Claude. No user interaction required.

**Two modes:**

- **Immediate** — invoked mid-session the moment Claude recognizes a mistake. Fills the entry from current context, appends to `~/.claude/auto-issues.md`, continues working without interruption.
- **Reflective** — invoked at session wrap-up. Claude reviews what happened in the session and asks: did anything go wrong that isn't logged yet? If yes, logs it. If no issues, exits silently.

The reflective mode uses `~/.claude/session-log.txt` (written by the Stop hook) for lightweight context about the session.

### 3. Stop hook — safety net

Configured in `~/.claude/settings.json`. Fires a shell command at session end that appends a timestamped session marker to `~/.claude/session-log.txt`:

```
YYYY-MM-DD HH:MM — <working directory>
```

This gives the reflective mode of `/log-mistake` a breadcrumb to work from without requiring AI inference at hook time.

### 4. Skill — `/review-mistakes`

Invoked manually in a fresh session when the user is ready to process the queue.

**Flow:**

1. Read `~/.claude/auto-issues.md`. If empty, say so and stop.
2. Print all entries numbered.
3. For each entry, propose one artifact based on cost:
   - **low** — default: discard, unless a clear repeatable pattern is visible
   - **medium** — targeted doc clarification or specific note
   - **high** — full treatment: skill creation/edit, AGENTS.md edit, or doc rewrite
4. Discuss the proposal — the user may push back, redirect, or add context. Reach alignment before touching anything.
5. Execute the agreed change.
6. Delete the entry from `~/.claude/auto-issues.md`.

The review session is conversational, not a queue processor. Each entry gets discussed before anything is written.

## Artifact types (output of review)

| Artifact | When |
|----------|------|
| `AGENTS.md` / `CLAUDE.md` edit | Recurring assumption or process gap that affects all sessions |
| Specific doc improvement | A section of `stacks/README.md`, `docs/`, etc. was incomplete or misleading |
| New or updated skill | Mistake reveals a repeatable pattern worth encoding as a workflow |
| Discard | One-off mistake; no durable lesson worth encoding |

## What this is not

- Not a replacement for `/capture-issue` (that remains for user-present, in-context captures)
- Not an archive — the queue file is deleted on process, not accumulated indefinitely
- Not automated fixing — the review session always involves the user before any artifact is written

## Files created

| File | Purpose |
|------|---------|
| `~/.claude/auto-issues.md` | The queue |
| `~/.claude/session-log.txt` | Lightweight session markers written by Stop hook |
| `~/.claude/skills/log-mistake/SKILL.md` | Self-invoked logging skill |
| `~/.claude/skills/review-mistakes/SKILL.md` | Review session skill |
| `~/.claude/settings.json` | Stop hook entry |
