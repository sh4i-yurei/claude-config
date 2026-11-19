#!/usr/bin/python3
"""Commit named vault files without reading another session's staged files."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def _git(vault, *args, env=None, check=True, capture=True):
    return subprocess.run(
        ["git", *args],
        cwd=vault,
        env=env,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def _error(message, status):
    print(message, file=sys.stderr)
    return status


def _arguments(argv):
    parser = argparse.ArgumentParser(
        prog="vault-commit", usage="vault-commit -m MESSAGE -- PATH [PATH...]"
    )
    parser.add_argument("-m", required=True, metavar="MESSAGE")
    if "--" not in argv:
        parser.parse_args(argv)
        parser.error("-- before PATH is required")
    boundary = argv.index("--")
    options = parser.parse_args(argv[:boundary])
    paths = argv[boundary + 1 :]
    if not paths:
        parser.error("at least one PATH is required")
    return options.m, paths


def _paths(vault, names, old):
    relative = []
    for name in names:
        path = Path(name)
        absolute = path if path.is_absolute() else Path.cwd() / path
        resolved = absolute.parent.resolve() / absolute.name
        try:
            rel = resolved.relative_to(vault)
        except ValueError:
            return None, f"not in the vault: {name}"
        if resolved.is_dir() and not resolved.is_symlink():
            return None, f"not a file: {name}"
        tracked = (
            _git(
                vault, "cat-file", "-e", f"{old}:{rel.as_posix()}", check=False
            ).returncode
            == 0
        )
        if not resolved.exists() and not resolved.is_symlink() and not tracked:
            return None, f"not found: {name}"
        if (
            not tracked
            and _git(
                vault, "check-ignore", "-q", "--", rel.as_posix(), check=False
            ).returncode
            == 0
        ):
            return None, f"ignored by the vault: {name}"
        relative.append(rel.as_posix())
    return relative, None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        message, names = _arguments(argv)
    except SystemExit as error:
        return error.code

    vault_given = Path(
        os.environ.get("SECOND_BRAIN", "~/Documents/Second_Brain")
    ).expanduser()
    vault = vault_given.resolve()
    if not vault.is_dir():
        return _error(f"not a git repository: {vault_given}", 2)
    top = _git(vault, "rev-parse", "--show-toplevel", check=False)
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != vault:
        return _error(f"not a git repository: {vault_given}", 2)

    branch_result = _git(
        vault, "symbolic-ref", "--quiet", "--short", "HEAD", check=False
    )
    if branch_result.returncode:
        return _error("the vault is not on a branch", 2)
    branch = branch_result.stdout.strip()
    old = _git(vault, "rev-parse", "HEAD").stdout.strip()
    paths, error = _paths(vault, names, old)
    if error:
        return _error(error, 2)

    hook_path = _git(
        vault, "rev-parse", "--git-path", "hooks/pre-commit"
    ).stdout.strip()
    hook = Path(hook_path)
    if not hook.is_absolute():
        hook = vault / hook
    if not hook.is_file() or not os.access(hook, os.X_OK):
        return _error("the vault has no pre-commit hook: set core.hooksPath", 2)

    for _ in range(3):
        old = _git(vault, "rev-parse", "HEAD").stdout.strip()
        hook_run = _git(vault, "hook", "run", "pre-commit", check=False, capture=False)
        if hook_run.returncode:
            return _error("vault check failed; nothing committed", 1)
        with tempfile.TemporaryDirectory(prefix="vault-commit-") as folder:
            index = Path(folder) / "index"
            environment = os.environ.copy()
            environment["GIT_INDEX_FILE"] = str(index)
            _git(vault, "read-tree", old, env=environment)
            _git(vault, "add", "-A", "--", *paths, env=environment)
            tree = _git(vault, "write-tree", env=environment).stdout.strip()
            previous_tree = _git(vault, "rev-parse", f"{old}^{{tree}}").stdout.strip()
            if tree == previous_tree:
                print("nothing to commit in those paths")
                return 0
            new = _git(
                vault, "commit-tree", tree, "-p", old, "-m", message
            ).stdout.strip()
        moved = _git(vault, "update-ref", f"refs/heads/{branch}", new, old, check=False)
        if moved.returncode:
            continue

        short = _git(vault, "rev-parse", "--short", new).stdout.strip()
        reset = _git(vault, "reset", "-q", "--", *paths, check=False)
        push = _git(vault, "push", "-q", "origin", branch, check=False)
        if push.returncode:
            print(f"committed {short} locally; the push was refused", file=sys.stderr)
            print(push.stderr, end="", file=sys.stderr)
        if reset.returncode:
            print(reset.stderr, end="", file=sys.stderr)
            return _error(
                f"committed {short}, but resetting its paths in the shared index failed",
                1,
            )
        if push.returncode:
            return 1
        print(_git(vault, "log", "--oneline", "-1", new).stdout.strip())
        return 0
    return _error(f"{branch} kept moving; nothing committed", 1)


if __name__ == "__main__":
    sys.exit(main())
