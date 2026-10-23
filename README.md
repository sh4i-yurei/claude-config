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

Claude Code's `~/.claude/settings.json` registers it for Bash PreToolUse. Claude's
registration currently has no agent flag. After W1 lands, Claude adds `--agent claude` to
that command. Codex's `~/Documents/codex-config/hooks.json` registers the same hook for
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

## What is not here

- The vault's integrity check is `.github/scripts/check.py` in the vault. The
  `vault-health` skill calls it there.
- `skills/synced/` is a cache that Claude Code writes when skills sync, and it is ignored.

These files lived in the vault under `.claude/` until 2026-09-25. Their history before that
date comes from the vault's history.
