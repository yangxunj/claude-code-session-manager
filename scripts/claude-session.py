#!/usr/bin/env python3
"""
Claude Code Session Management Tool

Features:
  list     - List all sessions for the current project, showing resumable status
  activate - Activate a session so it can be resumed via `claude --resume`
  backup   - Incrementally back up all jsonl files to a sibling directory
  restore  - Restore a backed-up jsonl back to ~/.claude/projects/<project>/

Background:
  Claude Code only allows resuming the ~10 most recent sessions (sorted by the
  last message timestamp in each .jsonl file), and it periodically purges the
  jsonl files under ~/.claude/projects/<project>/. This tool both shifts
  timestamps (to bring old sessions back into the resumable window) and
  maintains a sibling-directory backup so purged sessions can be restored.

Usage:
  python scripts/claude-session.py list
  python scripts/claude-session.py activate <session-id>
  python scripts/claude-session.py backup [--quiet] [--async]
  python scripts/claude-session.py restore <session-id> [--force]
  python scripts/claude-session.py restore --all
"""

import json
import os
import re
import shutil
import subprocess
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
ARCHIVE_ENV_VAR = "CLAUDE_SESSION_ARCHIVES"  # Optional: override default archive directory


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


# ── backup / restore shared helpers ──────────────────────────────────

def get_archive_dir():
    """Resolve the archive directory.

    Default: <cwd parent>/<cwd name>-session-archives/
    Override: set CLAUDE_SESSION_ARCHIVES environment variable.

    The default puts the archive in a sibling directory of the project so it:
      - lives outside the main repo (won't be pushed to GitHub, no 100MB limit)
      - is computed deterministically from cwd (no config file needed)
    """
    env_override = os.environ.get(ARCHIVE_ENV_VAR)
    if env_override:
        return Path(env_override)
    cwd = Path.cwd()
    return cwd.parent / f"{cwd.name}-session-archives"


def count_jsonl_lines(path):
    """Count non-empty lines in a jsonl file (each line is one message)."""
    if not path.exists():
        return 0
    count = 0
    with open(path, "rb") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def validate_jsonl_tail(path):
    """Validate that a jsonl file's last non-empty line is parseable JSON.

    Returns (ok: bool, reason: str). Used to detect truncation/corruption
    before letting a damaged source overwrite a good backup.
    """
    if not path.exists():
        return False, "file does not exist"
    try:
        last_line = None
        with open(path, "rb") as f:
            for line in f:
                line = line.strip()
                if line:
                    last_line = line
        if last_line is None:
            return False, "file is empty"
        json.loads(last_line.decode("utf-8"))
        return True, ""
    except json.JSONDecodeError as e:
        return False, f"last line failed JSON parse: {e}"
    except Exception as e:
        return False, f"read failed: {e}"


def spawn_async_self(extra_args):
    """Re-launch this script as a detached process and return immediately.

    Used by `backup --async` so the SessionStart hook doesn't add startup
    latency. Cross-platform: uses Windows DETACHED_PROCESS flags or POSIX
    start_new_session.
    """
    args = [sys.executable, str(Path(__file__).resolve())] + extra_args
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        # DETACHED_PROCESS = 0x00000008
        # CREATE_NEW_PROCESS_GROUP = 0x00000200
        # CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)


def write_log(archive_dir, msg):
    """Append a timestamped line to <archive>/backup.log."""
    log_path = archive_dir / "backup.log"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with open(log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ── backup command ───────────────────────────────────────────────────

def cmd_backup(argv):
    """Incrementally back up all jsonl files to the archive directory.

    Behavior:
      - Sources: ~/.claude/projects/<project>/*.jsonl (and *.jsonl.bak for
        legacy artifacts)
      - For each source:
          * not in archive yet → copy
          * in archive, sizes/lines match → skip (unchanged)
          * in archive, source has more lines → copy (jsonl is append-only)
          * in archive, source has FEWER lines → SKIP + WARN (truncation/corruption)
      - Source last-line JSON must parse, otherwise skip
      - Backup is never deleted, even if source disappears (the whole point)
      - MANIFEST.md is regenerated after each run
    """
    quiet = "--quiet" in argv
    if "--async" in argv:
        # Re-launch self as a detached process, drop --async
        new_args = [a for a in argv if a != "--async"]
        spawn_async_self(["backup"] + new_args)
        return

    project_dir = get_project_storage_dir()
    archive_dir = get_archive_dir()
    archive_dir.mkdir(parents=True, exist_ok=True)

    if not project_dir.exists():
        if not quiet:
            print(f"Project storage path does not exist: {project_dir}")
        write_log(archive_dir, f"backup skipped: project_dir missing ({project_dir})")
        sys.exit(0)

    if not quiet:
        print(f"Source: {project_dir}")
        print(f"Target: {archive_dir}")
        print()

    # Collect all jsonl / jsonl.bak files in the source
    sources = []
    for f in project_dir.iterdir():
        if not f.is_file():
            continue
        # Only back up .jsonl and .jsonl.bak; skip sessions-index.json and agent-* temp files
        if f.name == "sessions-index.json":
            continue
        if f.name.startswith("agent-"):
            continue
        if f.suffix == ".jsonl" or f.name.endswith(".jsonl.bak"):
            sources.append(f)

    if not sources:
        if not quiet:
            print("No jsonl files in source to back up")
        write_log(archive_dir, "backup skipped: no jsonl files in source")
        return

    copied = 0
    skipped_unchanged = 0
    skipped_corrupt = 0
    warnings = []

    for src in sorted(sources, key=lambda p: p.name):
        dest = archive_dir / src.name

        # Validate the source itself
        ok, reason = validate_jsonl_tail(src)
        if not ok:
            warnings.append(f"  [SKIP] {src.name} - source validation failed: {reason}")
            skipped_corrupt += 1
            continue

        if dest.exists():
            src_lines = count_jsonl_lines(src)
            dest_lines = count_jsonl_lines(dest)

            if src_lines == dest_lines and src.stat().st_size == dest.stat().st_size:
                skipped_unchanged += 1
                continue

            if src_lines < dest_lines:
                # jsonl is append-only — fewer lines in source means truncation/corruption
                warnings.append(
                    f"  [WARN] {src.name} - source lines {src_lines} < backup lines {dest_lines}, skipping overwrite"
                )
                skipped_corrupt += 1
                continue

        # Validation passed → copy (preserve mtime)
        shutil.copy2(src, dest)
        copied += 1
        if not quiet:
            print(f"  [OK]   {src.name} ({format_size(src.stat().st_size)})")

    # Rebuild MANIFEST
    manifest_path = archive_dir / "MANIFEST.md"
    write_manifest(archive_dir, manifest_path)

    summary = (
        f"backup done: copied={copied} unchanged={skipped_unchanged} "
        f"corrupt_skipped={skipped_corrupt}"
    )
    if warnings:
        summary += " [HAS WARNINGS]"
    write_log(archive_dir, summary)
    for w in warnings:
        write_log(archive_dir, w.strip())

    if not quiet:
        print()
        print(f"Done: copied {copied}, unchanged {skipped_unchanged}, skipped {skipped_corrupt}")
        if warnings:
            print()
            print("Warnings:")
            for w in warnings:
                print(w)


def write_manifest(archive_dir, manifest_path):
    """Rebuild MANIFEST.md based on the archive directory's current contents."""
    experts = load_session_experts()  # session-id → "S0XX Name"
    files = sorted(
        [
            f for f in archive_dir.iterdir()
            if f.is_file() and (f.suffix == ".jsonl" or f.name.endswith(".jsonl.bak"))
        ],
        key=lambda p: p.name,
    )

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Session Archives Manifest",
        "",
        f"Last updated: {now_iso}",
        "",
        f"Archive count: {len(files)}",
        "",
        "| Session ID | Registered | Size | Source last modified | Backup mtime | Notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for f in files:
        is_bak = f.name.endswith(".jsonl.bak")
        sid = f.name[:-len(".jsonl.bak")] if is_bak else f.stem
        expert = experts.get(sid, "")
        size = format_size(f.stat().st_size)
        # Last message timestamp from the source jsonl (if still present)
        project_dir = get_project_storage_dir()
        src_path = project_dir / f.name
        if src_path.exists():
            src_last_ts = get_last_timestamp_from_jsonl(src_path) or "N/A"
        else:
            src_last_ts = "(source purged by Claude Code)"
        backup_mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        note = ".bak (legacy rescue artifact)" if is_bak else ""
        lines.append(
            f"| `{sid[:8]}...` | {expert or '—'} | {size} | {src_last_ts[:19]} | {backup_mtime} | {note} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Auto-generated by `scripts/claude-session.py backup`. Do not edit manually.")
    lines.append("")

    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


# ── restore command ──────────────────────────────────────────────────

def cmd_restore(argv):
    """Restore a backed-up jsonl back to ~/.claude/projects/<project>/.

    Refuses to overwrite a live file that has more lines than the backup
    (live is canonical when newer); pass --force to override.
    """
    if not argv:
        print("Error: please provide a session-id or --all")
        print("Usage: python scripts/claude-session.py restore <session-id> [--force]")
        print("       python scripts/claude-session.py restore --all")
        sys.exit(1)

    project_dir = get_project_storage_dir()
    archive_dir = get_archive_dir()
    project_dir.mkdir(parents=True, exist_ok=True)

    if not archive_dir.exists():
        print(f"Error: archive directory does not exist: {archive_dir}")
        sys.exit(1)

    force = "--force" in argv
    target = next((a for a in argv if not a.startswith("--")), None)

    if target == "--all" or "--all" in argv:
        # Bulk restore: only copy files missing from source (don't overwrite existing)
        restored = 0
        skipped = 0
        for f in archive_dir.iterdir():
            if not (f.suffix == ".jsonl" or f.name.endswith(".jsonl.bak")):
                continue
            dest = project_dir / f.name
            if dest.exists() and not force:
                skipped += 1
                continue
            shutil.copy2(f, dest)
            restored += 1
            print(f"  Restored {f.name}")
        print()
        print(f"Done: restored {restored}, skipped {skipped} (already present; use --force to overwrite)")
        return

    if not target:
        print("Error: please provide a session-id")
        sys.exit(1)

    # Partial ID matching against archive contents
    matches = []
    for f in archive_dir.iterdir():
        if not f.is_file():
            continue
        if not (f.suffix == ".jsonl" or f.name.endswith(".jsonl.bak")):
            continue
        sid = f.name[:-len(".jsonl.bak")] if f.name.endswith(".jsonl.bak") else f.stem
        if sid.startswith(target) or target in sid:
            matches.append((sid, f))

    if not matches:
        print(f"Error: no archive matching '{target}'")
        sys.exit(1)
    if len(matches) > 1:
        print(f"Error: '{target}' matches multiple archives:")
        for sid, f in matches:
            print(f"  {f.name}")
        print("Please provide a more specific ID")
        sys.exit(1)

    sid, src = matches[0]
    dest = project_dir / src.name

    if dest.exists() and not force:
        # Compare line counts; if live is at least as long as backup, restoration is meaningless
        live_lines = count_jsonl_lines(dest)
        backup_lines = count_jsonl_lines(src)
        if live_lines >= backup_lines:
            print(f"Notice: live {src.name} lines ({live_lines}) >= backup ({backup_lines}); restore unnecessary")
            print("Pass --force to overwrite anyway")
            sys.exit(0)
        else:
            print(f"Warning: target exists but has fewer lines ({live_lines} < backup {backup_lines})")
            print("Pass --force to overwrite")
            sys.exit(1)

    shutil.copy2(src, dest)
    print(f"Restored {src.name} to {project_dir}")
    print()
    print("Next steps:")
    print(f"  python scripts/claude-session.py activate {sid}")
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
    elif command == "backup":
        cmd_backup(sys.argv[2:])
    elif command == "restore":
        cmd_restore(sys.argv[2:])
    else:
        print(f"Unknown command: {command}")
        print("Available commands: list, activate, backup, restore")
        sys.exit(1)


if __name__ == "__main__":
    main()
