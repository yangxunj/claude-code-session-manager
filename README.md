**English** | [中文](README_zh.md)

# Claude Code Session Manager

A skill for managing Claude Code sessions as reusable domain experts. Instead of starting fresh each time, sessions that have accumulated deep context in specific functional areas are documented and can be resumed when related work arises.

## Install

```bash
npx skills add yangxunj/claude-code-session-manager
```

## What it does

- **Route**: When a user requests a change, automatically check if a session expert already handles that domain and recommend resuming it
- **Register**: Let sessions self-evaluate and register themselves as domain experts with overlap detection
- **Activate**: Bring expired sessions back into Claude Code's resumable window (top ~10)
- **Initialize**: Set up session management for a new project with templates and tooling
- **Maintain**: Keep session documentation healthy with granularity guidelines

## How it works

Claude Code only allows resuming the ~10 most recent sessions, but all chat data is permanently stored on disk. This skill provides:

1. **Two-layer documentation** — A lightweight index file (tags, page tree, file path index) for quick routing, plus a details file for functional domain descriptions
2. **Activation script** — A Python CLI tool that modifies timestamps to bring old sessions back into the resumable window
3. **Self-registration prompt** — A template for sessions to evaluate whether they should register as experts (with >60% overlap detection)
4. **CLAUDE.md integration** — A snippet that instructs AI to check for session experts before handling requests

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Main skill instructions with 5 workflows |
| `scripts/claude-session.py` | Session management CLI (list / activate) |
| `references/registration-prompt.md` | Self-registration prompt template |
| `assets/template-index.md` | Index file template |
| `assets/template-details.md` | Details file template |
| `assets/template-claude-md-snippet.md` | CLAUDE.md integration snippet |

## Requirements

- Python 3.6+
- Claude Code CLI
- On Windows, use `PYTHONUTF8=1` prefix if Unicode errors occur

## License

MIT
