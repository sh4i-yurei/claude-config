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

## Secrets for agents

Agents use `vault-run` inside `dev` to pass a requested secret to one command. After it is linked
as `~/.local/bin/vault-run`, a named hidden field goes into that command's environment:

```bash
vault-run --env GH_TOKEN -- gh run list
```

An item's login password goes to the command's standard input, followed by a newline:

```bash
vault-run --stdin "keepbreath0 sudo (hub)" -- ssh hub "sudo -S -p '' true"
```

The runner reads the existing vault session itself. It does not pass the session key to the
command or print secret values.

## Agent guard registration

`hooks/git-guard.py` runs under the host's `/usr/bin/python3`. It loads the vendored
`bashlex` 0.18 parser from `vendor/bashlex/`; its license is beside the package. The
vendor files match the upstream release. `hooks/bashlex_compat.py` contains both quote
corrections: heredoc delimiters lose their quotes before matching, and nested script
words have their source spans decoded. Ruff excludes explicitly named vendor files.
The guard reads commands only from Bash PreToolUse events. Codex also sends patch text
in `tool_input.command` for `apply_patch`, and that text is not a shell command.
For every agent, the guard refuses `gh issue create`, `gh api` POST requests to a
repository's issue list, and GraphQL `createIssue` mutations. Its refusal directs issue
creation through `tools/workflow/issue.py open` in [Opening an issue from a file](#opening-an-issue-from-a-file).
Issue reads, issue comments, edits and closes, and writes to other API endpoints remain
available under each agent's other guard rules.
The guard reads built-in `gh` commands and aliases from
`hooks/gh-command-tree-2.97.0.json`. It resolves each command word to its canonical
name before checking the strict read list, pull request merges, and issue creation.
The tree also records flags accepted before a subcommand. An unknown first command
or a flag needed to judge a command is refused as unjudgeable. Local aliases from
`gh alias` are not in the versioned tree.

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
`template: handoff-codex-build` in their frontmatter. It checks a Write to a path that
doesn't exist yet or can't be read in full, and a Write or Edit to an existing handoff
only when the Request block it produces differs from the one in the file now.
When the template has a section named exactly `FACTS`, it refuses a FACTS bullet that has
no `Evidence:` followed by text, and a FACTS section with no bullets.
It reads required section names
from `Second_Brain/_Templates/handoff-codex-build.md` whenever it checks a handoff.
Tests load the hook in-process and patch its `HANDOFFS` and `TEMPLATE` to point it at
repository fixtures. If the template cannot be read, the hook allows the write
and sends a warning to Claude through `additionalContext`.

## Synchronizing labels

Run this command in the `dev` shell from the `claude-config` repository root. `vault-run` gives
it GitHub's token for that one run, and it prints every planned create, update and delete without
changing GitHub:

```bash
vault-run --env GH_TOKEN -- /usr/bin/python3 tools/workflow/sync_labels.py --dry-run
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
vault-run --env GH_TOKEN -- /usr/bin/python3 tools/workflow/issue.py open issue.toml --dry-run
vault-run --env GH_TOKEN -- /usr/bin/python3 tools/workflow/issue.py open issue.toml
```

The first invocation validates the file, reads GitHub's current issue form, labels, milestone,
related issues and board, and prints the body and planned GitHub calls. It changes nothing. Review
that output before running the second invocation. The command refuses a repository until it has a
`[boards]` entry in `workflow.toml`; it prints the line to add and the available products. A repository with its own Markdown
issue templates is refused until those templates are replaced by forms. Exit 2 means the input
was refused or a GitHub step failed. If a step fails after issue creation, the output includes the
new issue URL and lists completed and unfinished steps.

The input is TOML. `repo`, `kind` and `title` are required. `kind` is the name of a `.yml` or
`.yaml` issue form without its extension. `body` is a TOML table keyed by that form's field ids;
required fields must have values. The optional `scope` is a `scope:` label from `labels.toml`,
and is required when that repository defines scope labels. `milestone` is a milestone title or
number. `parent` is an issue number, and `blocked_by` is a list of issue numbers. Each related
issue must exist in the same repository. The optional `labels` list accepts global label names
from `labels.toml`, excluding `type:` and `scope:` labels. These are the only accepted keys. For example:

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

## Filing a build's review leftovers from its final round

Run these commands in the `dev` shell from the repository root, after a review handoff has one
review-result `json` block in its Response. The first command shows the planned issue without
writing to GitHub. The second opens it through the same checks and board steps as `open`.

```bash
vault-run --env GH_TOKEN -- /usr/bin/python3 tools/workflow/issue.py debt review-handoff.md --dry-run
vault-run --env GH_TOKEN -- /usr/bin/python3 tools/workflow/issue.py debt review-handoff.md
```

Run `debt` on the final review round. The command takes findings marked `non_blocking` whose
`breaks_test_case` is `none` from every round of that build. It uses the Chore form, the reviewed
issue's scope label and the `tech-debt` label, then links that issue as its parent and puts the new
issue in Backlog. It refuses a build when any of its review rounds is already named in one of the
parent's sub-issues, whether that sub-issue is open or closed. A build with no qualifying findings
opens nothing. It also refuses a round 0 file or two files with the same round number in one
build, including names such as `-review-02.md` and `-review-2.md`. Exit 2 means the handoff was
refused or a GitHub step failed.

## Checking whether an issue is Ready

Run this command in the `dev` shell from the repository root. It checks the issue against its
current form and board fields. `--check` reports the same conditions without changing the board.

```bash
vault-run --env GH_TOKEN -- /usr/bin/python3 tools/workflow/issue.py ready sh4i-yurei/claude-config#23 --check
vault-run --env GH_TOKEN -- /usr/bin/python3 tools/workflow/issue.py ready sh4i-yurei/claude-config#23
```

The command requires one `type:` label, a defined `scope:` label where the repository has scope
labels, every required form section, Priority, Size and Estimate, a milestone or parent, and no
open issue blocking it. An Architecture-sized issue also needs a body line beginning `Design: `.
It prints each condition as met or unmet. Exit 0 means all conditions are met and, without
`--check`, the board Status is Ready. Exit 1 means an issue needs more work. Exit 2 means a
configuration or GitHub error, including a missing board mapping or board item.

## What is not here

- The vault's integrity check is `.github/scripts/check.py` in the vault. The
  `vault-health` skill calls it there.
- `skills/synced/` is a cache that Claude Code writes when skills sync, and it is ignored.

These files lived in the vault under `.claude/` until 2026-09-25. Their history before that
date comes from the vault's history.
