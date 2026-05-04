---
name: session-manager
description: |
  Session expert management system for Claude Code projects. Enables tracking, routing, activating, and registering conversation sessions as domain experts. Use this skill when:
  (1) Setting up session management for a new project (initialization)
  (2) A user requests a feature change, bug fix, or optimization and you need to check if a session expert already handles that domain (routing)
  (3) A session has accumulated deep domain context and should register itself as an expert (registration)
  (4) An existing session expert needs to update its registration after scope changes (update)
  (5) A session is expired and needs to be activated for resuming (activation)
  (6) The user asks about managing, organizing, or optimizing session documentation
---

# Session Manager

## Overview

This skill provides a complete system for managing Claude Code sessions as reusable domain experts. Instead of starting fresh each time, sessions that have accumulated deep context in specific functional areas are documented and can be resumed when related work arises.

## Workflow Decision Tree

```
User request arrives
│
├─ "Set up session management for this project"
│   └─ Go to → Initialize
│
├─ "This project already uses session-manager — sync it to the latest version"
│   └─ Go to → Migrate
│
├─ Feature change / bug fix / optimization request
│   └─ Go to → Route
│
├─ "Register this session as an expert"
│   └─ Go to → Register
│
├─ "Update this session's registration"
│   └─ Go to → Update
│
├─ "Activate / resume an old session"
│   └─ Go to → Activate
│
├─ "Restore a session whose jsonl was purged by Claude Code"
│   └─ Go to → Restore
│
└─ "Optimize session documentation structure"
    └─ Go to → Maintain
```

## Initialize

Set up session management for a project that doesn't have it yet.

**Steps:**

1. Copy `assets/template-index.md` to the project (recommended: `doc/reference/claude-sessions.md`)
2. Copy `assets/template-details.md` to the project (recommended: `doc/reference/claude-sessions-details.md`)
3. Copy `scripts/claude-session.py` to the project (recommended: `scripts/claude-session.py`)
4. Add the CLAUDE.md integration snippet from `assets/template-claude-md-snippet.md` to the project's CLAUDE.md
5. Create or update `.claude/settings.json` with the SessionStart hook (see `template-claude-md-snippet.md` for the exact JSON)
6. Customize the page tree structure in the index file to match the project's architecture
7. Run `python scripts/claude-session.py backup` once — this creates the sibling archive directory `<project-parent>/<project-name>-session-archives/` and captures any jsonl files already on disk
8. Commit all files (the archive directory must NOT be added to git — it lives outside the repo)

**Important notes:**

- The script requires Python 3.6+. On Windows, if Unicode errors occur, prefix with `PYTHONUTF8=1`.
- The archive directory is intentionally placed **outside** the project repo so it isn't accidentally pushed to GitHub (chat logs may be sensitive, plus single jsonl files can exceed GitHub's 100MB limit).
- Do NOT `git init` inside the archive directory. jsonl is append-only — the latest version always contains the entire history, so version control adds no value, and would just waste disk and risk accidental pushes.

## Migrate

Bring an already-initialized project up to the latest skill version (e.g., when this skill ships new features like the backup/restore mechanism).

**Trigger:** User says something like "sync this project to the latest session-manager skill" or "this project's claude-session.py is out of date".

**Steps:**

1. **Read** the project's existing `scripts/claude-session.py` and CLAUDE.md "Session Expert Management" section — understand what's there before overwriting
2. **Replace** the project's `scripts/claude-session.py` with the latest version from `<skill-root>/scripts/claude-session.py`. If the project translated the script to a different language (e.g., Chinese comments), preserve that style by porting only the new functions/messages
3. **Update** the project's CLAUDE.md "Session Expert Management" section using `assets/template-claude-md-snippet.md` as the reference. Preserve any project-specific customizations (e.g., custom file paths) but adopt the new structure (decision tree + command quick reference + troubleshooting table)
4. **Add or update** `.claude/settings.json` with the SessionStart hook (merge with any existing hooks/permissions)
5. **Run** `python scripts/claude-session.py backup` once to create the sibling archive directory and capture all currently surviving jsonl files
6. **Verify** by tailing `<archive-dir>/backup.log` — should show a recent `backup done` line
7. **Commit** the script + CLAUDE.md + settings.json changes (not the archive directory)
8. **Do NOT touch** the project's `claude-sessions.md` / `claude-sessions-details.md` actual data — only adopt new template structure if needed (e.g., add "Permanently lost sessions" section if relevant)

**What this preserves:** all existing session expert registrations, page tree, file path index, and details — Migrate only updates the *infrastructure*, not the project's accumulated data.

## Route

When a user requests any change, check if a session expert should handle it.

**Steps:**

1. Read the project's session index file (e.g., `doc/reference/claude-sessions.md`)
2. Scan the index table tags, page tree, and file path index
3. If a matching session is found:
   - Run `python scripts/claude-session.py list` to check its status
   - If `[----]` (expired): run `python scripts/claude-session.py activate <session-id>`
   - Recommend: `claude --resume <session-id>`
   - Explain why that session is better suited
   - Do NOT do the work yourself unless the user explicitly asks
4. If no match: handle the request yourself

**Why this matters:** A session expert has the complete conversation history — design decisions, pitfalls encountered, user preferences, architectural context. A new session reading the same code cannot reconstruct this implicit knowledge.

## Register

When a session has accumulated significant domain context, register it as an expert.

**Prerequisites:** The session must have genuine, independent domain context that no existing session covers.

**How to trigger:** Tell the session to read the index file and follow its built-in registration guide. For example:

```
Read `doc/reference/claude-sessions.md` — follow "Scenario A: New Session Registration" in the Registration & Update Guide. Your Session ID is: <session-id>
```

To find the session ID: `python scripts/claude-session.py list` — rank #1 is the current session.

The index file's built-in guide will instruct the session to:
1. Self-evaluate overlap against existing sessions (>60% overlap = do not register)
2. If assessment passes, write to 4 places: index table, page tree, file path index, details file
3. Commit to git

## Update

When an existing session expert's scope has changed after further development, update its registration.

**How to trigger:**

```
Read `doc/reference/claude-sessions.md` — follow "Scenario B: Update Existing Registration" in the Registration & Update Guide. Your Session ID is: <session-id>
```

The session will compare its current context against its registered info and update all four records accordingly.

## Activate

Resume a session that has fallen out of Claude Code's ~10 most recent (but whose jsonl is still on disk).

```bash
# Check which sessions are resumable
python scripts/claude-session.py list

# Activate an expired session
python scripts/claude-session.py activate <session-id>

# Resume it
claude --resume <session-id>
```

The script supports partial ID matching (e.g., `activate 3f5273` instead of the full UUID).

## Restore

Recover a session whose jsonl was purged by Claude Code (file no longer in `~/.claude/projects/<project>/`).

```bash
# Check status — purged sessions show 0B or are missing entirely
python scripts/claude-session.py list

# Restore from sibling-directory backup
python scripts/claude-session.py restore <session-id>

# Then bump timestamps and resume as usual
python scripts/claude-session.py activate <session-id>
claude --resume <session-id>
```

Bulk variant: `python scripts/claude-session.py restore --all` copies every backup whose source is currently missing (existing live files are not overwritten unless you pass `--force`).

**How the backup directory gets populated:** A SessionStart hook runs `backup --quiet --async` automatically every time Claude Code starts. The backup is incremental, validated (line count must not decrease, last line must parse as JSON), and never deletes — even if Claude Code purges the source. See `assets/template-claude-md-snippet.md` for the full mechanism.

## Backup

Manually trigger an incremental backup (the SessionStart hook does this automatically — usually unnecessary).

```bash
# Synchronous, prints what was copied
python scripts/claude-session.py backup

# What the SessionStart hook runs (silent, returns immediately)
python scripts/claude-session.py backup --quiet --async
```

**When to run manually:**

- You just finished critical work and want to capture it before closing the session
- You suspect the hook isn't firing — running this and checking `<archive-dir>/backup.log` will tell you
- You're about to do something risky (e.g., delete jsonl files or run experiments) and want a known-good snapshot first

## Maintain

Guidelines for keeping session documentation healthy:

- **Tags**: 5-8 functional domain keywords per session, no implementation details
- **Core abilities**: Describe "what the session understands", not "what it changed"
- **File paths**: Paths only, no parenthetical annotations
- **Overlap check**: Before registering, verify >60% overlap threshold against existing sessions
- **Status updates**: Mark sessions as `outdated` when their code has significantly changed, or `superseded:S0XX` when replaced

## Resources

### scripts/

- `claude-session.py` — Session management CLI tool. Subcommands:
  - `list` — show all sessions for the current project, with resumable status
  - `activate <id>` — bump timestamps so an old session re-enters the resumable top-10
  - `backup [--quiet] [--async]` — incremental backup to the sibling archive directory
  - `restore <id> [--force]` / `restore --all` — copy a backed-up jsonl back to `~/.claude/projects/<project>/`

  Copy to the target project's `scripts/` directory.

### assets/

- `template-index.md` — Template for the session index file (index table + page tree + file path index + built-in registration & update guide)
- `template-details.md` — Template for the session details file (per-session functional domain descriptions)
- `template-claude-md-snippet.md` — CLAUDE.md integration snippet (routing workflow + tool usage instructions)
