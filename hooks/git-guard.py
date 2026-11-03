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
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor"))

DIRECT_PUSH_REPOS = {"second-brain"}
PROTECTED_BRANCHES = {"main", "master"}
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
GUARDED_PROGRAMS = ("git", "gh", "bw", "vault-env")
GIT, GH, BW, VAULT_ENV = GUARDED_PROGRAMS
SESSION_FILE = "bw-session"
FALLBACK_WORD = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    + "|".join(re.escape(name) for name in (*GUARDED_PROGRAMS, SESSION_FILE))
    + r")(?![A-Za-z0-9_])"
)
PFLAG_BOOLEAN_VALUES = frozenset(
    ("1", "t", "T", "TRUE", "true", "True", "0", "f", "F", "FALSE", "false", "False")
)
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
GH_FLAG_TABLES = {
    "auth-status": {
        "-a": False,
        "--active": False,
        "-h": True,
        "--hostname": True,
        "--jq": True,
        "--json": True,
        "-t": False,
        "--show-token": False,
        "--template": True,
    },
    "api": {
        "--allow-escape-sequences": False,
        "--cache": True,
        "-F": True,
        "--field": True,
        "-H": True,
        "--header": True,
        "--hostname": True,
        "-i": False,
        "--include": False,
        "--input": True,
        "-q": True,
        "--jq": True,
        "-X": True,
        "--method": True,
        "--paginate": False,
        "-p": True,
        "--preview": True,
        "-f": True,
        "--raw-field": True,
        "--silent": False,
        "--slurp": False,
        "-t": True,
        "--template": True,
        "--verbose": False,
        "--help": False,
    },
    "issue-create": {
        "-a": True,
        "--assignee": True,
        "--blocked-by": True,
        "--blocking": True,
        "-b": True,
        "--body": True,
        "-F": True,
        "--body-file": True,
        "-e": False,
        "--editor": False,
        "-l": True,
        "--label": True,
        "-m": True,
        "--milestone": True,
        "--parent": True,
        "-p": True,
        "--project": True,
        "--recover": True,
        "-T": True,
        "--template": True,
        "-t": True,
        "--title": True,
        "--type": True,
        "-w": False,
        "--web": False,
        "--help": False,
        "-R": True,
        "--repo": True,
    },
    "pr-merge": {
        "--admin": False,
        "-A": True,
        "--author-email": True,
        "--auto": False,
        "-b": True,
        "--body": True,
        "-F": True,
        "--body-file": True,
        "-d": False,
        "--delete-branch": False,
        "--disable-auto": False,
        "--match-head-commit": True,
        "-m": False,
        "--merge": False,
        "-r": False,
        "--rebase": False,
        "-s": False,
        "--squash": False,
        "-t": True,
        "--subject": True,
        "--help": False,
        "-R": True,
        "--repo": True,
    },
}
PUSH_REASON = (
    "Name the branch: git push [-u] origin <branch> or <source>:<destination>."
)
ISSUE_REASON = (
    "Use tools/workflow/issue.py open; see README.md, Opening an issue from a file."
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
    if unknown and action in ("push", "merge", "pull"):
        return "Unknown git global option for " + action + ": " + unknown
    if action in ("merge", "pull"):
        branch = run_git(directory, *lookup, "branch", "--show-current")
        if branch in PROTECTED_BRANCHES or not branch:
            refusal = (
                "git merge and git pull are refused on main, master, or an unknown "
                "branch, except a fast-forward to the branch's own upstream with --ff-only."
            )
            upstream = run_git(
                directory,
                *lookup,
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            )
            if upstream != "origin/" + branch:
                return refusal
            allowed_options = {
                "--ff-only",
                "-q",
                "--quiet",
                "-v",
                "--verbose",
                "--stat",
                "-n",
                "--no-stat",
            }
            command_args = args[1:]
            options = [arg for arg in command_args if arg.startswith("-")]
            targets = [arg for arg in command_args if not arg.startswith("-")]
            if "--ff-only" not in options or any(
                option not in allowed_options for option in options
            ):
                return refusal
            if action == "merge":
                allowed_targets = ([], [upstream], ["@{u}"], ["@{upstream}"])
            else:
                allowed_targets = ([], ["origin", branch])
            if targets not in allowed_targets:
                return refusal
    elif action == "push":
        return push_problem(args[1:], directory, lookup, agent)
    return None


def parse_gh(args):
    """Parse command path and flags with gh's interspersed flag grammar."""
    tree = json.loads(
        (Path(__file__).with_name("gh-command-tree-2.97.0.json")).read_text()
    )
    path, positionals, flags = [], [], {}
    node = tree
    index = 0
    ended = False
    path_open = True
    while index < len(args):
        arg = args[index]
        if arg == "--" and not ended:
            ended = True
            index += 1
            continue
        key = "-".join(path)
        table = GH_FLAG_TABLES.get(key)
        if table is None and (node["children"] or not path):
            table = node["flags"]
        if not path_open and node["children"]:
            index += 1
            continue
        if table is None and path:
            index += 1
            continue
        if not ended and arg.startswith("-") and arg != "-":
            if arg.startswith("--"):
                name, separator, attached = arg.partition("=")
                if name not in table:
                    return path, positionals, flags, name
                takes_value = table[name]
                if (
                    not takes_value
                    and separator
                    and attached not in PFLAG_BOOLEAN_VALUES
                ):
                    return path, positionals, flags, name
                if takes_value:
                    if not separator:
                        index += 1
                        if index == len(args):
                            return path, positionals, flags, name
                        attached = args[index]
                    flags.setdefault(name, []).append(attached)
                    flags.setdefault("_ordered", []).append((name, attached))
                else:
                    flags.setdefault(name, []).append(attached if separator else None)
                    flags.setdefault("_ordered", []).append(
                        (name, attached if separator else None)
                    )
            else:
                letters = arg[1:]
                offset = 0
                while offset < len(letters):
                    name = "-" + letters[offset]
                    if name not in table:
                        return path, positionals, flags, name
                    if table[name]:
                        value = letters[offset + 1 :].removeprefix("=")
                        if not value:
                            index += 1
                            if index == len(args):
                                return path, positionals, flags, name
                            value = args[index]
                        flags.setdefault(name, []).append(value)
                        flags.setdefault("_ordered", []).append((name, value))
                        break
                    attached = (
                        letters[offset + 2 :]
                        if letters[offset + 1 :].startswith("=")
                        else None
                    )
                    if attached is not None and attached not in PFLAG_BOOLEAN_VALUES:
                        return path, positionals, flags, name
                    flags.setdefault(name, []).append(attached)
                    flags.setdefault("_ordered", []).append((name, attached))
                    if attached is not None:
                        break
                    offset += 1
            index += 1
            continue
        child = (
            next(
                (
                    child
                    for child in node["children"]
                    if arg == child["name"] or arg in child["aliases"]
                ),
                None,
            )
            if path_open
            else None
        )
        if child is not None:
            path.append(child["name"])
            node = child
        elif not path:
            return path, positionals, flags, "command " + arg
        else:
            positionals.append(arg)
            path_open = False
        index += 1
    return path, positionals, flags, None


def gh_values(flags, *names):
    return [value for name, value in flags.get("_ordered", []) if name in names]


def issue_creation_problem(path, positionals, flags):
    if path == ["issue", "create"]:
        return ISSUE_REASON
    if path != ["api"]:
        return None
    endpoint = urlsplit(positionals[0]).path.lstrip("/") if positionals else None
    methods = gh_values(flags, "-X", "--method")
    method = methods[-1] if methods else None
    field_values = gh_values(flags, "-f", "-F", "--raw-field", "--field")
    fields = bool(field_values)
    body = bool(gh_values(flags, "--input"))
    if endpoint and re.fullmatch(r"repos/[^/]+/[^/]+/issues", endpoint):
        if (method or ("POST" if fields or body else "GET")).upper() == "POST":
            return ISSUE_REASON
    queries = [
        value.partition("=")[2] for value in field_values if value.startswith("query=")
    ]
    if endpoint == "graphql" and any(
        re.search(r"\bmutation\b[\s\S]*\bcreateIssue\s*\(", query) for query in queries
    ):
        return ISSUE_REASON
    return None


def gh_problem(args, agent):
    path, positionals, flags, unknown = parse_gh(args)
    if path == ["auth", "token"]:
        return "Secrets stay out of transcripts: gh auth token prints a token."
    if path == ["auth", "status"] and ("-t" in flags or "--show-token" in flags):
        return "Secrets stay out of transcripts: gh auth status can show a token."
    if unknown:
        if unknown.startswith("command "):
            return (
                "The guard can't judge this gh command: it doesn't know the command "
                + unknown.removeprefix("command ")
                + "."
            )
        return (
            "The guard can't judge this gh command: it doesn't know the flag "
            + unknown
            + "."
        )
    if path == ["pr", "merge"]:
        return "gh pr merge is refused."
    issue_reason = issue_creation_problem(path, positionals, flags)
    if issue_reason:
        return issue_reason
    if agent == "claude":
        return None
    if not path:
        return GH_REASON
    if path == ["api"]:
        methods = gh_values(flags, "-X", "--method")
        method = methods[-1] if methods else None
        fields = bool(gh_values(flags, "-f", "-F", "--raw-field", "--field"))
        body = bool(gh_values(flags, "--input"))
        return (
            None
            if method == "GET"
            and not body
            or method is None
            and not fields
            and not body
            else GH_REASON
        )
    return None if tuple(path) in GH_READS else GH_REASON


def unwrap(args):
    args = list(args)
    while args:
        name = os.path.basename(args[0])
        if name == "vault-run":
            if len(args) == 2 and args[1] in ("-h", "--help"):
                return [], None
            index = 1
            while index < len(args):
                arg = args[index]
                if arg == "--":
                    if index + 1 == len(args):
                        return (
                            [],
                            "Secrets stay out of transcripts: vault-run has no command.",
                        )
                    args = args[index + 1 :]
                    break
                if arg in ("--env", "--stdin"):
                    index += 1
                    if index == len(args) or not args[index] or args[index] == "--":
                        return (
                            [],
                            "Secrets stay out of transcripts: vault-run options are incomplete.",
                        )
                elif arg.startswith(("--env=", "--stdin=")):
                    if not arg.partition("=")[2]:
                        return (
                            [],
                            "Secrets stay out of transcripts: vault-run options are incomplete.",
                        )
                else:
                    return (
                        [],
                        "Secrets stay out of transcripts: vault-run options are unknown.",
                    )
                index += 1
            else:
                return (
                    [],
                    "Secrets stay out of transcripts: vault-run needs -- before its command.",
                )
            continue
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
    return args, None


def session_path(value):
    return "/" in value and value.rsplit("/", 1)[-1] == SESSION_FILE


def command(node, cwd, agent, source, pipeline_input=()):
    words = [part for part in node.parts if part.kind == "word"]
    raw_args = [bashlex_compat.word_value(part, source) for part in words]
    redirect_targets = [
        bashlex_compat.word_value(part.output, source)
        for part in node.parts
        if part.kind == "redirect"
        and isinstance(getattr(part, "output", None), bashlex.ast.node)
    ]
    if any(session_path(value) for value in (*raw_args, *redirect_targets)):
        return cwd, "Secrets stay out of transcripts: bw-session is the vault key."
    args, unwrap_problem = unwrap(raw_args)
    if unwrap_problem:
        return cwd, unwrap_problem
    if not args:
        return cwd, None
    name = os.path.basename(args[0])
    if name == VAULT_ENV:
        return cwd, "Secrets stay out of transcripts: use vault-run to fetch secrets."
    if (
        name == BW
        and args[1:]
        and args[1]
        not in ("status", "lock", "sync", "help", "--help", "-h", "--version")
    ):
        return cwd, "Secrets stay out of transcripts: bw can read the vault."
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
    if name == GIT:
        return cwd, git_problem(args[1:], cwd, agent)
    if name == GH:
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
            "Cannot parse a command mentioning "
            + ", ".join(GUARDED_PROGRAMS[:-1])
            + " or "
            + GUARDED_PROGRAMS[-1]
            + ": "
            + str(exc)
            if FALLBACK_WORD.search(normalized)
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
