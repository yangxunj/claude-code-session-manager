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


def is_forked_session(jsonl_path):
    """Check if a session is a fork by inspecting the first message's forkedFrom field.

    Forked sessions cannot be resumed by Claude Code. The activate command
    will automatically strip forkedFrom fields to make them resumable.
    """
    if not jsonl_path.exists():
        return False
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                return bool(obj.get("forkedFrom"))
            except json.JSONDecodeError:
                continue
    return False


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


def build_index_entry_from_jsonl(jsonl_path):
    """Build a sessions-index entry from a .jsonl file (for sessions missing from the index)."""
    sid = jsonl_path.stem
    first_ts = None
    last_ts = None
    first_prompt = ""
    msg_count = 0

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg_count += 1
            ts = obj.get("timestamp")
            if ts and ts != "N/A":
                if first_ts is None:
                    first_ts = ts
                last_ts = ts
            # Extract firstPrompt from the first user message
            if not first_prompt and obj.get("type") == "user":
                msg = obj.get("message", {})
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        first_prompt = content[:200]
                    elif isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                first_prompt = (part.get("text") or "")[:200]
                                break

    file_mtime = int(jsonl_path.stat().st_mtime * 1000)

    return {
        "sessionId": sid,
        "fullPath": str(jsonl_path),
        "fileMtime": file_mtime,
        "firstPrompt": first_prompt,
        "summary": "",
        "messageCount": msg_count,
        "created": first_ts or "",
        "modified": last_ts or "",
        "gitBranch": "main",
        "projectPath": str(Path.cwd()),
        "isSidechain": False,
    }


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

    # Get the mtime of sessions-index.json itself (used to distinguish stale vs active mtime mismatches)
    index_file_path = project_dir / "sessions-index.json"
    index_file_mtime = int(index_file_path.stat().st_mtime * 1000)

    # Load session expert mapping
    experts = load_session_experts()

    # Get real last-message timestamps for each session
    real_timestamps = get_session_last_timestamps(project_dir)

    # Build display data
    sessions = []
    for e in entries:
        sid = e["sessionId"]
        jsonl_path = project_dir / f"{sid}.jsonl"
        file_exists = jsonl_path.exists()
        file_size = jsonl_path.stat().st_size if file_exists else 0
        real_ts = real_timestamps.get(sid, e.get("modified", ""))
        forked = is_forked_session(jsonl_path) if file_exists else False

        # Check fileMtime consistency
        # mtime_status: "ok" / "stale" / "active"
        # - ok:     fileMtime in index matches actual file mtime
        # - stale:  .jsonl was modified BEFORE index was last written, but index has wrong mtime (real problem)
        # - active: .jsonl was modified AFTER index was last written (normal Claude Code writes, harmless)
        mtime_status = "ok"
        if file_exists:
            actual_mtime = int(jsonl_path.stat().st_mtime * 1000)
            index_mtime = e.get("fileMtime", 0)
            if actual_mtime != index_mtime:
                if actual_mtime <= index_file_mtime:
                    # File was modified before last index write, but index has wrong value → real problem
                    mtime_status = "stale"
                else:
                    # File was modified after last index write (normal Claude Code writes)
                    mtime_status = "active"

        sessions.append({
            "id": sid,
            "real_ts": real_ts,
            "index_modified": e.get("modified", ""),
            "msgs": e.get("messageCount", 0),
            "summary": e.get("summary", "") or "",
            "custom_title": e.get("customTitle", "") or "",
            "file_size": file_size,
            "expert": experts.get(sid, ""),
            "forked": forked,
            "mtime_status": mtime_status,
        })

    # Detect .jsonl files on disk that are missing from the index
    indexed_ids = {e["sessionId"] for e in entries}
    orphan_count = 0
    for f in project_dir.iterdir():
        if (f.suffix == ".jsonl"
                and f.stem != "sessions-index"
                and not f.stem.startswith("agent-")
                and f.stem not in indexed_ids):
            sid = f.stem
            real_ts = real_timestamps.get(sid, "")
            forked = is_forked_session(f)
            sessions.append({
                "id": sid,
                "real_ts": real_ts,
                "index_modified": "",
                "msgs": 0,  # Skip full parse to keep list fast
                "summary": "",
                "custom_title": "",
                "file_size": f.stat().st_size,
                "expert": experts.get(sid, ""),
                "forked": forked,
                "mtime_status": "orphan",  # File on disk but missing from index
            })
            orphan_count += 1

    # Sort by real timestamp (descending)
    sessions.sort(key=lambda x: x["real_ts"], reverse=True)

    # Display
    total_indexed = len(entries)
    print(f"Total {len(sessions)} sessions (indexed {total_indexed} + unindexed {orphan_count}, top {RESUMABLE_LIMIT} resumable)")
    print("=" * 110)

    fork_count = 0
    stale_count = 0
    orphan_display_count = 0
    for i, s in enumerate(sessions):
        is_resumable = i < RESUMABLE_LIMIT
        if s["mtime_status"] == "orphan":
            status = "ORPH"
            orphan_display_count += 1
        elif s["forked"]:
            status = "FORK"
            fork_count += 1
        elif is_resumable and s["mtime_status"] == "stale":
            status = "STAL"
            stale_count += 1
        elif is_resumable:
            status = " OK "
        else:
            status = "----"
        ts_display = s["real_ts"][:19].replace("T", " ") if s["real_ts"] else "N/A"
        size_str = format_size(s["file_size"])

        # Display name: prefer expert > custom_title > summary
        name = s["expert"]
        if not name:
            name = s["custom_title"][:40] if s["custom_title"] else s["summary"][:40]

        sid_short = s["id"][:8]
        msgs_str = f"{s['msgs']:>3} msgs" if s["mtime_status"] != "orphan" else "  ? msgs"

        print(f"  [{status}] {i + 1:>3}. {sid_short}... | {ts_display} | {msgs_str} | {size_str:>7} | {name}")

    print()
    print("Hint: [OK] = resumable, [----] = needs `activate`, [FORK] = forked, [STAL] = stale index, [ORPH] = unindexed")
    if fork_count:
        print(f"Found {fork_count} forked session(s). Running `activate` will auto-remove forkedFrom fields.")
    if stale_count:
        print(f"Found {stale_count} session(s) with stale index entries. Run `activate` to fix before resuming.")
    if orphan_display_count:
        print(f"Found {orphan_display_count} session(s) on disk but missing from index. Run `activate` to register.")
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
        # Not in index — check for .jsonl files on disk
        disk_matches = list(project_dir.glob(f"{target_id}*.jsonl"))
        if not disk_matches:
            disk_matches = [f for f in project_dir.glob("*.jsonl")
                           if target_id in f.stem and not f.stem.startswith("agent-")]
        if not disk_matches:
            print(f"Error: no session matching '{target_id}' (checked both index and disk)")
            sys.exit(1)
        if len(disk_matches) > 1:
            print(f"Error: '{target_id}' matches multiple files on disk:")
            for f in disk_matches:
                print(f"  {f.stem}")
            print("Please provide a more specific ID")
            sys.exit(1)

        # Build index entry from .jsonl file and register it
        jsonl_file = disk_matches[0]
        print(f"Not found in index, but exists on disk: {jsonl_file.name}")
        print("Building index entry from chat log...")
        new_entry = build_index_entry_from_jsonl(jsonl_file)
        index_data["entries"].append(new_entry)
        save_sessions_index(project_dir, index_data)
        print(f"  Registered in sessions-index.json ({new_entry['messageCount']} messages)")
        print()
        matches = [new_entry]

    if len(matches) > 1:
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

    # ── Step 1: Read and process the .jsonl file ──
    with open(jsonl_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Detect if this is a forked session (check first message)
    is_fork = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            first_obj = json.loads(stripped)
            is_fork = bool(first_obj.get("forkedFrom"))
            break
        except json.JSONDecodeError:
            continue

    # If forked, strip forkedFrom from all messages (required for resumability)
    if is_fork:
        print("Step 1a: Forked session detected, removing forkedFrom fields...")
        fork_removed = 0
        for idx in range(len(lines)):
            stripped = lines[idx].strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if "forkedFrom" in obj:
                del obj["forkedFrom"]
                lines[idx] = json.dumps(obj, ensure_ascii=False) + "\n"
                fork_removed += 1
        print(f"  Removed forkedFrom from {fork_removed} messages")
        print()

    # Modify timestamps of the last few messages
    step_label = "Step 1b" if is_fork else "Step 1"
    print(f"{step_label}: Modifying chat log timestamps...")
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

    # Read actual file mtime after writing (Claude Code validates this)
    actual_mtime = int(jsonl_path.stat().st_mtime * 1000)

    # ── Step 2: Update sessions-index.json ──
    print()
    print("Step 2: Updating index file...")
    for e in index_data["entries"]:
        if e["sessionId"] == sid:
            old_modified = e.get("modified", "N/A")
            e["modified"] = now_iso
            e["fileMtime"] = actual_mtime
            print(f"  modified: {old_modified} -> {now_iso}")
            print(f"  fileMtime: {actual_mtime}")
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
