#!/usr/bin/env python3
"""PostToolUse hook: run Vale on a blog post the moment it is written or edited.

The writing directive and the humanizer skill change how I write. This checks what
actually landed on disk, with a program that does not get tired or persuaded. It only
knows vocabulary and sentence shapes, so it will not catch a moral-of-the-story
closer, but it will catch "leverage", "a single", "The catch is that" and a semicolon
every time.

It never blocks. The findings are printed so they land in context as feedback, and
the judgement about which ones to act on stays with me. Scoped to 30_Posts because
that is the only folder whose contents are meant for strangers.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

VAULT = Path(
    os.environ.get("SECOND_BRAIN", Path.home() / "Documents/Second_Brain")
).resolve()
POSTS = VAULT / "30_Posts"
MAX_LINES = 40


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    raw = (payload.get("tool_input") or {}).get("file_path")
    if not raw:
        return 0
    path = Path(raw).resolve()
    if path.suffix != ".md" or POSTS not in path.parents or path.name == "README.md":
        return 0

    vale = shutil.which("vale") or str(Path.home() / ".local/bin/vale")
    if not Path(vale).exists():
        print("vale-post-lint: vale is not installed, skipping.")
        return 0

    # Vale matches its [30_Posts/*.md] section against the path as given, so it has
    # to be relative to the vault or no rules apply and it reports nothing.
    result = subprocess.run(
        [vale, "--output=line", "--no-exit", str(path.relative_to(VAULT))],
        cwd=VAULT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        print(f"Vale: no findings in {path.relative_to(VAULT)}.")
        return 0

    shown = lines[:MAX_LINES]
    print(
        f"Vale found {len(lines)} thing(s) in {path.relative_to(VAULT)}. "
        "Each is a suggestion, not a verdict; fix the ones that are real."
    )
    for ln in shown:
        # Drop the file path prefix; the line:col and the rule are what matter.
        rel = ln.split(":", 1)[1] if ":" in ln else ln
        print("  " + rel)
    if len(lines) > MAX_LINES:
        print(
            f"  ... and {len(lines) - MAX_LINES} more. Run `vale {path.relative_to(VAULT)}` for all of them."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
