# Session Self-Registration Prompt

Use this prompt to let a session evaluate whether it should register itself as a session expert. Copy and paste it into the session's conversation, replacing `<session-id>` and adjusting the index file path if needed.

---

## Prompt Template

```
Please read `doc/reference/claude-sessions.md` — this is the project's session expert index file.

Evaluate whether you should register yourself as a new session expert.

**Step 1: Overlap assessment**

Scan the index table and determine if any existing session highly overlaps with your work. If needed, check the details file `doc/reference/claude-sessions-details.md` for the session's functional domain description. Criteria:

- If an existing session's tags, functional domains, and files overlap >60% with yours, that domain already has an expert — do NOT register
- If your work is only minor fixes or parameter tweaks to an existing session's domain, do NOT register
- Only register when you have accumulated independent context that no existing session possesses

If you determine you should NOT register, tell the user: "Session [S0XX] already covers the main content of this work. Future related work should continue using that session — no need to register a duplicate." Then stop.

**Step 2: Register (only if Step 1 passes)**

Follow the "Session Registration Flow" and "Registration Granularity Guidelines" in `claude-sessions.md` to complete the registration in both the index file and the details file, then commit to git.

Your Session ID is: `<session-id>`
```

---

## How to get the session ID

Run this command in the session you want to register:

```bash
# The session ID is shown in the session list
python scripts/claude-session.py list
```

The current session's ID is the most recent entry (rank #1) in the list.
