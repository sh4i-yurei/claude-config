# claude-config

The setup Claude Code loads on my machines: the skills, hooks and rules it reads from
`~/.claude`. Notes and research live in the Second Brain vault, a separate repository.

## What is here

- `skills/`: one folder per skill, each with a `SKILL.md` and any scripts it runs. The
  research tools are in `skills/research/scripts/`.
- `hooks/`: the hook scripts. `~/.claude/settings.json` wires them to events by their
  `~/.claude/hooks/...` paths. `herdr-session-name.py` names an interactive session after its
  workspace.
- `rules/`: instructions loaded into every session, such as the writing style.
- `tools/`: standalone scripts that aren't skills. `tools/token-usage/` measures where Claude
  Code's and Codex's tokens go, from their session files.
- `tools/workflow/`: `labels.toml` defines global labels and repository-specific `scope:` labels.
  `workflow.toml` lists GitHub owners, workflow exceptions, each active repository's board and
  the `[upstream]` approval and text rules.
  `config.py` validates both files, and `sync_labels.py` applies the definitions to every active
  repository returned by GitHub for those owners. A newly created repository receives the global
  labels without an entry in either file. `issue.py open` creates a checked issue on our boards;
  `issue.py upstream` files an approved issue outside them and opens a tracking issue. `open` places it
  and stray open issues on that repository's board. `handoff_cost.py` counts the Codex sessions
  that followed one handoff, with their model calls and tokens. `handoff_send.py` delivers a
  handoff or its Response notice to a named live session.
- `telemetry/`: a Podman Quadlet unit and an OpenTelemetry Collector config that keep Claude
  Code's `skill_activated` events, and nothing else, in one local file. See
  [Skill telemetry](#skill-telemetry).
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

## Skill telemetry

Claude Code reports which skills run through OpenTelemetry. A collector in a pinned container
receives those events on `127.0.0.1:4318`. It keeps only `skill_activated` and deletes the
email and account and organisation ids. The result goes to
`~/.local/share/claude-telemetry/skill-activations.jsonl`, rotated at 10 MB. The two files run
from links, like the skills:

```bash
mkdir -p ~/.config/containers/systemd ~/.config/claude-telemetry
ln -s ~/Documents/claude-config/telemetry/claude-telemetry.container ~/.config/containers/systemd/
ln -s ~/Documents/claude-config/telemetry/collector.yaml ~/.config/claude-telemetry/
systemctl --user daemon-reload
systemctl --user start claude-telemetry.service
```

These run on the host, not inside `dev`. The `env` block in `~/.claude/settings.json` turns the
export on:

```json
"CLAUDE_CODE_ENABLE_TELEMETRY": "1",
"OTEL_LOGS_EXPORTER": "otlp",
"OTEL_METRICS_EXPORTER": "none",
"OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://127.0.0.1:4318/v1/logs",
"OTEL_LOG_TOOL_DETAILS": "1"
```

`OTEL_LOG_TOOL_DETAILS` gives skills their real names. It also puts full commands and file paths
on other events, which is why the collector keeps only `skill_activated`. Prompt text, response
text, raw API bodies, the host name and tracing stay off. When the collector isn't running, a
session carries on normally and its events are lost.

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

vault-run, vault-env, git-credential-bw, secret-load and the research gateway all read an item through tools/vault_item.py, which finds the one item whose name is exactly the name asked for. When no item or several items have that name, they say so instead of reading the wrong one. vault-env and git-credential-bw are linked as ~/.local/bin/vault-env and ~/.local/bin/git-credential-bw, from tools/vault_env.py and tools/git_credential_bw.py.

`secret-load` moves one staged value into OpenBao's `secret/` KV store without printing it. Use `secret-load --from FILE --label LABEL --to openbao:PATH[#KEY] --dry-run` to check a labelled line first; omit `--label` to load a whole file. A matching value stays as it is. Use `--replace` to rotate a different value and `--remove-source` to remove the source only after verification and token revocation. Source removal does not scrub old blocks on btrfs. Vaultwarden destinations are reserved for a later item.

## Committing to the vault

Agents commit vault work only with `vault-commit -m MESSAGE -- PATH...` inside `dev`.
It commits only the named paths even when other sessions have staged work.
If the push is refused, the commit stays local for a person to sort out.

```bash
vault-commit -m "Workflow upkeep: a note" -- "10_Projects/16_Tooling/Workflow upkeep.md"
```

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
creation through `tools/workflow/issue.py open` for our repositories or `issue.py upstream`
for one outside our boards, as described in [Opening an issue from a file](#opening-an-issue-from-a-file).
Issue reads, issue comments, edits and closes, and writes to other API endpoints remain
available under each agent's other guard rules.
For every agent, the guard also refuses `git commit` in the shared vault checkout, found at `SECOND_BRAIN` or `~/Documents/Second_Brain`, and names `vault-commit`, because every session shares that checkout's index; worktrees and clones of the vault have their own index and stay allowed.
The guard refuses AI attribution in a commit message it can read.
The guard refuses a new queue task without a project tag and an item tag.
For an `rtk` command, the guard judges every command RTK could run.
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
`command`, `exec`, `nohup`, `xargs`, and `rtk`. It checks commands up to 64 KB and
refuses a command when its five-second judgement budget expires.
For `sudo`, it reads options and variable assignments as sudo 1.9.17p2 does
before checking the command sudo would run.

Any other wrapper, shell, interpreter, or `eval` is outside the guard's view.
This includes a heredoc routed through a compound command into a shell.
GitHub repository rulesets enforce protected branches even when the guard
cannot see the eventual command, as decisions 15 and 17 specify.

### If the guard refuses every command

The guard fails closed: when it can't run or judge a command, it refuses it with a
`Guard error:` reason. A bad change to `hooks/git-guard.py` can therefore refuse every
shell command for every agent. No agent can repair that, because the agents' shell
commands are refused and every Claude session is denied editing `hooks/`, `tools/` and
`rules/` in this checkout and `~/.claude/hooks/`. The person at the machine recovers it
from a terminal outside any agent, in one of two ways.

The first way puts back the last good guard. `~/.claude/hooks` links to this checkout's
`hooks/`, so the restored file takes effect at once:

```bash
git -C ~/Documents/claude-config log --oneline -5 -- hooks/git-guard.py
git -C ~/Documents/claude-config checkout <last-good-commit> -- hooks/git-guard.py
```

The fix then goes through a pull request as usual. Once it merges, running
`git -C ~/Documents/claude-config checkout -- hooks/git-guard.py` and a fast-forward
pull returns the checkout to `main`.

The second way turns the guard off for a short time. Remove the
`git-guard.py --agent claude` entry from the Bash PreToolUse hooks in
`~/.claude/settings.json`, and the `git-guard.py` entry in `~/.codex/hooks.json` if Codex
is affected. Put both back as soon as the guard is fixed, because while they are out
nothing checks the agents' Git, GitHub and secret commands.

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
no `Evidence:` followed by text, and a FACTS section with no bullets. It also finds the note
named by the handoff's `project:` wikilink under `Second_Brain/10_Projects` and requires each
FACTS bullet to match one in that note's `## Facts` section after removing backticks and
collapsing whitespace. Missing, ambiguous, unreadable or factless project notes are refused.
`HANDOFF_PROJECTS_ROOT` can point the hook at another project notes folder.
It reads required section names
from `Second_Brain/_Templates/handoff-codex-build.md` whenever it checks a handoff.
Tests load the hook in-process and patch its `HANDOFFS`, `PROJECTS` and `TEMPLATE` to point it at
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

### Filing an issue upstream

Run these commands in the `dev` shell from the repository root. The first reads the approval row,
GitHub labels and issues, and the tracking repository's chore form and board. It prints both planned
issues without writing either one. The second files the upstream issue, opens its tracking issue
on our board, then notes both links on the approval row.

```bash
vault-run --env GH_TOKEN -- /usr/bin/python3 tools/workflow/issue.py upstream issue.toml --dry-run
vault-run --env GH_TOKEN -- /usr/bin/python3 tools/workflow/issue.py upstream issue.toml
```

The TOML file accepts exactly `repo`, `title`, `body`, `approval`, `tracking`, optional
`tracking_scope` and optional `labels`. The target repository must be outside our owners and
boards. Every label must already exist there. For example:

```toml
repo = "mvschwarz/openrig"
title = "Per-seat list of MCP servers to block, through deniedMcpServers in the seat's settings"
body = "A per-seat list could block selected MCP servers at launch."
approval = "qitem-<id>"
tracking = "sh4i-yurei/workflow-engine"
labels = ["enhancement"]
```

The approval row must come from `main-lead@hq`, be addressed to the filing seat, say
"upstream", and name the target repository. One approval may file one issue. The title and body
are checked against the `[upstream]` text rules before any write. If a later step fails, the
command prints the links it created and the failed step; keep those links when resolving the
failure, rather than filing the same upstream issue again.

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

## Delivering a handoff to a live session

In the `dev` shell from the repository root, run these commands with a handoff file in
`~/Documents/Second_Brain/05_Agents/handoffs/`:

```bash
python3 tools/workflow/handoff_send.py deliver handoff.md
python3 tools/workflow/handoff_send.py reply handoff.md
```

`deliver` waits for the session in `session:` and prompts it to read the Request. It prints
`delivered handoff.md to <session>`. After the Response is written, `reply` waits for the
session in `reply_to:` and tells it the Response is ready. It prints
`told <reply_to> that handoff.md has its Response`. Both commands accept a full path and an
optional `--wait-minutes N` (default 30). A refusal or failed delivery prints one error on
standard error.

## Session naming registration

To name interactive Claude sessions after their herdr workspaces, add this entry to the
`SessionStart` hooks in `~/.claude/settings.json` after `herdr-session-name.py` is on `main`:

```json
{
  "hooks": [
    {"type": "command", "command": "python3 ~/.claude/hooks/herdr-session-name.py", "timeout": 10}
  ]
}
```

The hook prints `This session's herdr name is <name>.` into the session's context when
herdr names it. It prints nothing when the session cannot be named.

## Counting a handoff's Codex cost

Run this command from the repository root with a handoff's file name or path. It reads every
Codex session file under `~/.codex/sessions`, or under the folder `--sessions` names.

```bash
python3 tools/workflow/handoff_cost.py 2026-11-07-claude-to-codex-workflow-upkeep-handoff-facts.md
```

A session counts for the handoff when its first "Follow the Request in" message names a file
with the same name. The command prints one line for each such session and then a total:

```text
rollout-2026-11-07T08-31-50-01a1c1f0-9c3e-7a63-b2d8-1e5f4c7a8d03.jsonl: 2 steps, 92069 input tokens (79616 cached), 1161 output tokens
1 sessions, 2 steps, 92069 input tokens (79616 cached), 1161 output tokens
```

A step is one model call. The tokens are the sums of each call's own usage record, which also
count the call that compacts a long session's context. When no session followed the handoff, the
command says so on standard error and exits 1.

## What is not here

- The vault's integrity check is `.github/scripts/check.py` in the vault. The
  `vault-health` skill calls it there.
- `skills/synced/` is a cache that Claude Code writes when skills sync, and it is ignored.

These files lived in the vault under `.claude/` until 2026-09-25. Their history before that
date comes from the vault's history.
