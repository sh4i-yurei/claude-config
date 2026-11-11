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


def herdr(args):
    result = subprocess.run(["herdr", *args], text=True, capture_output=True)
    try:
        answer = json.loads(result.stdout if result.returncode == 0 else result.stderr)
    except json.JSONDecodeError:
        answer = {}
    return result.returncode, answer


def command_error(args, answer):
    message = answer.get("error", {}).get("message", "invalid response")
    return refuse(f"herdr {' '.join(args[:2])}: {message}", 1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
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

    code, answer = herdr(["agent", "get", target])
    if code:
        if answer.get("error", {}).get("code") == "agent_not_found":
            return refuse(f"no live session named {target}", 1)
        return command_error(["agent", "get"], answer)

    wait_args = ["agent", "wait", target, "--timeout", str(args.wait_minutes * 60_000)]
    code, answer = herdr(wait_args)
    if code:
        reason = answer.get("error", {}).get("code")
        if reason == "agent_not_found":
            return refuse(f"no live session named {target}", 1)
        if reason == "timeout":
            return refuse(
                f"{target} was not idle after {args.wait_minutes} minutes; nothing was sent",
                1,
            )
        return command_error(wait_args, answer)
    if answer.get("result", {}).get("agent", {}).get("agent_status") == "blocked":
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
    code, answer = herdr(prompt_args)
    if code and answer.get("error", {}).get("code") == "agent_prompt_stalled":
        keys_args = ["agent", "send-keys", target, "enter"]
        code, answer = herdr(keys_args)
        if code:
            if answer.get("error", {}).get("code") == "agent_not_found":
                return refuse(f"no live session named {target}", 1)
            return command_error(keys_args, answer)
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
        code, answer = herdr(start_args)
        if code and answer.get("error", {}).get("code") == "timeout":
            return refuse(
                f"{target} did not start on the prompt; it may be sitting in its input box",
                1,
            )
    if code:
        reason = answer.get("error", {}).get("code")
        if reason == "agent_not_found":
            return refuse(f"no live session named {target}", 1)
        if reason == "agent_blocked":
            return refuse(f"{target} is waiting on a prompt; nothing was sent", 1)
        return command_error(
            prompt_args
            if answer.get("id") == "cli:agent:prompt"
            else ["agent", "wait"],
            answer,
        )
    if answer.get("result", {}).get("agent", {}).get("agent_status") not in (
        "working",
        "blocked",
    ):
        return refuse(
            f"{target} did not start on the prompt; it may be sitting in its input box",
            1,
        )
    if args.mode == "deliver":
        print(f"delivered {path.name} to {target}")
    else:
        print(f"told {target} that {path.name} has its Response")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
