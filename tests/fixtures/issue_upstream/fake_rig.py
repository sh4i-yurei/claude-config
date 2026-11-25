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
    if state.get("invalid_whoami"):
        print("not JSON")
        sys.exit(0)
    print(
        json.dumps({"identity": {"senderAddress": state.get("seat", "filing@tooling")}})
    )
elif args[:2] == ["queue", "show"]:
    if state.get("missing"):
        print(json.dumps({"error": "qitem_not_found"}))
        sys.exit(1)
    print(json.dumps(state.get("approval", {})))
elif args[:2] == ["queue", "update"]:
    if state.get("update_failure"):
        print(state["update_failure"], file=sys.stderr)
        sys.exit(1)
    print("updated")
else:
    print("unexpected rig command", args, file=sys.stderr)
    sys.exit(1)
