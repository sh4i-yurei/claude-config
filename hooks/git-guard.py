#!/usr/bin/env python3
"""PreToolUse hook: refuses git and gh commands that skip the pull request workflow.

Agents never merge, never force push, and never push to main on a repository that protects it
(Development workflow decisions 14 and 31). The same script serves Claude Code and Codex, which
send the same PreToolUse event and accept the same deny decision.

Commands are matched as text, so a command wrapped in `distrobox enter dev -- bash -lc '...'` or
chained after `cd` is still caught. Mark can still run any of these himself; hooks only see the
agents' tool calls.
"""

import json
import os
import re
import shlex
import subprocess
import sys

# Repositories that take direct pushes to main by design. Every other repository is treated as
# protected, so a new repository is guarded before anyone remembers to list it.
DIRECT_PUSH_REPOS = {"claude-config", "codex-config", "second-brain"}
PROTECTED_BRANCHES = {"main", "master"}

OVERRIDE = (
    "If this is deliberate, Mark runs it himself, and the issue or pull request records why "
    "with the workflow-exception label."
)

# Only a word in command position counts: the start of the text, after a separator, at the start
# of a script passed to a shell with -c (as in `bash -lc '...'`), or after a prefix like `--` or
# `sudo`. Without this, a commit message saying "refuses git merge", or a grep for it, would
# itself be refused.
START = r"(?:^|[;&|(`\n{]|-\w*c\s+['\"]|\b(?:sudo|exec|then|do|else|time|env|xargs|nohup)\b|\s--)\s*"
# git, then any global options such as -C <dir> or -c key=value, then the subcommand.
GIT = START + r"git\b(?P<opts>(?:\s+(?:-C\s+\S+|-c\s+\S+|--[\w-]+(?:=\S+)?))*)\s+"
MERGE = re.compile(GIT + r"merge(?![\w-])")
PUSH = re.compile(GIT + r"push(?![\w-])(?P<args>[^;&|\n'\"]*)")
GH_PR_MERGE = re.compile(START + r"gh\b[^;&|\n'\"]*?\bpr\s+merge\b")
CD = re.compile(r"\bcd\s+([^\s;&|'\"]+)")


def command_text(tool_input):
    """The shell command as one string, whichever tool sent it."""
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if isinstance(command, list):
        # Quote it the way a shell would, so ["bash", "-lc", "git merge x"] keeps its script quoted.
        command = shlex.join(str(part) for part in command)
    return command if isinstance(command, str) else ""


def repo_dir(command, match, cwd):
    """The directory a git command runs in: its -C option, else the last cd before it."""
    c_option = re.search(r"-C\s+(\S+)", match.group("opts") or "")
    if c_option:
        return os.path.expanduser(c_option.group(1))
    cds = CD.findall(command[: match.start()])
    if cds:
        return os.path.join(cwd, os.path.expanduser(cds[-1]))
    return cwd


def git(directory, *args):
    try:
        out = subprocess.run(
            ["git", "-C", directory, *args], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def repo_name(directory):
    url = git(directory, "remote", "get-url", "origin")
    return re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1]) if url else ""


def push_problem(command, match, cwd):
    """Why this git push is refused, or None if it may run."""
    args = match.group("args").split()
    if any(
        a in ("--force", "-f", "--force-with-lease", "--force-if-includes")
        or a.startswith("--force")
        or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", a)
        for a in args
    ) or any(a.startswith("+") for a in args):
        return "Force pushes are refused. Push a new commit instead, or rebase on a fresh branch."

    directory = repo_dir(command, match, cwd)
    name = repo_name(directory)
    if name in DIRECT_PUSH_REPOS:
        return None

    positional = [a for a in args if not a.startswith("-")]
    refspecs = positional[1:]
    if "--all" in args or "--mirror" in args:
        targets = PROTECTED_BRANCHES
    elif refspecs:
        targets = {r.split(":")[-1].removeprefix("refs/heads/") for r in refspecs}
    else:
        targets = {git(directory, "branch", "--show-current")}

    if targets & PROTECTED_BRANCHES:
        where = name or "a repository this hook couldn't identify"
        return (
            f"Pushing to main in {where} is refused. Changes reach main through a pull request "
            f"with passing checks. Push a branch and open a pull request instead."
        )
    return None


def problem(command, cwd):
    if MERGE.search(command):
        return "git merge is refused. Changes reach main only through a pull request that Mark merges."
    if GH_PR_MERGE.search(command):
        return "gh pr merge is refused. Agents open and update pull requests; only Mark merges them."
    for match in PUSH.finditer(command):
        reason = push_problem(command, match, cwd)
        if reason:
            return reason
    return None


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    command = command_text(event.get("tool_input"))
    if "git" not in command and "gh" not in command:
        return 0
    reason = problem(command, event.get("cwd") or os.getcwd())
    if reason:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"{reason} {OVERRIDE}",
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
