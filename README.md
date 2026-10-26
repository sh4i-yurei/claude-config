# claude-config

The setup Claude Code loads on my machines: the skills, hooks and rules it reads from
`~/.claude`. Notes and research live in the Second Brain vault, a separate repository.

## What is here

- `skills/`: one folder per skill, each with a `SKILL.md` and any scripts it runs. The
  research tools are in `skills/research/scripts/`.
- `hooks/`: the hook scripts. `~/.claude/settings.json` wires them to events by their
  `~/.claude/hooks/...` paths.
- `rules/`: instructions loaded into every session, such as the writing style.
- `tools/`: standalone scripts that aren't skills. `tools/token-usage/` measures where Claude
  Code's and Codex's tokens go, from their session files.
- `tools/workflow/`: `labels.toml` defines global labels and repository-specific `scope:` labels.
  `workflow.toml` lists GitHub owners, workflow exceptions and each active repository's board.
  `config.py` validates both files, and `sync_labels.py` applies the definitions to every active
  repository returned by GitHub for those owners. A newly created repository receives the global
  labels without an entry in either file. `issue.py open` creates a checked issue and places it
  and stray open issues on that repository's board.
- `vale/`: configuration for Vale, the prose linter. `vale.ini` covers posts and is run by
  the `vale-post-lint.py` hook; `vale-sweep.ini` covers every prose note and is run by the
  vault sweep. `styles/` holds the rules: `keepbreath`, my own, and `ai-tells`, a downloaded
  pack. Both are tracked, so every machine gets the same rules. Vale itself is installed
  separately.

## Setting up a machine

Clone the repository, then point `~/.claude` at it. An existing folder is kept as a dated
backup rather than overwritten.

```bash
git clone https://github.com/sh4i-yurei/claude-config.git ~/Documents/claude-config
for d in skills hooks rules; do
  [ -e ~/.claude/$d ] && mv ~/.claude/$d ~/.claude/$d.bak-$(date +%Y%m%d)
  ln -s ~/Documents/claude-config/$d ~/.claude/$d
done
```

`~/.claude/settings.json` is not in this repository. Because it refers to the hooks through
`~/.claude/hooks`, it needs no change when this repository moves.

## Agent guard registration

`hooks/git-guard.py` runs under the host's `/usr/bin/python3`. It loads the vendored
`bashlex` 0.18 parser from `vendor/bashlex/`; its license is beside the package. The
vendor files match the upstream release. `hooks/bashlex_compat.py` contains both quote
corrections: heredoc delimiters lose their quotes before matching, and nested script
words have their source spans decoded. Ruff excludes explicitly named vendor files.
The guard reads commands only from Bash PreToolUse events. Codex also sends patch text
in `tool_input.command` for `apply_patch`, and that text is not a shell command.

Claude Code's `~/.claude/settings.json` registers it for Bash PreToolUse with
`--agent claude`. Codex's `~/Documents/codex-config/hooks.json` registers the same hook for
PreToolUse with a 10-second timeout and no agent flag, so the strict rules apply. The
flag selects a rule set; GitHub repository rules enforce protected branches.

The guard parses simple commands, lists, pipelines, groups, loops, substitutions,
and redirects. It follows scripts passed to `bash` or `sh` with a short `-c`
option, direct heredocs and here-strings fed to those shells, and the named
options of `distrobox enter`, `flatpak-spawn --host`, `env`, `sudo`, `timeout`,
`command`, `exec`, `nohup`, and `xargs`. It checks commands up to 64 KB and
refuses a command when its five-second judgement budget expires.

Any other wrapper, shell, interpreter, or `eval` is outside the guard's view.
This includes a heredoc routed through a compound command into a shell.
GitHub repository rulesets enforce protected branches even when the guard
cannot see the eventual command, as decisions 15 and 17 specify.

## Handoff check registration

To check build handoffs before Claude writes or edits them, add this entry to the
`PreToolUse` hooks in `~/.claude/settings.json` after `handoff-check.py` is on `main`:

```json
{
  "matcher": "Write|Edit",
  "hooks": [
    {"type": "command", "command": "python3 ~/.claude/hooks/handoff-check.py"}
  ]
}
```

The hook checks only files under `05_Agents/handoffs/` with
`template: handoff-codex-build` in their frontmatter. It reads required section names
from `Second_Brain/_Templates/handoff-codex-build.md` on each invocation.
Tests set `HANDOFF_CHECK_ROOT` and `HANDOFF_BUILD_TEMPLATE` to point the hook at
repository fixtures. If the template cannot be read, the hook allows the write
and sends a warning to Claude through `additionalContext`.

## Synchronizing labels

Run these commands in the `dev` shell from the `claude-config` repository root. The first loads
GitHub authentication into the current shell, and the second prints every planned create, update
and delete without changing GitHub:

```bash
eval "$(vault-env)"
/usr/bin/python3 tools/workflow/sync_labels.py --dry-run
```

After reviewing the plan, omit `--dry-run` to apply it. The command skips archived repositories
and the exceptions in `workflow.toml`. It keeps undefined labels that still appear on open issues
or open pull requests, prints their numbers, continues through the other repositories, and exits 1. A configuration
or GitHub error exits 2. Edit `labels.toml` to change the shared label definitions; repository
entries there apply only to their named repository. GitHub's default labels are absent from the
file, so the sync removes unused defaults.

## Opening an issue from a file

Run these commands in the `dev` shell from the repository root. PyYAML is needed by the same
`/usr/bin/python3` that runs the command. If it is absent in `dev`, install it in that shell with
`/usr/bin/python3 -m pip install --user --break-system-packages PyYAML`.

```bash
eval "$(vault-env)"
/usr/bin/python3 tools/workflow/issue.py open issue.toml --dry-run
/usr/bin/python3 tools/workflow/issue.py open issue.toml
```

The first invocation validates the file, reads GitHub's current issue form, labels, milestone,
related issues and board, and prints the body and planned GitHub calls. It changes nothing. Review
that output before running the second invocation. The command refuses a repository until it has a
`[boards]` entry in `workflow.toml`; it prints the line to add. A repository with its own Markdown
issue templates is refused until those templates are replaced by forms. Exit 2 means the input
was refused or a GitHub step failed. If a step fails after issue creation, the output includes the
new issue URL and lists completed and unfinished steps.

The input is TOML. `repo`, `kind` and `title` are required. `kind` is the name of a `.yml` or
`.yaml` issue form without its extension. `body` is a TOML table keyed by that form's field ids;
required fields must have values. The optional `scope` is a `scope:` label from `labels.toml`,
and is required when that repository defines scope labels. `milestone` is a milestone title or
number. `parent` is an issue number, and `blocked_by` is a list of issue numbers. Each related
issue must exist in the same repository. These are the only accepted keys. For example:

```toml
repo = "sh4i-yurei/claude-config"
kind = "feature"
title = "Describe the feature"
scope = "scope:ci"
milestone = "Workflow · M1: Global GitHub workflow"
parent = 20
blocked_by = [22]

[body]
context = "Project, step and reason."
changes = "What changes."
done = "The condition that finishes the issue."
```

The tool reads this repository's forms when it has any; otherwise it reads the forms from
the issue repository owner's `.github` repository. It renders fields in form order, adds the form's labels and the scope label,
links the parent and blockers, and puts the issue on its configured board with Status Backlog.
Priority, Size, Estimate and Iteration stay empty for triage. It also adds any open issues from
the same repository that are missing from that board, with Status Backlog.

## What is not here

- The vault's integrity check is `.github/scripts/check.py` in the vault. The
  `vault-health` skill calls it there.
- `skills/synced/` is a cache that Claude Code writes when skills sync, and it is ignored.

These files lived in the vault under `.claude/` until 2026-09-25. Their history before that
date comes from the vault's history.
