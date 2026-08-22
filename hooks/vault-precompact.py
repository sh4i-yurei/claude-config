#!/usr/bin/env python3
"""PreCompact hook: save the raw material before compaction destroys it.

Compaction summarises the transcript to reclaim context. Summaries keep what
happened and drop how it looked — the exact stderr, the exact command, the exact
wrong output. That detail is the entire substance of a buildlog entry and the
reason Mark's posts are readable, so losing it silently is the worst failure this
system can have.

PreCompact cannot inject context, so this does not try to nag. It checkpoints:
extracts commands, errors and outputs from the transcript to a file on disk that
outlives the compaction, and leaves a pointer the Stop hook can surface.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

STATE = Path.home() / ".claude" / "state" / "precompact"
MAX_ITEMS = 400  # Plenty for one compaction window; keeps the dump readable.

# Lines worth keeping: things that look like failure or like a command.
SIGNAL = re.compile(
    r"(error|errno|exception|traceback|failed|failure|denied|refused|timeout|"
    r"not found|no such file|cannot|unable to|fatal|warning|\bE:\s|non-zero|"
    r"exit code|status [1-9])",
    re.IGNORECASE,
)


def now() -> str:
    return subprocess.run(
        ["date", "+%Y-%m-%d %H:%M %Z"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "TZ": "America/Chicago"},
    ).stdout.strip()


def stamp() -> str:
    return subprocess.run(
        ["date", "+%Y%m%d-%H%M%S"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "TZ": "America/Chicago"},
    ).stdout.strip()


RESULT_LINES = 6  # Enough to show what a command actually returned.


def harvest(transcript: Path) -> list[str]:
    """Pull command/output pairs and error text out of the transcript.

    Pairing a command with whatever came back next is the important part. Filtering
    for error-shaped text alone misses the most valuable case: the command that
    succeeded and returned the wrong thing. `curl` printing `max-age=300` after a
    reload that exited clean contains no error keywords at all, and it is exactly
    the symptom the eventual post is built on.
    """
    items: list[str] = []
    pending_cmd = False
    try:
        with transcript.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                for kind, text in walk(rec):
                    if kind == "cmd":
                        items.append("$ " + text)
                        pending_cmd = True
                    elif kind == "result":
                        # Keep the result if it follows a command (the pairing) or
                        # looks like a failure on its own.
                        if pending_cmd or SIGNAL.search(text):
                            for ln in text.splitlines()[:RESULT_LINES]:
                                if ln.strip():
                                    items.append("  " + ln.strip()[:300])
                        pending_cmd = False
                    if len(items) >= MAX_ITEMS:
                        return items
    except (OSError, UnicodeDecodeError):
        return items
    return items


def walk(obj) -> list[tuple[str, str]]:
    """Yield ("cmd", text) and ("result", text) in the order they appear."""
    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        if obj.get("type") == "tool_use":
            cmd = (obj.get("input") or {}).get("command")
            if isinstance(cmd, str) and cmd.strip():
                found.append(("cmd", cmd.strip().splitlines()[0][:300]))
        if obj.get("type") == "tool_result":
            content = obj.get("content")
            if isinstance(content, str) and content.strip():
                found.append(("result", content))
        for k, v in obj.items():
            if k != "input":  # already handled; avoids re-walking command args
                found.extend(walk(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(walk(v))
    return found


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # Never block compaction over a parse problem.

    transcript = payload.get("transcript_path", "")
    session_id = payload.get("session_id", "unknown")
    # The field is compaction_trigger ("manual" | "auto"); `trigger` does not exist.
    trigger = payload.get("compaction_trigger", payload.get("trigger", "unknown"))
    if not transcript or not Path(transcript).is_file():
        return 0

    items = harvest(Path(transcript))
    if not items:
        return 0

    STATE.mkdir(parents=True, exist_ok=True)
    out = STATE / f"{session_id}-{stamp()}.md"
    out.write_text(
        f"# Pre-compaction checkpoint — {now()}\n\n"
        f"Session `{session_id}`, compaction trigger: {trigger}.\n\n"
        "Commands and error output harvested before the transcript was "
        "summarised. Use this when writing buildlog entries for this session — "
        "the exact text below is what compaction would otherwise have lost.\n\n"
        "```\n" + "\n".join(items) + "\n```\n",
        encoding="utf-8",
    )

    # Pointer file so the Stop hook can mention this without rescanning.
    (STATE / f"{session_id}.latest").write_text(str(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
