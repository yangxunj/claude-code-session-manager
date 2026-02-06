#!/usr/bin/env python3
"""
Claude Code Session Management Tool

Features:
  list     - List all sessions for the current project, showing resumable status
  activate - Activate a session so it can be resumed via `claude --resume`

Background:
  Claude Code only allows resuming the ~10 most recent sessions (sorted by the
  last message timestamp in each .jsonl file). Older sessions still have their
  complete chat data on disk but cannot be resumed. This tool modifies timestamps
  to bring old sessions back into the resumable window.

Usage:
  python scripts/claude-session.py list
  python scripts/claude-session.py activate <session-id>
  python scripts/claude-session.py activate <partial-id>
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows UTF-8 output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# ── Configuration ────────────────────────────────────────────────────

CLAUDE_HOME = Path.home() / ".claude"
RESUMABLE_LIMIT = 10  # Number of recent sessions Claude Code allows resuming


def get_project_storage_dir():
    """Derive Claude's project storage path from the current working directory."""
    cwd = str(Path.cwd())
    # Claude's naming convention: replace : \ / with -
    # e.g., D:\Workspace\myProject -> D--Workspace-myProject
    dir_name = cwd.replace(":", "-").replace("\\", "-").replace("/", "-")
    return CLAUDE_HOME / "projects" / dir_name


def find_session_index_file():
    """Find the session expert index file in the project.

    Searches for common patterns:
    - doc/reference/claude-sessions.md (default convention)
    - Any .md file with a session index table header
    """
    cwd = Path.cwd()

    # Try the default convention first
    default_path = cwd / "doc" / "reference" / "claude-sessions.md"
    if default_path.exists():
        return default_path

    # Fallback: search for files containing the index table header
    for pattern in ["**/claude-sessions.md", "**/session-experts.md"]:
        for p in cwd.glob(pattern):
            return p

    return None


def load_sessions_index(project_dir):
    """Load sessions-index.json."""
    index_path = project_dir / "sessions-index.json"
    if not index_path.exists():
        print(f"Error: cannot find {index_path}")
        sys.exit(1)
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_sessions_index(project_dir, data):
    """Save sessions-index.json."""
    index_path = project_dir / "sessions-index.json"
    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_session_experts():
    """Load session expert index (if exists), return {session_id: expert_name} mapping.

    Parses the markdown index table looking for rows with format:
    | ID | Name | Tags | Status | Session ID |
    """
    experts = {}
    index_file = find_session_index_file()
    if not index_file:
        return experts

    with open(index_file, "r", encoding="utf-8") as f:
        in_table = False
        for line in f:
            line = line.strip()
            # Detect table header (flexible: matches various header patterns)
            if re.match(r"^\|.*(?:ID|编号).*\|.*(?:Name|名称).*\|", line, re.IGNORECASE):
                in_table = True
                continue
            if line.startswith("| ----") or line.startswith("|----"):
                continue
            if line.startswith("---"):
                in_table = False
                continue
            if in_table and line.startswith("|"):
                cols = [c.strip() for c in line.split("|")]
                # cols: ['', 'ID', 'Name', 'Tags', 'Status', 'Session ID', '']
                if len(cols) >= 6:
                    expert_id = cols[1]
                    expert_name = cols[2]
                    session_id = cols[5].strip("`").strip()
                    if session_id and re.match(r"^S\d+$", expert_id):
                        experts[session_id] = f"{expert_id} {expert_name}"
    return experts


def get_last_timestamp_from_jsonl(jsonl_path):
    """Read the timestamp of the last message with a timestamp from a .jsonl file."""
    if not jsonl_path.exists():
        return None

    last_ts = None
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                ts = obj.get("timestamp")
                if ts and ts != "N/A":
                    last_ts = ts
            except json.JSONDecodeError:
                continue
    return last_ts


def get_session_last_timestamps(project_dir):
    """Get last message timestamps for all sessions, return {session_id: timestamp_str}."""
    result = {}
    for f in project_dir.iterdir():
        if f.suffix == ".jsonl" and f.name != "sessions-index.json" and not f.name.startswith("agent-"):
            sid = f.stem
            ts = get_last_timestamp_from_jsonl(f)
            if ts:
                result[sid] = ts
    return result


def format_size(size_bytes):
    """Format file size for display."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


# ── list command ─────────────────────────────────────────────────────

def cmd_list():
    project_dir = get_project_storage_dir()
    print(f"Project storage: {project_dir}")
    print()

    index_data = load_sessions_index(project_dir)
    entries = index_data.get("entries", [])

    # Load session expert mapping
    experts = load_session_experts()

    # Get real last-message timestamps for each session
    real_timestamps = get_session_last_timestamps(project_dir)

    # Build display data
    sessions = []
    for e in entries:
        sid = e["sessionId"]
        jsonl_path = project_dir / f"{sid}.jsonl"
        file_size = jsonl_path.stat().st_size if jsonl_path.exists() else 0
        real_ts = real_timestamps.get(sid, e.get("modified", ""))
        sessions.append({
            "id": sid,
            "real_ts": real_ts,
            "index_modified": e.get("modified", ""),
            "msgs": e.get("messageCount", 0),
            "summary": e.get("summary", "") or "",
            "custom_title": e.get("customTitle", "") or "",
            "file_size": file_size,
            "expert": experts.get(sid, ""),
        })

    # Sort by real timestamp (descending)
    sessions.sort(key=lambda x: x["real_ts"], reverse=True)

    # Display
    print(f"Total {len(sessions)} sessions (top {RESUMABLE_LIMIT} are resumable)")
    print("=" * 110)

    for i, s in enumerate(sessions):
        is_resumable = i < RESUMABLE_LIMIT
        status = " OK " if is_resumable else "----"
        ts_display = s["real_ts"][:19].replace("T", " ") if s["real_ts"] else "N/A"
        size_str = format_size(s["file_size"])

        # Display name: prefer expert > custom_title > summary
        name = s["expert"]
        if not name:
            name = s["custom_title"][:40] if s["custom_title"] else s["summary"][:40]

        sid_short = s["id"][:8]

        print(f"  [{status}] {i + 1:>3}. {sid_short}... | {ts_display} | {s['msgs']:>3} msgs | {size_str:>7} | {name}")

    print()
    print("Hint: [OK] = resumable, [----] = needs `activate` first")
    print(f"Usage: python scripts/claude-session.py activate <session-id>")


# ── activate command ─────────────────────────────────────────────────

def cmd_activate(target_id):
    project_dir = get_project_storage_dir()
    index_data = load_sessions_index(project_dir)
    entries = index_data.get("entries", [])

    # Support partial ID matching
    matches = [e for e in entries if e["sessionId"].startswith(target_id)]
    if not matches:
        # Try fuzzy match
        matches = [e for e in entries if target_id in e["sessionId"]]

    if not matches:
        print(f"Error: no session matching '{target_id}'")
        sys.exit(1)
    elif len(matches) > 1:
        print(f"Error: '{target_id}' matches multiple sessions:")
        for m in matches:
            print(f"  {m['sessionId']}")
        print("Please provide a more specific ID")
        sys.exit(1)

    entry = matches[0]
    sid = entry["sessionId"]
    jsonl_path = project_dir / f"{sid}.jsonl"

    if not jsonl_path.exists():
        print(f"Error: cannot find chat log file {jsonl_path}")
        sys.exit(1)

    # Load session expert mapping
    experts = load_session_experts()
    expert_name = experts.get(sid, "")

    print(f"Session:  {sid}")
    if expert_name:
        print(f"Expert:   {expert_name}")
    print(f"Summary:  {entry.get('summary', 'N/A')}")
    print()

    # Generate new timestamp (current time)
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    now_mtime = int(now.timestamp() * 1000)

    # ── Step 1: Modify timestamps in the .jsonl file ──
    print("Step 1: Modifying chat log timestamps...")
    with open(jsonl_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find and modify the last 5 messages with timestamps
    modified_count = 0
    for idx in range(len(lines) - 1, max(len(lines) - 6, -1), -1):
        line = lines[idx].strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        old_ts = obj.get("timestamp")
        if old_ts and old_ts != "N/A":
            # Use incrementing seconds to avoid identical timestamps
            offset_seconds = modified_count
            ts = now.strftime(f"%Y-%m-%dT%H:%M:{offset_seconds:02d}.000Z")
            obj["timestamp"] = ts
            lines[idx] = json.dumps(obj, ensure_ascii=False) + "\n"
            print(f"  {old_ts} -> {ts}")
            modified_count += 1

    with open(jsonl_path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)
    print(f"  Modified {modified_count} message timestamps")

    # ── Step 2: Update sessions-index.json ──
    print()
    print("Step 2: Updating index file...")
    for e in index_data["entries"]:
        if e["sessionId"] == sid:
            old_modified = e.get("modified", "N/A")
            e["modified"] = now_iso
            e["fileMtime"] = now_mtime
            print(f"  modified: {old_modified} -> {now_iso}")
            break

    save_sessions_index(project_dir, index_data)
    print(f"  sessions-index.json updated")

    # ── Done ──
    print()
    print("Activation successful! You can now resume this session:")
    print(f"  claude --resume {sid}")


# ── Main entry ───────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1].lower()

    if command == "list":
        cmd_list()
    elif command == "activate":
        if len(sys.argv) < 3:
            print("Error: please provide a session ID")
            print("Usage: python scripts/claude-session.py activate <session-id>")
            sys.exit(1)
        cmd_activate(sys.argv[2])
    else:
        print(f"Unknown command: {command}")
        print("Available commands: list, activate")
        sys.exit(1)


if __name__ == "__main__":
    main()
