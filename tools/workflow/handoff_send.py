"""Deliver a handoff to a named interactive session."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import yaml


FRONTMATTER = re.compile(r"\A---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|\Z)")


def positive_number(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive whole number") from error
    if number < 1 or str(number) != value:
        raise argparse.ArgumentTypeError("must be a positive whole number")
    return number


def refuse(message, code=2):
    print(message, file=sys.stderr)
    return code


class InvalidHerdrResponse(Exception):
    """A herdr call returned an answer that cannot be read."""


def herdr(args):
    try:
        result = subprocess.run(["herdr", *args], capture_output=True)
        raw = result.stdout if result.returncode == 0 else result.stderr
        answer = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise InvalidHerdrResponse(
            f"herdr {' '.join(args[:2])}: invalid response"
        ) from None
    if not isinstance(answer, dict):
        raise InvalidHerdrResponse(f"herdr {' '.join(args[:2])}: invalid response")
    if result.returncode:
        error = answer.get("error")
        if not isinstance(error, dict):
            raise InvalidHerdrResponse(f"herdr {' '.join(args[:2])}: invalid response")
        code, message = error.get("code"), error.get("message")
        if not isinstance(code, str) or not isinstance(message, str):
            raise InvalidHerdrResponse(f"herdr {' '.join(args[:2])}: invalid response")
        return None, code, message
    details = answer.get("result")
    if not isinstance(details, dict):
        raise InvalidHerdrResponse(f"herdr {' '.join(args[:2])}: invalid response")
    agent = details.get("agent")
    status = agent.get("agent_status") if isinstance(agent, dict) else None
    return status, None, None


def command_error(args, message):
    return refuse(f"herdr {' '.join(args[:2])}: {message}", 1)


def run(argv=None):
    parser = argparse.ArgumentParser(prog="handoff_send.py", description=__doc__)
    parser.add_argument("mode", choices=("deliver", "reply"))
    parser.add_argument("handoff")
    parser.add_argument("--wait-minutes", type=positive_number, default=30)
    args = parser.parse_args(argv)

    folder = Path(
        os.environ.get(
            "HANDOFFS_DIR", Path.home() / "Documents/Second_Brain/05_Agents/handoffs"
        )
    ).resolve()
    supplied = Path(args.handoff)
    path = (folder / supplied if supplied.parent == Path(".") else supplied).resolve()
    if path.suffix != ".md" or path.parent != folder:
        return refuse(f"not a handoff in {folder}: {args.handoff}")
    if not path.is_file():
        return refuse(f"no such handoff: {args.handoff}")
    try:
        content = path.read_text()
        match = FRONTMATTER.match(content)
        fields = yaml.safe_load(match.group(1)) if match else None
    except (OSError, UnicodeError, yaml.YAMLError):
        fields = None
    if not isinstance(fields, dict):
        return refuse(f"{path.name} has no readable frontmatter")

    if args.mode == "deliver":
        state = fields.get("state")
        if state is None:
            return refuse(f"{path.name} has no state: field")
        if state != "open":
            return refuse(f"{path.name} is {state}, not open")
    key = "session" if args.mode == "deliver" else "reply_to"
    target = fields.get(key)
    if not isinstance(target, str) or not target.strip():
        return refuse(f"{path.name} has no {key}: field")
    target = target.strip()
    if shutil.which("herdr") is None:
        return refuse("herdr is not on PATH")

    get_args = ["agent", "get", target]
    _, reason, message = herdr(get_args)
    if message is not None:
        if reason == "agent_not_found":
            return refuse(f"no live session named {target}", 1)
        return command_error(get_args, message)

    wait_args = ["agent", "wait", target, "--timeout", str(args.wait_minutes * 60_000)]
    status, reason, message = herdr(wait_args)
    if message is not None:
        if reason == "agent_not_found":
            return refuse(f"no live session named {target}", 1)
        if reason == "timeout":
            return refuse(
                f"{target} was not idle after {args.wait_minutes} minutes; nothing was sent",
                1,
            )
        return command_error(wait_args, message)
    if status not in ("idle", "done", "blocked"):
        return command_error(wait_args, "invalid response")
    if status == "blocked":
        return refuse(f"{target} is waiting on a prompt; nothing was sent", 1)

    prompt = (
        f"Read {path} and follow its Request."
        if args.mode == "deliver"
        else f"Your handoff {path} has its Response."
    )
    prompt_args = [
        "agent",
        "prompt",
        target,
        prompt,
        "--wait",
        "--until",
        "working",
        "--until",
        "blocked",
        "--timeout",
        "10000",
    ]
    status, reason, message = herdr(prompt_args)
    last_args = prompt_args
    if message is not None and reason == "agent_prompt_stalled":
        keys_args = ["agent", "send-keys", target, "enter"]
        _, reason, message = herdr(keys_args)
        if message is not None:
            if reason == "agent_not_found":
                return refuse(f"no live session named {target}", 1)
            return command_error(keys_args, message)
        start_args = [
            "agent",
            "wait",
            target,
            "--until",
            "working",
            "--until",
            "blocked",
            "--timeout",
            "5000",
        ]
        status, reason, message = herdr(start_args)
        last_args = start_args
        if message is not None and reason == "timeout":
            return refuse(
                f"{target} did not start on the prompt; it may be sitting in its input box",
                1,
            )
    if message is not None:
        if reason == "agent_not_found":
            return refuse(f"no live session named {target}", 1)
        if reason == "agent_blocked":
            return refuse(f"{target} is waiting on a prompt; nothing was sent", 1)
        return command_error(last_args, message)
    if status not in ("working", "blocked"):
        return refuse(
            f"{target} did not start on the prompt; it may be sitting in its input box",
            1,
        )
    if args.mode == "deliver":
        print(f"delivered {path.name} to {target}")
    else:
        print(f"told {target} that {path.name} has its Response")
    return 0


def main(argv=None):
    try:
        return run(argv)
    except InvalidHerdrResponse as error:
        return refuse(str(error), 1)


if __name__ == "__main__":
    raise SystemExit(main())
