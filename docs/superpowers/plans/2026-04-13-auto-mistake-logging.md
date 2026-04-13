# Auto Mistake Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-logging mistake system that captures errors during unattended sessions into a queue file, then drains that queue collaboratively in a fresh review session producing targeted project artifacts.

**Architecture:** Two skills (`/log-mistake`, `/review-mistakes`) backed by a plain markdown queue file (`~/.claude/auto-issues.md`). A Stop hook appends lightweight session markers to `~/.claude/session-log.txt` as a safety net for the reflective logging mode. No code — all markdown skill files and a JSON settings patch.

**Tech Stack:** Claude Code skill system (markdown SKILL.md files), `~/.claude/settings.json` hooks, shell (date/echo for the hook command)

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `~/.claude/auto-issues.md` | The mistake queue |
| Create | `~/.claude/skills/log-mistake/SKILL.md` | Self-invoked logging skill |
| Create | `~/.claude/skills/review-mistakes/SKILL.md` | Review session skill |
| Modify | `~/.claude/settings.json` | Add Stop hook |

---

### Task 1: Initialize the queue file

**Files:**
- Create: `~/.claude/auto-issues.md`

- [ ] **Step 1: Create the empty queue file**

```bash
touch ~/.claude/auto-issues.md
```

- [ ] **Step 2: Verify it exists**

```bash
ls -la ~/.claude/auto-issues.md
```

Expected: file present, 0 bytes.

- [ ] **Step 3: Commit**

This file is in `~/.claude/` (not the repo), so no git commit needed. Move on.

---

### Task 2: Write the `/log-mistake` skill

**Files:**
- Create: `~/.claude/skills/log-mistake/SKILL.md`

- [ ] **Step 1: Create the skill directory**

```bash
mkdir -p ~/.claude/skills/log-mistake
```

- [ ] **Step 2: Write the skill file**

Write the following to `~/.claude/skills/log-mistake/SKILL.md`:

```markdown
---
name: log-mistake
description: Self-log a mistake, behavior issue, or inefficiency during or at the end of an unattended session. Appends a structured entry to ~/.claude/auto-issues.md without interrupting work. Only invoked explicitly — never auto-triggered.
disable-model-invocation: true
---

# log-mistake

Log a mistake to the async queue. Fast. Non-interrupting.

---

## When to invoke

- **Immediately** — the moment you recognize a mistake mid-session
- **Reflectively** — at session wrap-up, scan for anything not yet logged

---

## Immediate mode

You just recognized a mistake. Fill the entry from current context and append it.

Do not ask for user confirmation. Do not interrupt current work.

---

## Reflective mode

Invoked at session wrap-up. Read `~/.claude/session-log.txt` if it exists for lightweight session context.

Ask yourself: did anything go wrong in this session that is not yet logged in `~/.claude/auto-issues.md`?

- If yes: fill and append the entry, then continue to wrap-up
- If nothing to log: exit silently — do not announce this

---

## Entry format

First, read `~/.claude/auto-issues.md` to determine the next N. Then append:

~~~markdown
## [N] <one-line title>
- Date: YYYY-MM-DD
- Repo: <only if local; omit for global>
- Type: mistake | behavior | inefficiency
- What happened: <one sentence>
- Root cause: <specific why>
- Cost: low | medium | high — <brief note on consequence>
- Fix pointer: <rough direction — non-binding>
- Context: <only if specific file/area; otherwise omit>
~~~

**Cost guide:**
- **low** — minor friction, easily recovered
- **medium** — wasted meaningful work or caused a wrong assumption to propagate
- **high** — broke something, required significant recovery, or caused the user to intervene

`Fix pointer` is explicitly non-binding. The review session may discard it entirely.

---

## After appending

Continue without comment. Do not print the entry. Do not announce the logging.
```

- [ ] **Step 3: Verify the file was written**

```bash
head -5 ~/.claude/skills/log-mistake/SKILL.md
```

Expected: frontmatter starting with `---` and `name: log-mistake`.

---

### Task 3: Write the `/review-mistakes` skill

**Files:**
- Create: `~/.claude/skills/review-mistakes/SKILL.md`

- [ ] **Step 1: Create the skill directory**

```bash
mkdir -p ~/.claude/skills/review-mistakes
```

- [ ] **Step 2: Write the skill file**

Write the following to `~/.claude/skills/review-mistakes/SKILL.md`:

```markdown
---
name: review-mistakes
description: Review the auto-logged mistake queue in a fresh session. Triage each entry collaboratively with the user and produce a targeted artifact (doc edit, skill update, AGENTS.md change) or discard. Only invoked explicitly via /review-mistakes.
disable-model-invocation: true
---

# review-mistakes

Process the auto-logged mistake queue. One entry at a time, collaboratively.

---

## Step 1 — Read the queue

Read `~/.claude/auto-issues.md`. If the file is empty or doesn't exist, say so and stop.

Print all entries numbered:

```
[N] <type> — <what happened> (<date>) [cost: <level>]
```

---

## Step 2 — Triage loop

Work through entries one at a time. For each entry:

1. Read the full entry
2. Locate the relevant repo and files using `Repo:` and `Context:` fields — read those files, do not theorize
3. Propose one artifact based on cost:
   - **low** — default: discard. Propose a real artifact only if you see a clear repeatable pattern
   - **medium** — propose a targeted doc clarification or specific note
   - **high** — propose full treatment: skill creation/edit, AGENTS.md edit, or doc rewrite
4. Present the proposal with your reasoning
5. Discuss — the user may push back, redirect, or add context. Reach alignment before touching anything.
6. Execute the agreed change
7. Delete the entry from `~/.claude/auto-issues.md`

Do not batch entries. Do not move to the next entry until the current one is fully resolved and deleted from the file.

---

## Artifact types

| Artifact | When |
|----------|------|
| `AGENTS.md` / `CLAUDE.md` edit | Recurring assumption or process gap affecting all sessions |
| Specific doc improvement | A section of `stacks/README.md`, `docs/`, etc. was incomplete or misleading |
| New or updated skill | Mistake reveals a repeatable pattern worth encoding as a workflow |
| Discard | One-off mistake; no durable lesson worth encoding |

---

## After all entries are processed

Confirm the queue is empty. Say so briefly and stop.
```

- [ ] **Step 3: Verify the file was written**

```bash
head -5 ~/.claude/skills/review-mistakes/SKILL.md
```

Expected: frontmatter starting with `---` and `name: review-mistakes`.

---

### Task 4: Add the Stop hook

**Files:**
- Modify: `~/.claude/settings.json`

The Stop hook appends a timestamped session marker to `~/.claude/session-log.txt`. This is a shell-only operation — no AI invocation at hook time.

- [ ] **Step 1: Read the current settings.json**

```bash
cat ~/.claude/settings.json
```

- [ ] **Step 2: Write the updated settings.json**

Merge the `hooks` key into the existing JSON. The final file must be valid JSON containing all existing keys plus the new `hooks` section:

```json
{
  "enabledPlugins": {
    "skill-creator@claude-plugins-official": true,
    "superpowers@claude-plugins-official": true
  },
  "extraKnownMarketplaces": {
    "superpowers-marketplace": {
      "source": {
        "source": "github",
        "repo": "obra/superpowers-marketplace"
      }
    },
    "anthropic-agent-skills": {
      "source": {
        "source": "github",
        "repo": "anthropics/skills"
      }
    }
  },
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo \"$(date '+%Y-%m-%d %H:%M') — $(pwd)\" >> /home/aperture/.claude/session-log.txt"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 3: Verify the JSON is valid**

```bash
python3 -m json.tool ~/.claude/settings.json > /dev/null && echo "valid"
```

Expected: `valid`

---

### Task 5: Verify end-to-end

No automated tests exist for markdown skills. Manual verification covers the two critical paths.

- [ ] **Step 1: Verify both skills are discoverable**

```bash
ls ~/.claude/skills/log-mistake/SKILL.md ~/.claude/skills/review-mistakes/SKILL.md
```

Expected: both paths printed with no errors.

- [ ] **Step 2: Simulate an immediate log entry**

Manually append a test entry to `~/.claude/auto-issues.md` to verify the format parses correctly in a future review:

```bash
cat >> ~/.claude/auto-issues.md << 'EOF'

## [1] Test entry — verify queue format
- Date: 2026-04-13
- Type: mistake
- What happened: Manually added to verify the queue file and review skill work correctly.
- Root cause: Intentional test entry.
- Cost: low — no real consequence
- Fix pointer: Delete this entry during first /review-mistakes session
EOF
```

- [ ] **Step 3: Verify the entry was appended**

```bash
cat ~/.claude/auto-issues.md
```

Expected: the entry printed cleanly with correct markdown structure.

- [ ] **Step 4: Verify the Stop hook shell command syntax**

```bash
echo "$(date '+%Y-%m-%d %H:%M') — $(pwd)" >> /tmp/session-log-test.txt && cat /tmp/session-log-test.txt && rm /tmp/session-log-test.txt
```

Expected: a line like `2026-04-13 14:32 — /home/aperture/ServerManagementScripts` printed cleanly.

- [ ] **Step 5: Commit the plan**

The plan doc lives in the repo:

```bash
cd ~/ServerManagementScripts
git add docs/superpowers/plans/2026-04-13-auto-mistake-logging.md
git commit -m "Add auto mistake logging implementation plan"
```
