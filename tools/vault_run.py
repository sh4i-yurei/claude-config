"""Run a command with selected Bitwarden fields or one password."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


CONTAINER_MARKER = Path("/run/.containerenv")
TOKEN_ITEM = "API tokens (keepbreath.ing)"


def _parser():
    parser = argparse.ArgumentParser(
        prog="vault-run",
        usage="vault-run [--env NAME]... [--stdin ITEM] -- COMMAND [ARG]...",
    )
    parser.add_argument("--env", action="append", metavar="NAME")
    parser.add_argument("--stdin", action="append", metavar="ITEM", default=[])
    return parser


def _read_item(name, environment):
    try:
        result = subprocess.run(
            ["bw", "get", "item", name],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
    except (OSError, ValueError):
        pass
    print(
        f'vault-run: nothing from the vault for "{name}". '
        "Is the vault unlocked, and does the item exist? Run vu.",
        file=sys.stderr,
    )
    return None


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

    if not CONTAINER_MARKER.is_file():
        print(
            "vault-run: bw runs only inside the dev container (distrobox enter dev)",
            file=sys.stderr,
        )
        return 1

    bw_environment = os.environ.copy()
    bw_environment["BW_NOINTERACTION"] = "true"
    if not bw_environment.get("BW_SESSION"):
        session_file = (
            Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
            / "bw-session"
        )
        try:
            bw_environment["BW_SESSION"] = session_file.read_text()
        except OSError:
            bw_environment.pop("BW_SESSION", None)

    child_environment = os.environ.copy()
    child_environment.pop("BW_SESSION", None)
    if options.env:
        item = _read_item(TOKEN_ITEM, bw_environment)
        if item is None:
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
        item = _read_item(name, bw_environment)
        if item is None:
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
