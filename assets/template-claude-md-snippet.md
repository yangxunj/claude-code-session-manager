# CLAUDE.md Integration Snippet

Add the following section to your project's `CLAUDE.md` (or equivalent project instructions file).
Adjust paths and details to match your project structure.

---

```markdown
## Session Expert Management

This project maintains a **Session Expert Management System** in two files:

- `doc/reference/claude-sessions.md` — **Index file** (index table + page tree + file path index), lightweight, for quick lookup
- `doc/reference/claude-sessions-details.md` — **Details file** (functional domain descriptions, files involved per session), consult as needed

Each session expert is a historical conversation that has accumulated deep development context in a specific functional domain — the best recovery point for that domain.

### Required workflow when receiving change requests

**When a user requests any feature change, bug fix, or page optimization, you MUST follow this flow before deciding to do it yourself:**

1. **Read `doc/reference/claude-sessions.md`** (only this index file), scan the index table and page tree
2. **Determine if a session expert already owns this feature**: match by tags, page tree, or file path reverse-lookup
3. **If a matching session expert is found**:
   - Run `python scripts/claude-session.py list` to check if the session is resumable
   - If it shows `[----]` (expired), run `python scripts/claude-session.py activate <session-id>` to activate it
   - If `list` shows the jsonl is missing (size 0B or absent), run `python scripts/claude-session.py restore <session-id>` first to recover from the local backup
   - Recommend the user resume that session: `claude --resume <session-id>`
   - Explain the session's expertise and why it's better suited for this task
   - **Do NOT do the work yourself** unless the user explicitly asks you to
4. **If no matching session is found**: handle the request yourself

### Session backup / restore mechanism (important)

**Why this exists:**

- Claude Code only allows resuming the ~10 most recent sessions (sorted by the jsonl's last-message timestamp)
- Claude Code **periodically purges** jsonl files under `~/.claude/projects/<project>/` — once purged, `--resume` cannot recover them
- Therefore this project keeps a local backup in a **sibling directory** of the main repo: `<project-parent>/<project-name>-session-archives/`

**Key constraints:**

- The archive directory is **outside the main repo** — not pushed to GitHub (bypasses 100MB file limit, also avoids leaking chat content)
- **Do NOT `git init` inside the archive directory** — jsonl is append-only, so the latest version contains the entire history; "version control" is unnecessary. File-level validation (line count must not decrease + last line must parse as JSON) prevents a corrupted source from overwriting a good backup
- **Backup is append-only too** — even if the source jsonl is purged by Claude Code, the backup is retained (this is the entire point)

**Automatic trigger:** `.claude/settings.json` configures a SessionStart hook that runs `backup --quiet --async` in the background every time Claude Code starts. No-op when nothing has changed.

#### Command quick reference

| Command                                          | Purpose                                       | When to use                                                          |
| ------------------------------------------------ | --------------------------------------------- | -------------------------------------------------------------------- |
| `python scripts/claude-session.py list`          | List all sessions + status                    | **First step on every change request** — check expert availability   |
| `python scripts/claude-session.py activate <id>` | Bump timestamps so session re-enters top 10   | `list` shows `[----]` but jsonl is still present (non-zero size)     |
| `python scripts/claude-session.py restore <id>`  | Copy a backed-up jsonl back to ~/.claude/...  | `list` shows jsonl size 0B or file missing                           |
| `python scripts/claude-session.py restore --all` | Bulk-restore everything missing on the source | When you suspect Claude Code mass-purged                             |
| `python scripts/claude-session.py backup`        | Manual incremental backup                     | Usually unnecessary (the hook handles it); run after critical work   |

#### Decision tree: when the user asks for a change

```
1. Read doc/reference/claude-sessions.md, find a matching session expert
   ├─ No match → handle the request yourself, done
   └─ Match found: S0XX
        │
        ▼
2. Run `list` to check S0XX's status
   ├─ [ OK ]                   → claude --resume <id>
   ├─ [----] size > 0B         → activate → claude --resume <id>
   └─ [----] size = 0B / gone  → restore → activate → claude --resume <id>
                                  (recovers from sibling-directory backup)
```

#### Troubleshooting

| Question                                | Where to look                                                                          |
| --------------------------------------- | -------------------------------------------------------------------------------------- |
| Is the SessionStart hook actually running? | `tail <archive-dir>/backup.log` — check the most recent timestamp                   |
| Which sessions are backed up?           | `cat <archive-dir>/MANIFEST.md`                                                        |
| Were there any backup warnings?         | `grep WARN <archive-dir>/backup.log`                                                   |
| `restore` says "no archive matching"    | Check the `Session ID` column in MANIFEST.md — file is `<full-session-id>.jsonl(.bak)?` |
| Want to back up the current session immediately | `python scripts/claude-session.py backup` (synchronous; shows output)          |
| Archive directory was deleted / new machine | Restart Claude Code — the SessionStart hook will recreate it and back up everything live |
```

---

## Required project files

In addition to embedding the snippet above, an initialized project also needs:

1. **`scripts/claude-session.py`** — copied from this skill
2. **`doc/reference/claude-sessions.md`** — initialized from `assets/template-index.md`
3. **`doc/reference/claude-sessions-details.md`** — initialized from `assets/template-details.md`
4. **`.claude/settings.json`** — must contain the SessionStart hook:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python scripts/claude-session.py backup --quiet --async"
          }
        ]
      }
    ]
  }
}
```

5. **Sibling archive directory** — created automatically on first `backup` run; users should not put anything in it manually
