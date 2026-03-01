# Session Expert Management

## AI Usage Guide

This file records all valuable Claude Code sessions (conversation experts) in the project. Each session has accumulated deep development context in a specific functional domain and serves as the best recovery point for that domain.

**File structure:**

- **This file** (`claude-sessions.md`) — Index layer: index table, page tree, file path index. Most scenarios only need this file to locate a session.
- **Details file** (`claude-sessions-details.md`) — Functional domain descriptions and files for each session. Only read when you need to deeply understand a specific session.
- **Management script** (`scripts/claude-session.py`) — List all session statuses, activate expired sessions to make them resumable.

**Lookup flow:**

1. Scan the "Index Table" — match by tags and name to find candidate sessions
2. For page-related issues, check the "Page Tree" to find sessions mounted on page nodes
3. If you know the specific file, check the "File Path Index" to reverse-lookup associated sessions
4. The index table includes Session IDs — you can directly recommend the user to resume
5. If further confirmation is needed, read the corresponding session's details in the details file
6. Recommend to the user: `claude --resume <session-id>`

**Disambiguation rule:** When multiple sessions are mounted on the same node, each ID in the page tree has a responsibility annotation (e.g., `S002:status display/buttons`). Match the session based on what the user wants to optimize. If unsure, recommend the best-matching one and mention other related sessions.

**Status values:**

- `active` — Session context is still valid, can be resumed directly
- `outdated` — Related code has changed significantly, context may be stale, for reference only
- `superseded:S0XX` — Has been replaced by the specified session

**Session Registration & Update Guide:**

When the user asks you to register or update your session info, choose the appropriate scenario below. The user will provide your Session ID.

**Scenario A: New Session Registration**

Applies when: you have accumulated deep context in a new functional domain and need to register as an expert for the first time.

Step 1 — Overlap assessment (must do first):

Read the index table below and determine if any existing session highly overlaps with your work. If needed, check the details file for that session's functional domain description.

- If an existing session's tags, functional domains, and files overlap >60% with yours, that domain already has an expert — **do NOT register**
- If your work is only minor fixes or parameter tweaks to an existing session's domain, **do NOT register**
- Only register when you have accumulated **independent context that no existing session possesses**

If you determine you should NOT register, tell the user: "Session [S0XX] already covers the main content of this work. Future related work should continue using that session — no need to register a duplicate." Then stop.

Step 2 — Execute registration (only if assessment passes):

1. **Update index table**: Add a new row in this file's index table
2. **Update page tree**: Mount the session ID on the corresponding page node
3. **Update file path index**: Add the key files involved
4. **Update details file**: Add functional domain descriptions and files in the details file
5. **Commit to git**: Commit all changes together

**Scenario B: Update Existing Registration**

Applies when: you are an already-registered session expert, and after further development, your functional scope has changed.

1. **Read current registration**: Find your entries in the index table, page tree, file path index, and details file
2. **Compare with actual work**: Compare the context accumulated in this conversation against your registered info — identify differences (new functional domains? new files involved? tags need adjusting?)
3. **Update all four records**: Index table (name/tags), page tree (node mounts), file path index (add/remove paths), details file (core abilities/files)
4. **Commit to git**

**Granularity guidelines (applies to both registration and updates):**

Session documentation exists for **routing** — helping new sessions quickly find "who should handle this problem", not for recording work logs. After resuming a session, the complete conversation context is already there; the documentation doesn't need to repeat it.

Tags should be functional domain keywords only (5-8), not implementation details:

- ✅ `dimension-weights, score-calculation, grading-strategy`
- ❌ `LIST_IGNORE, fileList, originFileObj, slider-tooltip`

Core abilities should describe "what I understand", not "what I changed":

- ✅ `antd-img-crop cropping component integration and source-level understanding`
- ❌ `After antd-img-crop cropping, if beforeUpload returns false, antd Upload still keeps the original file's originFileObj...`

File paths should be paths only, no parenthetical annotations:

- ✅ `frontend/src/components/UploadModal.tsx`
- ❌ `frontend/src/components/UploadModal.tsx (core: ImgCrop integration + beforeUpload changed to LIST_IGNORE mode)`

**Resuming expired sessions:**

Claude Code only allows resuming the ~10 most recent sessions (sorted by last message timestamp), but all session chat data is permanently stored on disk (`~/.claude/projects/`).

When you need to resume a session that has fallen out of the top 10:

```bash
# View all session statuses
python scripts/claude-session.py list

# Activate a specific session (supports partial ID matching)
python scripts/claude-session.py activate <session-id>

# Then resume normally
claude --resume <session-id>
```

---

## Index Table

| ID   | Name | Tags | Status | Session ID |
| ---- | ---- | ---- | ------ | ---------- |
| S001 | (example) | tag1, tag2, tag3 | active | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |

---

## Page Tree

```
├── Frontend
│   ├── Page A → [S001]
│   └── Page B → (no session yet)
│
├── Backend
│   ├── Module A → [S001]
│   └── Module B → (no session yet)
│
└── Non-code
    └── Documentation → (no session yet)
```

---

## File Path Index

| File Path | Associated Sessions |
| --------- | ------------------- |
| `frontend/src/pages/Example.tsx` | S001 |

> Detailed records are in the details file — consult as needed.
