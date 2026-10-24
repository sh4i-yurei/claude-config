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
| `hooks/git-guard.py`, `hooks/bashlex_compat.py` | Warn Claude and Codex before guarded git and gh actions; correct parser quoting in one compatibility module imported once per process | PreToolUse event on stdin; optional `--agent claude` hint; deny decision on stdout; vendored bashlex 0.18; 64 KB command cap and five-second judgement budget | Malformed events, oversized commands, and internal errors return a deny decision; hook startup failures and timeouts depend on the agent runtime | Judge commands by text search; treat an agent flag as identity proof; replace GitHub branch rules |
| `hooks/research-gate.py`, `research-log.py`, `research_log_shared.py` | Pace and record web fetches | PreToolUse and PostToolUse events | Gate refuses; recorder never blocks | Keep a second copy of the domain logic outside `research_log_shared.py` |
| `hooks/writing-style-gate.py` | Put the writing rules in front of a vault write | PreToolUse event, additional context | Never refuses | Refuse a write |
| `hooks/handoff-check.py` | Check build handoffs against the live build template before a Write or Edit | Claude Code PreToolUse event on stdin; a deny decision on stdout | Allows the write with a warning if the template cannot be read | Check handoffs without the build template field or paths outside `05_Agents/handoffs/` |
| `hooks/vale-post-lint.py` | Lint a post with Vale after it's written | PostToolUse event | Reports, never blocks | Edit the post |
| `hooks/buildlog-stop.py` | Nudge for an unlogged buildlog entry at session end | Stop event | Never blocks twice in a row | Write the buildlog itself |
| `hooks/vault-session-start.py`, `vault-precompact.py` | Put the vault's state into context; save material before compaction | SessionStart and PreCompact events | Fail quietly | Change any note |
| `hooks/claude-autoformat.sh` | Format a file after it's written, by extension | PostToolUse event | Leaves the file unchanged on error | Format a file type it doesn't know |
| `rules/` | Instructions loaded into every session | Markdown, loaded whole | — | Hold anything that only some sessions need; that belongs in a skill |
| `skills/` | One folder per skill: `SKILL.md` and its scripts | Loaded when the skill applies | Per skill | Duplicate a rule from `rules/` |
| `tools/` | Standalone scripts that aren't skills | Run by hand | — | Be wired to a hook |
| `tools/workflow/labels.toml` | Define global labels and each repository's scope labels | TOML tables keyed by label name and repository | Invalid definitions stop the sync before GitHub calls | Include GitHub's default labels or a repository list for global labels |
| `tools/workflow/workflow.toml` | Define owners to query and repositories all workflow tools skip | `owners` and `exceptions` TOML arrays; G3 adds board mappings | Invalid configuration stops the sync before GitHub calls | Enumerate active repositories or hold label definitions |
| `tools/workflow/config.py` | Read and validate both workflow TOML files for tools | `load()` returns owners, exceptions and label maps; raises `ConfigError` naming a bad file | Refuses missing or malformed configuration | Make GitHub calls or mutate labels |
| `tools/workflow/sync_labels.py` | Query GitHub repositories and reconcile their labels | `python3 tools/workflow/sync_labels.py [--dry-run]`; exit 0 for success, 1 for labels still used by open issues or pull requests, 2 for an error | Stops on a failed GitHub call; names kept labels and continues | Read TOML itself, list repositories in code, delete a label used by an open issue or pull request, or write in dry-run mode |
| `vale/` | Vale's configuration and styles | Read by Vale | — | — |
| `tests/` | Tests for the hooks and tools | `python3 -m pytest` | — | Depend on the live `~/.claude` folder |

## Rules every piece follows

- **A hook that guards is a security control.** It's tested for what it must allow as much as for
  what it refuses, and it parses its input rather than pattern-matching text.
- **One owner per shared thing.** Shared domain logic lives in one module that the others import.
- **Hooks read their input from stdin and never depend on the current directory** being this
  repository.
- **Nothing here holds a secret.** Paths under `~/Documents/lockbox/` may be named; values never.
