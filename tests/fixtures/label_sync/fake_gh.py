#!/usr/bin/python3
"""Replay captured GitHub data and record the public gh command interface."""

import json
import os
from pathlib import Path
import sys


state_path = Path(os.environ["FAKE_GH_STATE"])
calls_path = Path(os.environ["FAKE_GH_CALLS"])
state = json.loads(state_path.read_text())
args = sys.argv[1:]
with calls_path.open("a") as calls:
    calls.write(json.dumps(args) + "\n")

failure = state.get("failure")
if failure and failure["command"] == args[: len(failure["command"])]:
    print(failure["message"], file=sys.stderr)
    sys.exit(1)

if args[:2] == ["repo", "list"]:
    result = state["repos"]
elif args[:2] == ["label", "list"]:
    result = state["labels"][args[args.index("--repo") + 1]]
elif args[:2] == ["issue", "list"]:
    repo = args[args.index("--repo") + 1]
    label = args[args.index("--label") + 1]
    result = [
        {"number": number}
        for number in state.get("issues", {}).get(repo, {}).get(label, [])
    ]
elif args[:2] == ["pr", "list"]:
    repo = args[args.index("--repo") + 1]
    label = args[args.index("--label") + 1]
    result = [
        {"number": number}
        for number in state.get("pull_requests", {}).get(repo, {}).get(label, [])
    ]
elif args[:2] == ["label", "create"]:
    repo = args[args.index("--repo") + 1]
    name = args[2]
    labels = state["labels"][repo]
    labels[:] = [label for label in labels if label["name"] != name]
    labels.append(
        {
            "name": name,
            "color": args[args.index("--color") + 1],
            "description": args[args.index("--description") + 1],
            "isDefault": False,
        }
    )
    result = None
elif args[:2] == ["label", "delete"]:
    repo = args[args.index("--repo") + 1]
    state["labels"][repo] = [
        label for label in state["labels"][repo] if label["name"] != args[2]
    ]
    result = None
else:
    print(f"unexpected gh command: {args}", file=sys.stderr)
    sys.exit(1)

state_path.write_text(json.dumps(state))
if result is not None:
    print(json.dumps(result))
