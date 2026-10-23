#!/usr/bin/env python3
"""Advise both agents about guarded Git and GitHub CLI actions.

--agent claude is a configuration hint, not proof of caller identity. An absent or
unrecognized value uses the strict policy. Repository rules remain authoritative.
"""

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor"))

DIRECT_PUSH_REPOS = {"claude-config", "codex-config", "second-brain"}
PROTECTED_BRANCHES = {"main", "master"}
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
WORD = re.compile(r"(?<![A-Za-z0-9_])(?:git|gh)(?![A-Za-z0-9_])")
GH_READS = {
    ("run", "list"),
    ("run", "view"),
    ("run", "watch"),
    ("pr", "view"),
    ("pr", "list"),
    ("pr", "diff"),
    ("pr", "checks"),
    ("pr", "status"),
    ("issue", "view"),
    ("issue", "list"),
    ("repo", "view"),
}
GH_REASON = (
    "Allowed gh commands: run list/view/watch; pr view/list/diff/checks/status; "
    "issue view/list; repo view; api GET."
)
PUSH_REASON = (
    "Name the branch: git push [-u] origin <branch> or <source>:<destination>."
)
DEADLINE = None
MAX_COMMAND_BYTES = 64 * 1024


def check_budget():
    if DEADLINE is not None and time.monotonic() >= DEADLINE:
        raise TimeoutError("Command was too complex to judge in time.")


def deny(reason):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def run_git(directory, *args):
    check_budget()
    key = (directory, args)
    if key in GIT_CACHE:
        return GIT_CACHE[key]
    if len(GIT_CACHE) >= MAX_GIT_LOOKUPS:
        raise TimeoutError("Command was too complex to judge in time.")
    remaining = DEADLINE - time.monotonic() if DEADLINE is not None else 2
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True,
            text=True,
            timeout=min(2, remaining),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Command was too complex to judge in time.") from exc
    value = result.stdout.strip() if result.returncode == 0 else ""
    GIT_CACHE[key] = value
    return value


GIT_CACHE = {}
MAX_GIT_LOOKUPS = 512


def directory_for(args, cwd):
    directory = cwd
    git_dir = None
    work_tree = None
    unknown = None
    index = 0
    while index < len(args) and args[index].startswith("-"):
        flag = args[index]
        if flag in (
            "-C",
            "-c",
            "--git-dir",
            "--work-tree",
            "--namespace",
            "--config-env",
        ):
            if index + 1 >= len(args):
                raise ValueError("missing git global option value")
            if flag == "-C":
                path = os.path.expanduser(args[index + 1])
                directory = os.path.abspath(os.path.join(directory, path))
            elif flag == "--git-dir":
                git_dir = args[index + 1]
            elif flag == "--work-tree":
                work_tree = args[index + 1]
            index += 2
        elif flag.startswith("-C") and len(flag) > 2:
            directory = os.path.abspath(
                os.path.join(directory, os.path.expanduser(flag[2:]))
            )
            index += 1
        elif flag.startswith("--git-dir="):
            git_dir = flag.partition("=")[2]
            index += 1
        elif flag.startswith("--work-tree="):
            work_tree = flag.partition("=")[2]
            index += 1
        elif flag in (
            "-p",
            "--paginate",
            "-P",
            "--no-pager",
            "--bare",
            "--no-replace-objects",
            "--no-lazy-fetch",
            "--no-optional-locks",
            "--no-advice",
            "--html-path",
            "--man-path",
            "--info-path",
            "--exec-path",
            "-h",
            "--help",
            "-v",
            "--version",
        ):
            index += 1
        elif flag.startswith(("-c", "--namespace=", "--config-env=", "--exec-path=")):
            index += 1
        else:
            unknown = flag
            index += 1
    lookup = []
    if git_dir is not None:
        lookup.append("--git-dir=" + git_dir)
    if work_tree is not None:
        lookup.append("--work-tree=" + work_tree)
    return directory, args[index:], lookup, unknown


def repository_name(directory, lookup):
    url = run_git(directory, *lookup, "remote", "get-url", "origin")
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") if url else ""


def push_problem(args, directory, lookup, agent):
    if any(
        a in ("--force", "-f", "--force-with-lease", "--force-if-includes")
        or a.startswith(("--force=", "--force-with-lease=", "--force-if-includes="))
        or re.fullmatch(r"-[A-Za-z]*f[A-Za-z]*", a)
        for a in args
    ) or any(a.startswith("+") or ":+" in a for a in args):
        return "Force pushes are refused."
    if any(a in ("--all", "--mirror") for a in args) or (
        agent != "claude" and "--tags" in args
    ):
        return PUSH_REASON
    if agent != "claude":
        values = list(args)
        if values and values[0] in ("-u", "--set-upstream"):
            values.pop(0)
        if len(values) != 2 or values[0] != "origin":
            return PUSH_REASON
        refspec = values[1]
        if refspec.count(":") > 1:
            return PUSH_REASON
        if ":" in refspec and not refspec.split(":", 1)[0]:
            return PUSH_REASON
        destination = refspec.rsplit(":", 1)[-1]
        if (
            not BRANCH.fullmatch(destination)
            or destination.startswith("refs/")
            or destination in PROTECTED_BRANCHES
            or destination == "HEAD"
        ):
            return PUSH_REASON
        return None
    positional = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"):
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        positional.append(arg)
        index += 1
    refspecs = positional[1:] if positional else []
    if "--tags" in args and not refspecs:
        return None
    targets = {ref.rsplit(":", 1)[-1].removeprefix("refs/heads/") for ref in refspecs}
    branch = run_git(directory, *lookup, "branch", "--show-current")
    if not refspecs:
        targets = {branch}
    else:
        targets = {branch if target in ("HEAD", "@") else target for target in targets}
    if targets & PROTECTED_BRANCHES or "" in targets:
        if repository_name(directory, lookup) not in DIRECT_PUSH_REPOS:
            return "Pushing to main or an unknown branch is refused in this repository."
    return None


def git_problem(args, cwd, agent):
    directory, args, lookup, unknown = directory_for(args, cwd)
    if not args:
        return None
    action = args[0]
    if unknown and action in ("push", "merge"):
        return "Unknown git global option for " + action + ": " + unknown
    if action == "merge":
        branch = run_git(directory, *lookup, "branch", "--show-current")
        if branch in PROTECTED_BRANCHES or not branch:
            return "git merge is refused on main, master, or an unknown branch."
    elif action == "push":
        return push_problem(args[1:], directory, lookup, agent)
    return None


def gh_problem(args, agent):
    if len(args) >= 2 and args[:2] == ["pr", "merge"]:
        return "gh pr merge is refused."
    if agent == "claude":
        return None
    if not args:
        return GH_REASON
    if args[0] == "api":
        method = None
        fields = False
        body = False
        for i, arg in enumerate(args[1:], 1):
            if arg in ("-X", "--method"):
                method = args[i + 1] if i + 1 < len(args) else ""
            elif arg.startswith("--method="):
                method = arg.partition("=")[2]
            elif arg.startswith("-X") and len(arg) > 2:
                method = arg[2:]
            elif arg in ("-f", "-F", "--field", "--raw-field") or arg.startswith(
                ("--field=", "--raw-field=", "-f", "-F")
            ):
                fields = True
            elif arg in ("--input",) or arg.startswith("--input="):
                body = True
        return (
            None
            if method == "GET"
            and not body
            or method is None
            and not fields
            and not body
            else GH_REASON
        )
    return None if tuple(args[:2]) in GH_READS else GH_REASON


def unwrap(args):
    args = list(args)
    while args:
        name = os.path.basename(args[0])
        if name == "distrobox" and len(args) >= 2 and args[1] == "enter":
            index = 2
            while index < len(args) and args[index] != "--":
                index += (
                    2
                    if args[index] in ("-n", "--name", "-a", "--additional-flags")
                    else 1
                )
            args = args[index + 1 :] if index < len(args) else []
        elif name == "env":
            index = 1
            while index < len(args):
                arg = args[index]
                if arg == "--":
                    index += 1
                    break
                if arg in ("-u", "--unset", "-C", "--chdir", "-a", "--argv0"):
                    index += 2
                elif arg in ("-i", "--ignore-environment", "-") or arg.startswith(
                    ("--unset=", "--chdir=", "--argv0=")
                ):
                    index += 1
                elif "=" in arg and not arg.startswith("-"):
                    index += 1
                else:
                    break
            args = args[index:]
        elif name == "sudo":
            index = 1
            while index < len(args) and args[index].startswith("-"):
                if args[index] == "--":
                    index += 1
                    break
                index += 2 if args[index] in ("-u", "-g", "-h", "-p", "-D") else 1
            args = args[index:]
        elif name == "timeout":
            index = 1
            while index < len(args):
                if args[index] in ("-s", "--signal", "-k", "--kill-after"):
                    index += 2
                elif args[index] == "--foreground" or args[index].startswith(
                    ("--signal=", "--kill-after=")
                ):
                    index += 1
                else:
                    break
            args = args[index + 1 :] if index < len(args) else []
        elif name == "command":
            index = 1
            while index < len(args) and args[index] in ("-p", "-v", "-V"):
                index += 1
            if index < len(args) and args[index] == "--":
                index += 1
            args = args[index:]
        elif name == "flatpak-spawn":
            index = 1
            while index < len(args) and args[index] == "--host":
                index += 1
            args = args[index:]
        elif name == "xargs":
            index = 1
            while index < len(args) and args[index].startswith("-"):
                index += (
                    2
                    if args[index] in ("-n", "-P", "-I", "-L", "-s", "-d", "-a")
                    else 1
                )
            args = args[index:]
        elif name in ("nohup", "exec"):
            args = args[1:]
        else:
            break
    return args


def command(node, cwd, agent, source, pipeline_input=()):
    words = [part for part in node.parts if part.kind == "word"]
    args = unwrap([bashlex_compat.word_value(part, source) for part in words])
    if not args:
        return cwd, None
    name = os.path.basename(args[0])
    if name == "cd" and len(args) >= 2:
        return os.path.abspath(os.path.join(cwd, os.path.expanduser(args[1]))), None
    if name in ("bash", "sh"):
        for i, arg in enumerate(args[1:], 1):
            if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", arg) and i + 1 < len(args):
                return cwd, script_problem(args[i + 1], cwd, agent)
        for body in pipeline_input:
            reason = script_problem(body, cwd, agent)
            if reason:
                return cwd, reason
        for part in node.parts:
            if part.kind == "redirect" and getattr(part, "heredoc", None):
                body = part.heredoc.value.rsplit("\n", 1)[0] + "\n"
                return cwd, script_problem(body, cwd, agent)
            if part.kind == "redirect" and part.type == "<<<":
                return cwd, script_problem(
                    bashlex_compat.word_value(part.output, source), cwd, agent
                )
    if name == "git":
        return cwd, git_problem(args[1:], cwd, agent)
    if name == "gh":
        return cwd, gh_problem(args[1:], agent)
    return cwd, None


def child_nodes(node):
    """Yield every AST child, regardless of the parent's kind or field name."""
    seen = set()
    for value in vars(node).values():
        values = value if isinstance(value, (list, tuple)) else (value,)
        for child in values:
            if isinstance(child, bashlex.ast.node) and id(child) not in seen:
                seen.add(id(child))
                yield child


def walk(node, cwd, agent, source, pipeline_input=()):
    check_budget()
    outer_cwd = cwd
    if node.kind == "command":
        cwd, reason = command(node, cwd, agent, source, pipeline_input)
        if reason:
            return cwd, reason
    pending_heredocs = []
    for child in child_nodes(node):
        # A pipeline carries here-document input from earlier commands to a
        # later shell command. Every child is still traversed by this loop.
        input_bodies = pending_heredocs if node.kind == "pipeline" else ()
        child_cwd, reason = walk(child, cwd, agent, source, input_bodies)
        if reason:
            return cwd, reason
        if (
            child.kind not in ("commandsubstitution", "processsubstitution")
            and node.kind != "pipeline"
        ):
            cwd = child_cwd
        if node.kind == "pipeline" and child.kind == "command":
            for part in child.parts:
                if part.kind == "redirect" and getattr(part, "heredoc", None):
                    pending_heredocs.append(
                        part.heredoc.value.rsplit("\n", 1)[0] + "\n"
                    )
    # Parenthesized groups run in a subshell; pipeline elements also have
    # separate working directories. A later sibling sees its parent's cwd.
    if node.kind == "pipeline" or (
        node.kind == "compound"
        and any(
            child.kind == "reservedword" and child.word == "("
            for child in child_nodes(node)
        )
    ):
        return outer_cwd, None
    return cwd, None


def script_problem(script, cwd, agent):
    try:
        trees = bashlex.parse(script)
    except Exception as exc:
        normalized = re.sub(r"['\"\\`]", "", script)
        return (
            "Cannot parse a command mentioning git or gh: " + str(exc)
            if WORD.search(normalized)
            else None
        )
    for tree in trees:
        cwd, reason = walk(tree, cwd, agent, script)
        if reason:
            return reason
    return None


def main():
    try:
        global bashlex, bashlex_compat, DEADLINE
        import bashlex
        import bashlex_compat

        bashlex_compat.install()
        DEADLINE = time.monotonic() + 5

        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        tool_name = event.get("tool_name")
        tool_input = event.get("tool_input")
        cwd = event.get("cwd")
        if (
            not isinstance(tool_name, str)
            or not tool_name
            or not isinstance(tool_input, dict)
            or not isinstance(cwd, str)
            or not cwd
        ):
            raise ValueError("event lacks tool_name, tool_input, or cwd")
        if tool_name != "Bash":
            if tool_name == "apply_patch" and not isinstance(
                tool_input.get("command"), str
            ):
                raise ValueError("apply_patch event lacks a command")
            return 0
        cmd = tool_input.get("command")
        if isinstance(cmd, list) and cmd and all(isinstance(x, str) for x in cmd):
            cmd = shlex.join(cmd)
        if not isinstance(cmd, str) or not cmd.strip():
            raise ValueError("event lacks a command")
        if len(cmd.encode("utf-8")) > MAX_COMMAND_BYTES:
            deny("Command is too large to judge.")
            return 0
        agent = "claude" if sys.argv[1:] == ["--agent", "claude"] else "strict"
        reason = script_problem(cmd, cwd, agent)
        if reason:
            deny(reason)
    except Exception as exc:
        deny("Guard error: " + type(exc).__name__ + ": " + str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
