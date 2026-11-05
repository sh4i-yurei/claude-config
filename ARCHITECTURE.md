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
| `.github/workflows/ci.yml` | Call the pinned shared Python and shell checks on every push | Reusable workflows at full commit SHAs; installs the guard's pinned gh, PyYAML and mutmut | A failing shared check fails CI | Hold a copy of the shared checks' logic |
| `hooks/git-guard.py`, `hooks/bashlex_compat.py`, `hooks/gh-command-tree-2.97.0.json` | Warn Claude and Codex before guarded git and gh actions; refuse direct vault reads and unwrap vault-run; parse gh flags and resolve built-in command aliases through a versioned canonical command tree; correct parser quoting in one compatibility module imported once per process | PreToolUse event on stdin; optional `--agent claude` hint; deny decision on stdout; vendored bashlex 0.18; 64 KB command cap and five-second judgement budget | Malformed events, oversized commands, and internal errors return a deny decision; hook startup failures and timeouts depend on the agent runtime; when bashlex cannot parse a script, one text search for the guard's protected program names and bw-session refuses it | Judge parsed commands by text search; treat an agent flag as identity proof; replace GitHub branch rules |
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
| `tools/vault-env` | Print the vault's API token exports for direct shell evaluation | `eval "$(vault-env)"` inside `dev`; arguments or terminal stdout exit 2 with usage | A missing container or inaccessible vault exits 1 with an error on stderr | Print token exports in response to arguments or to a terminal |
| `tools/vault_run.py` | Be the only way agents get a secret; give it only to the command that needs it | `vault-run [--env NAME]... [--stdin ITEM] -- COMMAND [ARG]...` inside `dev`, linked as `~/.local/bin/vault-run` | Refuses missing fields, passwords, vault access, and invalid commands with named errors | Print a secret value or pass the vault session key to the child; be wired to a hook |
| `tools/workflow/labels.toml` | Define global labels and each repository's scope labels | TOML tables keyed by label name and repository | Invalid definitions stop the sync before GitHub calls | Include GitHub's default labels or a repository list for global labels |
| `tools/workflow/workflow.toml` | Define owners to query, workflow exceptions, products and repository board mappings | `owners` and `exceptions` TOML arrays; `[products]` maps product names to a project owner and number; `[boards]` maps repositories to product names | An unmapped repository stops issue opening before a GitHub write | Enumerate active repositories for label sync or hold label definitions |
| `tools/workflow/config.py` | Read and validate both workflow TOML files for tools | `load()` returns owners, exceptions and label maps; `load_board_config()` returns board mappings and ordered product names; `load_boards()` returns board mappings; all raise `ConfigError` naming a bad file | Refuses missing or malformed configuration | Make GitHub calls or mutate labels |
| `tools/workflow/sync_labels.py` | Query GitHub repositories and reconcile their labels | `python3 tools/workflow/sync_labels.py [--dry-run]`; exit 0 for success, 1 for labels still used by open issues or pull requests, 2 for an error | Stops on a failed GitHub call; names kept labels and continues | Read TOML itself, list repositories in code, delete a label used by an open issue or pull request, or write in dry-run mode |
| `tools/workflow/issue.py` | Validate an issue file or every review round's leftover findings from the final round against the current GitHub form, open it, link related issues and put it and stray open issues on the mapped board; check the Definition of Ready and set Ready only when it passes | `python3 tools/workflow/issue.py open FILE [--dry-run]`; `python3 tools/workflow/issue.py debt REVIEW_HANDOFF [--dry-run]`; `python3 tools/workflow/issue.py ready OWNER/REPO#NUMBER [--check [--stacked-on OWNER/REPO#NUMBER]... [--proposed-with OWNER/REPO#NUMBER]...]`; open and debt exit 0 for success or 2 for refusal or failure; ready exits 0 when Ready, 1 for unmet conditions, or 2 for configuration or GitHub error | Open and debt name validation problems before writes and, after creation, print the issue URL and completed and remaining steps; ready names every unmet condition before a Status write; a named open blocker passes with `--stacked-on` only with a linked agent/ branch that heads an open pull request, or with `--proposed-with` only when its card on the same board is in Proposed | Read workflow TOML itself; accept Markdown issue templates; set triage fields during open; write in dry-run or check mode |
| `vale/` | Vale's configuration and styles | Read by Vale | — | — |
| `tests/` | Tests for the hooks, tools and research skill; shell scripts' Bats tests live in `tests/shell/` and run under kcov in CI | `python3 -m pytest` and `bats tests/shell` | — | Depend on the live `~/.claude` folder |

## Rules every piece follows

- **A hook that guards is a security control.** It's tested for what it must allow as much as for
  what it refuses, and it parses its input rather than pattern-matching text.
- **One owner per shared thing.** Shared domain logic lives in one module that the others import.
- **Hooks read their input from stdin and never depend on the current directory** being this
  repository.
- **Nothing here holds a secret.** Paths under `~/Documents/lockbox/` may be named; values never.
