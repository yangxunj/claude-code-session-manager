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
   - Recommend the user resume that session: `claude --resume <session-id>`
   - Explain the session's expertise and why it's better suited for this task
   - **Do NOT do the work yourself** unless the user explicitly asks you to
4. **If no matching session is found**: handle the request yourself

### Session management tools

```bash
# View all session statuses ([OK] = resumable, [----] = needs activation)
python scripts/claude-session.py list

# Activate an expired session (supports partial ID matching)
python scripts/claude-session.py activate <session-id>

# Then resume normally
claude --resume <session-id>
```
```
