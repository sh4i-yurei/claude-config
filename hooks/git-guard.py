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
import stat
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
VAULT_COMMIT = "vault-commit"
SESSION_FILE = "bw-session"
FALLBACK_WORD = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    + "|".join(
        re.escape(name) for name in (*GUARDED_PROGRAMS, VAULT_COMMIT, SESSION_FILE)
    )
    + r")(?![A-Za-z0-9_])"
)
PFLAG_BOOLEAN_VALUES = frozenset(
    ("1", "t", "T", "TRUE", "true", "True", "0", "f", "F", "FALSE", "false", "False")
)
# RTK v1.2.1 command and option words, read from its clap definitions and dispatch.
RTK_TOP_LEVEL_SKIP_WORDS = ("--verbose", "--skip-env")
RTK_HELP_VERSION_WORDS = ("-h", "--help", "-V", "--version")
RTK_GIT_VALUE_OPTIONS = ("-C", "-c", "--git-dir", "--work-tree")
RTK_GT_GIT_SUBCOMMANDS = (
    "status",
    "diff",
    "show",
    "add",
    "push",
    "pull",
    "fetch",
    "stash",
    "worktree",
)
RTK_PIPELINE_GH_SUBCOMMANDS = ("share", "add", "search")
RTK_READABLE_SHELLS = ("sh", "bash", "dash")
RTK_RUN_VALUE_OPTIONS = ("-c", "--command", "--shell")
RTK_FILTER_VALUE_OPTIONS = ("--shell",)
RTK_EXECUTABLE_SUBCOMMANDS = ("run", "err", "summary", "test")
RTK_BYPASS_SUBCOMMANDS = ("bypass", "proxy")
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
# OpenRig rig 0.7.19 uses commander 13.1.0. True means the exact option takes a value.
RIG_QUEUE_CREATE_OPTIONS = {
    **dict.fromkeys(
        (
            "--source",
            "--destination",
            "--body",
            "--body-file",
            "--body-context",
            "--mission",
            "--slice",
            "--gate",
            "--priority",
            "--tier",
            "--tags",
            "--expires-at",
            "--id",
            "--target-repo",
            "--summary",
            "--human-intent",
            "--human-detail-file",
            "--reply-to",
            "--human-questions-file",
            "--evidence-ref",
            "--host",
            "--return-route",
        ),
        True,
    ),
    **dict.fromkeys(
        ("--alert", "--no-nudge", "--verify", "--full", "--json", "-h", "--help"), False
    ),
}
RIG_QUEUE_HANDOFF_OPTIONS = {
    **dict.fromkeys(
        (
            "--from",
            "--to",
            "--body",
            "--body-file",
            "--note",
            "--priority",
            "--tier",
            "--tags",
            "--gate",
            "--target-repo",
            "--summary",
            "--evidence-ref",
            "--host",
        ),
        True,
    ),
    **dict.fromkeys(
        ("--alert", "--no-nudge", "--full", "--json", "-h", "--help"), False
    ),
}
RIG_QUEUE_OPTIONS = {
    "create": RIG_QUEUE_CREATE_OPTIONS,
    "handoff": RIG_QUEUE_HANDOFF_OPTIONS,
    "handoff-and-complete": RIG_QUEUE_HANDOFF_OPTIONS,
}
RIG_QUEUE_TAG_REASON = (
    "Every queue task carries a project: tag and an item: tag, so it can be "
    "found by project and item (OpenRig team decision 16)."
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
STRICT_PUSH_REASON = "Only Claude pushes: commit on the named branch and stop."
STRICT_ALIAS_REASON = (
    "Git aliases are refused under the strict policy, because one can hide a push: "
    "run the command it stands for."
)
ISSUE_REASON = "Use tools/workflow/issue.py open for our repositories, or issue.py upstream for one outside our boards; see README.md, Opening an issue from a file."
DEADLINE = None
MAX_COMMAND_BYTES = 64 * 1024
ATTRIBUTION_REASON = (
    "Commits and pull requests carry no AI attribution: remove the Co-authored-by "
    "trailer or Generated with line (Operating model decision 12)."
)
COMMIT_OPTIONS = Path(__file__).with_name("git-commit-options-2.54.0.txt")
MAX_MESSAGE_BYTES = 1024 * 1024


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


def commit_options(args, directory):
    """Ask Git to canonicalize commit options, preserving attached values."""
    check_budget()
    remaining = DEADLINE - time.monotonic() if DEADLINE is not None else 2
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--parseopt", "--stuck-long", "--", *args],
            cwd=directory,
            input=COMMIT_OPTIONS.read_text(),
            capture_output=True,
            text=True,
            timeout=min(2, remaining),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Command was too complex to judge in time.") from exc
    if not result.stderr and result.stdout.startswith("cat <<"):
        return []
    if result.returncode:
        first_error = (
            result.stderr.splitlines()[0]
            if result.stderr
            else "Git rejected the arguments."
        )
        raise ValueError("The guard can't judge this git commit: " + first_error)
    return shlex.split(result.stdout)[2:]


def has_attribution(message, trailer=False):
    if trailer and message.lower().startswith("co-authored-by"):
        return True
    message = message.replace("\\n", "\n")
    return bool(
        re.search(r"(?im)^\s*co-authored-by:", message)
        or re.search(r"(?im)^[^A-Za-z]*generated with", message)
    )


def message_file_text(name, directory):
    path = Path(os.path.expanduser(name))
    path = path if path.is_absolute() else Path(directory) / path
    try:
        with os.fdopen(
            os.open(path, os.O_RDONLY | os.O_NONBLOCK), "rb"
        ) as message_file:
            info = os.fstat(message_file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_MESSAGE_BYTES:
                raise OSError("not a regular message file within the size limit")
            content = message_file.read(MAX_MESSAGE_BYTES)
    except OSError as exc:
        raise ValueError(
            f"The guard can't read the commit message file {name}."
        ) from exc
    return content.decode("utf-8", errors="replace")


def vault_commit_problem(args):
    before_paths = args[: args.index("--")] if "--" in args else args
    index = 0
    while index < len(before_paths):
        arg = before_paths[index]
        if arg == "-m" and index + 1 < len(before_paths):
            index += 1
            message = before_paths[index]
        elif arg.startswith("-m") and len(arg) > 2:
            message = arg[3:] if arg[2] == "=" else arg[2:]
        else:
            index += 1
            continue
        if has_attribution(message):
            return ATTRIBUTION_REASON
        index += 1
    return None


GIT_CACHE = {}
MAX_GIT_LOOKUPS = 512


def directory_for(args, cwd):
    directory = cwd
    git_dir = None
    work_tree = None
    unknown = None
    config_override = False
    config_options = []
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
            elif flag in ("-c", "--config-env"):
                config_override = True
                config_options.extend((flag, args[index + 1]))
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
            if flag.startswith(("-c", "--config-env=")):
                config_override = True
            if flag.startswith("--config-env="):
                config_options.append(flag)
            index += 1
        else:
            unknown = flag
            index += 1
    lookup = []
    if git_dir is not None:
        lookup.append("--git-dir=" + git_dir)
    if work_tree is not None:
        lookup.append("--work-tree=" + work_tree)
    return directory, args[index:], lookup, unknown, config_override, config_options


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
    if agent != "claude":
        return STRICT_PUSH_REASON
    if any(a in ("--all", "--mirror") for a in args):
        return PUSH_REASON
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
    directory, args, lookup, unknown, config_override, config_options = directory_for(
        args, cwd
    )
    if not args:
        return None
    action = args[0]
    if agent != "claude":
        alias = run_git(
            directory,
            *lookup,
            *config_options,
            "config",
            "--get",
            "alias." + action,
        )
        if (
            alias
            and action
            not in run_git(directory, "--list-cmds=builtins,main,others").splitlines()
        ):
            return STRICT_ALIAS_REASON
    if action == "commit":
        top_level = run_git(directory, *lookup, "rev-parse", "--show-toplevel")
        vault = Path(
            os.environ.get("SECOND_BRAIN", Path.home() / "Documents/Second_Brain")
        )
        if top_level and Path(top_level).resolve() == vault.resolve():
            return (
                "Commit vault work with vault-commit -m MESSAGE -- PATH...: a plain git "
                "commit in the shared vault checkout can take another session's staged files."
            )
        try:
            parsed = commit_options(args[1:], directory)
            for option in parsed:
                if option == "--":
                    break
                if option.startswith("--message="):
                    if has_attribution(option.partition("=")[2]):
                        return ATTRIBUTION_REASON
                elif option.startswith("--trailer="):
                    if has_attribution(option.partition("=")[2], trailer=True):
                        return ATTRIBUTION_REASON
                elif option.startswith("--file="):
                    name = option.partition("=")[2]
                    if name != "-" and has_attribution(
                        message_file_text(name, directory)
                    ):
                        return ATTRIBUTION_REASON
        except ValueError as exc:
            return str(exc)
    if unknown and action in ("push", "merge", "pull"):
        return "Unknown git global option for " + action + ": " + unknown
    if agent != "claude" and action in ("send-pack", "http-push"):
        return STRICT_PUSH_REASON
    if action in ("merge", "pull"):
        branch = run_git(directory, *lookup, "branch", "--show-current")
        if branch in PROTECTED_BRANCHES or not branch:
            refusal = (
                "git merge and git pull are refused on main, master, or an unknown "
                "branch, except a fast-forward to the branch's own upstream with --ff-only."
            )
            if config_override:
                return refusal
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
        return (
            None
            if flags == {"--version": [None], "_ordered": [("--version", None)]}
            else GH_REASON
        )
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


# sudo 1.9.17p2, src/parse_args.c: sudo_short_opts and sudo_long_opts.
SUDO_SHORT_OPTIONS = {
    "A": "none",
    "a": "required",
    "B": "none",
    "b": "none",
    "C": "required",
    "c": "required",
    "D": "required",
    "E": "none",
    "e": "none",
    "g": "required",
    "H": "none",
    "h": "optional",
    "i": "none",
    "K": "none",
    "k": "none",
    "l": "none",
    "N": "none",
    "n": "none",
    "P": "none",
    "p": "required",
    "R": "required",
    "r": "required",
    "S": "none",
    "s": "none",
    "T": "required",
    "t": "required",
    "U": "required",
    "u": "required",
    "V": "none",
    "v": "none",
}
SUDO_LONG_OPTIONS = {
    "background": "none",
    "preserve-env": "equals-only",
    "edit": "none",
    "set-home": "none",
    "login": "none",
    "remove-timestamp": "none",
    "list": "none",
    "preserve-groups": "none",
    "shell": "none",
    "other-user": "required",
    "validate": "none",
    "askpass": "none",
    "auth-type": "required",
    "bell": "none",
    "close-from": "required",
    "login-class": "required",
    "chdir": "required",
    "group": "required",
    "help": "none",
    "host": "required",
    "reset-timestamp": "none",
    "no-update": "none",
    "non-interactive": "none",
    "prompt": "required",
    "chroot": "required",
    "role": "required",
    "stdin": "none",
    "command-timeout": "required",
    "type": "required",
    "user": "required",
    "version": "none",
}


def sudo_variable(word):
    return "=" in word and not word.startswith(("/", "="))


def sudo_command_index(args):
    index = 1
    while index < len(args):
        word = args[index]
        if word == "--":
            return index + 1, None
        if word.startswith("--"):
            name, separator, _value = word[2:].partition("=")
            if name in SUDO_LONG_OPTIONS:
                option = name
            else:
                matches = [
                    candidate
                    for candidate in SUDO_LONG_OPTIONS
                    if candidate.startswith(name)
                ]
                option = matches[0] if len(matches) == 1 else None
            if option is None or separator and SUDO_LONG_OPTIONS[option] == "none":
                return (
                    0,
                    f"The guard can't judge this sudo command: it doesn't know the option {word}.",
                )
            if SUDO_LONG_OPTIONS[option] == "required" and not separator:
                if index + 1 == len(args):
                    return (
                        0,
                        f"The guard can't judge this sudo command: the option {word} has no value.",
                    )
                index += 1
            index += 1
            continue
        if word.startswith("-") and len(word) > 1:
            for offset, letter in enumerate(word[1:], 1):
                kind = SUDO_SHORT_OPTIONS.get(letter)
                if kind is None:
                    return (
                        0,
                        f"The guard can't judge this sudo command: it doesn't know the option {word}.",
                    )
                if kind == "required":
                    if offset == len(word) - 1:
                        if index + 1 == len(args):
                            return (
                                0,
                                f"The guard can't judge this sudo command: the option {word} has no value.",
                            )
                        index += 1
                    break
                if kind == "optional":
                    if (
                        offset == len(word) - 1
                        and word == "-h"
                        and index + 1 < len(args)
                    ):
                        next_word = args[index + 1]
                        if not next_word.startswith("-") and not sudo_variable(
                            next_word
                        ):
                            index += 1
                    break
            index += 1
            continue
        if sudo_variable(word):
            index += 1
            continue
        break
    return index, None


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
            index, problem = sudo_command_index(args)
            if problem:
                return [], problem
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


def rtk_commands(words):
    """Return possible argument lists, scripts, and an unreadable-form reason."""
    words = list(words)
    while words and (
        words[0] in RTK_TOP_LEVEL_SKIP_WORDS or re.fullmatch(r"-v+", words[0])
    ):
        words.pop(0)
    if not words or words[0] in RTK_HELP_VERSION_WORDS:
        return [], [], None
    if words[0].startswith("-"):
        return [], [], rtk_unknown_option(words[0])
    subcommand, *args = words
    if subcommand == "git":
        # Only options before the git subcommand belong to RTK.
        index = 0
        while index < len(args):
            word = args[index]
            if word == "--skip-env":
                args.pop(index)
                continue
            if word in RTK_GIT_VALUE_OPTIONS:
                index += 2
            elif word.startswith("-"):
                index += 1
            else:
                break
        return [["git", *args]], [], None
    if subcommand == "gh":
        while args and args[0] == "--skip-env":
            args.pop(0)
        if args and args[0] == "--":
            args.pop(0)
        return [["gh", *args]], [], None
    if subcommand == "gt":
        while args and args[0] == "--skip-env":
            args.pop(0)
        program = "git" if args and args[0] in RTK_GT_GIT_SUBCOMMANDS else "gt"
        return [[program, *args]], [], None
    if subcommand in RTK_EXECUTABLE_SUBCOMMANDS:
        return rtk_executable_commands(subcommand, args)
    if subcommand in RTK_BYPASS_SUBCOMMANDS:
        while args and args[0] == "--skip-env":
            args.pop(0)
        if len(args) == 1:
            try:
                args = shlex.split(args[0])
            except ValueError:
                return (
                    [],
                    [],
                    (
                        "The guard can't judge this rtk command: "
                        f"it can't split the word {args[0]}."
                    ),
                )
        return [args] if args else [], [], None
    if subcommand == "pipeline":
        while args and args[0] == "--skip-env":
            args.pop(0)
        if args and args[0] in RTK_PIPELINE_GH_SUBCOMMANDS:
            return (
                [],
                [],
                (
                    f"The guard can't judge rtk pipeline {args[0]}: "
                    "it runs gh with arguments that aren't on the command line."
                ),
            )
        return [], [], None
    commands = [[subcommand, *args]]
    if "--" in args:
        commands.append(args[args.index("--") + 1 :])
    return commands, [], None


def rtk_unknown_option(word):
    return f"The guard can't judge this rtk command: it doesn't know the option {word}."


def rtk_executable_commands(subcommand, args):
    script = None
    shell = None
    index = 0
    while index < len(args):
        word = args[index]
        if word == "--":
            index += 1
            break
        if not word.startswith("-"):
            break
        if word == "--skip-env":
            index += 1
            continue
        if subcommand == "test" and not (
            word == "--shell" or word.startswith("--shell=")
        ):
            break
        valued = (
            RTK_FILTER_VALUE_OPTIONS if subcommand != "run" else RTK_RUN_VALUE_OPTIONS
        )
        option, equal, value = word.partition("=")
        if option not in valued or (equal and option == "-c"):
            return [], [], rtk_unknown_option(word)
        if not equal:
            if index + 1 == len(args):
                return (
                    [],
                    [],
                    (
                        f"The guard can't judge this rtk command: the option {word} has no value."
                    ),
                )
            value = args[index + 1]
            index += 1
        if option == "--shell":
            shell = value
        else:
            script = value
        index += 1
    remaining = args[index:]
    if subcommand == "test":
        while remaining and remaining[0] == "!":
            remaining = remaining[1:]
        if len(remaining) >= 2 and remaining[0] == "(" and remaining[-1] == ")":
            remaining = remaining[1:-1]
        if remaining and remaining[0].startswith("-"):
            return [], [], None
    if script is not None or (
        subcommand != "run" and shell is not None and len(remaining) == 1
    ):
        if shell is not None and os.path.basename(shell) not in RTK_READABLE_SHELLS:
            return (
                [],
                [],
                (
                    f"The guard can't judge this rtk command: it can't read a {shell} script."
                ),
            )
        return [], [script if script is not None else remaining[0]], None
    commands = [remaining] if remaining else []
    scripts = []
    if len(remaining) == 1:
        scripts.append(remaining[0])
    return commands, scripts, None


def rig_queue_problem(args):
    if len(args) < 2 or args[0] != "queue" or args[1] not in RIG_QUEUE_OPTIONS:
        return None
    options = RIG_QUEUE_OPTIONS[args[1]]
    tags_value = ""
    index = 2
    while index < len(args):
        word = args[index]
        if word == "--":
            break
        if word == "-" or not word.startswith("-"):
            index += 1
            continue
        option, equals, attached = word.partition("=")
        if option not in options or (equals and not options[option]):
            return f"The guard can't judge this rig command: it doesn't know the option {word}."
        if options[option]:
            if equals:
                value = attached
            else:
                if index + 1 >= len(args):
                    return f"The guard can't judge this rig command: the option {word} has no value."
                index += 1
                value = args[index]
            if option == "--tags":
                tags_value = value
        elif option in ("-h", "--help"):
            return None
        index += 1
    tags = [tag.strip() for tag in tags_value.split(",") if tag.strip()]
    if not any(
        tag.startswith("project:") and len(tag) > len("project:") for tag in tags
    ):
        return RIG_QUEUE_TAG_REASON
    if not any(tag.startswith("item:") and len(tag) > len("item:") for tag in tags):
        return RIG_QUEUE_TAG_REASON
    return None


def command(node, cwd, agent, source, pipeline_input=(), candidate_args=None):
    words = [part for part in node.parts if part.kind == "word"]
    raw_args = (
        [bashlex_compat.word_value(part, source) for part in words]
        if candidate_args is None
        else candidate_args
    )
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
    if name == "rtk":
        commands, scripts, problem = rtk_commands(args[1:])
        if problem:
            return cwd, problem
        for value in commands:
            reason = command(node, cwd, agent, source, pipeline_input, value)[1]
            if reason:
                return cwd, reason
        for value in scripts:
            reason = script_problem(value, cwd, agent)
            if reason:
                return cwd, reason
        return cwd, None
    if name in (VAULT_ENV, "vault_env.py"):
        return cwd, "Secrets stay out of transcripts: use vault-run to fetch secrets."
    if name in (VAULT_COMMIT, "vault_commit.py"):
        return cwd, vault_commit_problem(args[1:])
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
    if name == "rig":
        return cwd, rig_queue_problem(args[1:])
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
            + ", "
            + GUARDED_PROGRAMS[-1]
            + " or "
            + VAULT_COMMIT
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
