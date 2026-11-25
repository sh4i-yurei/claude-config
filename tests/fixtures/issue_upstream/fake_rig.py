#!/usr/bin/python3
"""Return one approval row and record rig commands."""

import json
import os
from pathlib import Path
import sys


args = sys.argv[1:]
with Path(os.environ["FAKE_RIG_CALLS"]).open("a") as out:
    out.write(json.dumps(args) + "\n")
state = json.loads(Path(os.environ["FAKE_RIG_STATE"]).read_text())
if args == ["whoami", "--json"]:
    if state.get("whoami_failure"):
        print(state["whoami_failure"], file=sys.stderr)
        sys.exit(1)
    if state.get("missing_sender"):
        print(json.dumps({"identity": {}}))
        sys.exit(0)
    if state.get("invalid_whoami"):
        print("not JSON")
        sys.exit(0)
    print(
        json.dumps({"identity": {"senderAddress": state.get("seat", "filing@tooling")}})
    )
elif args[:2] == ["queue", "show"]:
    if (
        len(args) < 3
        or args[2] != state.get("approval_id", "qitem-approval")
        or state.get("missing")
    ):
        print(json.dumps({"error": "qitem_not_found"}))
        sys.exit(1)
    if any(arg not in ("--full", "--json") for arg in args[3:]):
        print("unknown option", file=sys.stderr)
        sys.exit(1)
    row = state.get("approval", {}).copy()
    if "--full" not in args:
        row["body"] = row.get("body", "")[:24]
    if "--json" not in args:
        print("approval row")
        sys.exit(0)
    print(json.dumps(row))
elif args[:2] == ["queue", "update"]:
    if state.get("update_failure"):
        print(
            state["update_failure"],
            file=sys.stdout if state.get("update_on_stdout") else sys.stderr,
        )
        sys.exit(1)
    print("updated")
else:
    print("unexpected rig command", args, file=sys.stderr)
    sys.exit(1)
