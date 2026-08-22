#!/usr/bin/env python3
"""PreToolUse gate: put the writing rules in front of me before I write a vault note.

The style rules are loaded every session, but "loaded" and "applied" are different
things, and the gap between them is where the slop gets written. This fires in the
moment that matters — immediately before a note is written or edited — and injects
the self-check as context.

It never blocks. Blocking a write over prose style would be obnoxious and would fire
on legitimate edits constantly. It reminds; the judgement stays with the model.

Scoped to the vault. Code, config and scratch files are not the problem this fixes,
and firing on every file edit would train me to ignore it.
"""

import json
import os
import re
import sys
from pathlib import Path

VAULT = Path(
    os.environ.get("SECOND_BRAIN", Path.home() / "Documents/Second_Brain")
).resolve()

# Files that are structure rather than prose — a reminder about sentence quality
# would just be noise on these.
SKIP_NAMES = {"README.md", "INDEX.md"}

# Rough signals that the content being written has slipped back into the compressed
# style. These are hints for the reminder, not a verdict — the note is injected
# either way, and these only sharpen it.
ARROW_CHAIN = re.compile(r"\S\s*(→|->)\s*\S.*(→|->)")
MIDDOT_LIST = re.compile(r"\S\s+·\s+\S")
BACKTICKED = re.compile(r"`[^`\n]+`")


def backtick_heavy(text: str) -> bool:
    """True if some line is mostly code identifiers with a little English holding
    them together, rather than English with a few identifiers in it.

    Measured as a ratio of the line, not as a prefix pattern. A realistic offending
    line starts with several ordinary words before the backticks begin, so anything
    anchored to the start of the line misses the case entirely.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) < 40:
            continue
        spans = BACKTICKED.findall(stripped)
        if len(spans) < 3:
            continue
        if sum(len(s) for s in spans) / len(stripped) > 0.45:
            return True
    return False


def content_of(tool_input: dict) -> str:
    for key in ("content", "new_string"):
        v = tool_input.get(key)
        if isinstance(v, str):
            return v
    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_input = payload.get("tool_input") or {}
    raw_path = tool_input.get("file_path") or ""
    if not raw_path:
        return 0

    try:
        path = Path(raw_path).resolve()
    except (OSError, ValueError):
        return 0

    if VAULT not in path.parents:
        return 0
    if path.suffix != ".md" or path.name in SKIP_NAMES:
        return 0
    if "_Templates" in path.parts:
        return 0

    body = content_of(tool_input)
    hits = []
    if ARROW_CHAIN.search(body):
        hits.append("arrow chains standing in for sentences")
    if MIDDOT_LIST.search(body):
        hits.append("middots doing the job of grammar")
    if backtick_heavy(body):
        hits.append("a line that is mostly backticks with a few English words")

    reminder = (
        "Writing a vault note. Before this lands, read it as if you had never seen "
        "it: complete sentences rather than fragments, every piece of jargon "
        "explained the first time, one idea per sentence, the reason before the "
        "detail, and backticks only around real code identifiers. If a sentence only "
        "makes sense because you already know what you meant, rewrite it. Full "
        "directive: 40_Reference/writing-and-teaching-directive.md."
    )
    if hits:
        reminder += (
            " Specifically, this draft appears to contain " + ", ".join(hits) + "."
        )

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "additionalContext": reminder,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
