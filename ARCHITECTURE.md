# Architecture

How the pieces of this repository fit together, and what each one must not do. When a change
doesn't fit this, change this file first, on purpose, in the same commit.

## The shape

This repository is Claude Code's live configuration. `~/.claude/hooks`, `~/.claude/rules` and
`~/.claude/skills` are symbolic links into it, so whatever is on `main` in this checkout is what
every running Claude session loads, the moment it lands. That is why work happens in a worktree
under `~/Documents/worktrees/` and reaches `main` as one commit, never by switching branches
here. `~/.claude/settings.json` is outside the repository and wires the hooks to events. Codex
also runs one of these hooks, `git-guard.py`, from its own `hooks.json`.

## The pieces

| Piece | Responsibility | Interface | Fails how | Must not |
|---|---|---|---|---|
| `hooks/git-guard.py` | Refuse git and gh commands that skip the pull request workflow, for Claude and Codex | Claude Code and Codex PreToolUse event on stdin; a deny decision on stdout | Never blocks a command that names neither git nor gh | Judge a command by searching its text; loosen its rules for a caller it can't identify |
| `hooks/research-gate.py`, `research-log.py`, `research_log_shared.py` | Pace and record web fetches | PreToolUse and PostToolUse events | Gate refuses; recorder never blocks | Keep a second copy of the domain logic outside `research_log_shared.py` |
| `hooks/writing-style-gate.py` | Put the writing rules in front of a vault write | PreToolUse event, additional context | Never refuses | Refuse a write |
| `hooks/vale-post-lint.py` | Lint a post with Vale after it's written | PostToolUse event | Reports, never blocks | Edit the post |
| `hooks/buildlog-stop.py` | Nudge for an unlogged buildlog entry at session end | Stop event | Never blocks twice in a row | Write the buildlog itself |
| `hooks/vault-session-start.py`, `vault-precompact.py` | Put the vault's state into context; save material before compaction | SessionStart and PreCompact events | Fail quietly | Change any note |
| `hooks/claude-autoformat.sh` | Format a file after it's written, by extension | PostToolUse event | Leaves the file unchanged on error | Format a file type it doesn't know |
| `rules/` | Instructions loaded into every session | Markdown, loaded whole | — | Hold anything that only some sessions need; that belongs in a skill |
| `skills/` | One folder per skill: `SKILL.md` and its scripts | Loaded when the skill applies | Per skill | Duplicate a rule from `rules/` |
| `tools/` | Standalone scripts that aren't skills | Run by hand | — | Be wired to a hook |
| `vale/` | Vale's configuration and styles | Read by Vale | — | — |
| `tests/` | Tests for the hooks and tools | `python3 -m pytest` | — | Depend on the live `~/.claude` folder |

## Rules every piece follows

- **A hook that guards is a security control.** It's tested for what it must allow as much as for
  what it refuses, and it parses its input rather than pattern-matching text.
- **One owner per shared thing.** Shared domain logic lives in one module that the others import.
- **Hooks read their input from stdin and never depend on the current directory** being this
  repository.
- **Nothing here holds a secret.** Paths under `~/Documents/lockbox/` may be named; values never.
