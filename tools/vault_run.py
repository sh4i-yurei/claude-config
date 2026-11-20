#!/usr/bin/python3
"""Run a command with selected Bitwarden fields or one password."""

import argparse
import os
import subprocess
import sys

import vault_item

TOKEN_ITEM = "API tokens (keepbreath.ing)"


def _parser():
    parser = argparse.ArgumentParser(
        prog="vault-run",
        usage="vault-run [--env NAME]... [--stdin ITEM] -- COMMAND [ARG]...",
    )
    parser.add_argument("--env", action="append", metavar="NAME")
    parser.add_argument("--stdin", action="append", metavar="ITEM", default=[])
    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = _parser()
    try:
        if "--" in argv:
            boundary = argv.index("--")
            options = parser.parse_args(argv[:boundary])
            command = argv[boundary + 1 :]
        else:
            options = parser.parse_args(argv)
            parser.error("-- before COMMAND is required")
        if (
            not command
            or (not options.env and not options.stdin)
            or len(options.stdin) > 1
        ):
            parser.error("one --env or --stdin and one COMMAND are required")
    except SystemExit as error:
        return error.code

    child_environment = os.environ.copy()
    child_environment.pop("BW_SESSION", None)
    if options.env:
        try:
            item = vault_item.read_item(TOKEN_ITEM)
        except vault_item.VaultItemError as error:
            print(f"vault-run: {error}", file=sys.stderr)
            return 1
        fields = {
            field.get("name"): field.get("value") for field in item.get("fields", [])
        }
        for name in options.env:
            if name not in fields or fields[name] is None:
                print(f'vault-run: no field {name} on "{TOKEN_ITEM}"', file=sys.stderr)
                return 2
            child_environment[name] = fields[name]

    password = None
    if options.stdin:
        name = options.stdin[0]
        try:
            item = vault_item.read_item(name)
        except vault_item.VaultItemError as error:
            print(f"vault-run: {error}", file=sys.stderr)
            return 1
        password = item.get("login", {}).get("password")
        if password is None:
            print(f'vault-run: "{name}" has no password', file=sys.stderr)
            return 2

    try:
        process = subprocess.Popen(
            command,
            env=child_environment,
            stdin=subprocess.PIPE if password is not None else None,
        )
    except FileNotFoundError:
        print(f"vault-run: command not found: {command[0]}", file=sys.stderr)
        return 127
    if password is not None:
        process.communicate((password + "\n").encode())
    else:
        process.wait()
    return process.returncode if process.returncode >= 0 else 128 - process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
