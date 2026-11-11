"""Name an interactive Claude session after its herdr workspace."""

import json
import os
import re
import shutil
import subprocess
import sys


def herdr(args):
    try:
        result = subprocess.run(
            ["herdr", *args], text=True, capture_output=True, timeout=5
        )
        answer = json.loads(result.stdout) if result.returncode == 0 else None
        return answer if isinstance(answer, dict) else None
    except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeError):
        return None


def main():
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT") != "cli":
        return 0
    pane = os.environ.get("HERDR_PANE_ID")
    workspace = os.environ.get("HERDR_WORKSPACE_ID")
    if not pane or not workspace or shutil.which("herdr") is None:
        return 0
    try:
        json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    answer = herdr(["workspace", "list"])
    if not isinstance(answer, dict):
        return 0
    result = answer.get("result")
    if not isinstance(result, dict):
        return 0
    entries = result.get("workspaces")
    if not isinstance(entries, list):
        return 0
    label = next(
        (
            item.get("label")
            for item in entries
            if isinstance(item, dict) and item.get("workspace_id") == workspace
        ),
        None,
    )
    if not isinstance(label, str):
        return 0
    name = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    if not name:
        return 0
    if herdr(["agent", "rename", pane, name]) is not None:
        print(f"This session's herdr name is {name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
