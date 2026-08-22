#!/usr/bin/env python3
"""Stop hook: nudge Claude to write the buildlog before the session ends.

Fires when Claude finishes responding. If the session did real work and no
buildlog entry has been written yet, it blocks once with a reason — which Claude
receives and acts on. Blocks at most once per session, so there is no loop.

Deliberately quiet: a short chat, a question, or a session that already logged
gets no interruption at all. A hook that fires on everything is one you learn to
ignore.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

VAULT = Path(os.environ.get("SECOND_BRAIN", Path.home() / "Documents/Second_Brain"))
BUILDLOGS = VAULT / "20_Buildlogs"
STATE = Path.home() / ".claude" / "state" / "buildlog-stop"

# Below this many tool calls, the session was a conversation, not work worth logging.
WORK_THRESHOLD = 12


def already_fired(session_id: str) -> bool:
    """Has this session already been nudged?"""
    return (STATE / f"{session_id}.fired").exists()


def mark_fired(session_id: str) -> None:
    """Record the nudge. Called only when actually blocking, never before.

    Marking on entry would burn the session's single nudge on an early Stop —
    when little work has happened yet and we correctly decide not to block —
    leaving nothing to fire later once the work has piled up.
    """
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / f"{session_id}.fired").touch()


def tool_call_count(transcript_path: str) -> int:
    """Rough measure of whether anything actually happened this session."""
    try:
        count = 0
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                if '"type":"tool_use"' in line or '"tool_use"' in line:
                    count += 1
        return count
    except (OSError, UnicodeDecodeError):
        return 0


def logged_today() -> bool:
    """True if any buildlog was written to today — then we've already captured."""
    if not BUILDLOGS.is_dir():
        return False
    today = subprocess.run(
        ["date", "+%Y-%m-%d"], capture_output=True, text=True, check=False
    ).stdout.strip()
    for log in BUILDLOGS.glob("*/*-log.md"):
        try:
            mtime = subprocess.run(
                ["date", "-r", str(log), "+%Y-%m-%d"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if mtime == today:
                return True
        except OSError:
            continue
    return False


def open_buildlogs() -> list[str]:
    """Buildlogs whose outline still says status: active."""
    out = []
    if not BUILDLOGS.is_dir():
        return out
    for outline in sorted(BUILDLOGS.glob("*/*-outline.md")):
        try:
            head = outline.read_text(encoding="utf-8")[:400]
            if "status: active" in head:
                out.append(outline.parent.name)
        except OSError:
            continue
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # Malformed input is not a reason to interrupt the user.

    session_id = payload.get("session_id", "")
    transcript = payload.get("transcript_path", "")

    if not session_id or already_fired(session_id):
        return 0
    if tool_call_count(transcript) < WORK_THRESHOLD:
        return 0
    if logged_today():
        return 0

    active = open_buildlogs()
    if active:
        where = "Open buildlogs: " + ", ".join(active) + "."
    else:
        where = (
            "No buildlog is open. If this session was substantial, scaffold one with "
            '~/.claude/skills/buildlog/scripts/new-buildlog.sh <slug> "<Project>".'
        )

    # If this session was compacted, the raw commands and output were checkpointed
    # to disk before the summariser ate them. Point at it — that file is often the
    # only surviving copy of the exact text an entry needs.
    checkpoint = ""
    pointer = Path.home() / ".claude" / "state" / "precompact" / f"{session_id}.latest"
    if pointer.is_file():
        try:
            path = pointer.read_text(encoding="utf-8").strip()
            if path and Path(path).is_file():
                checkpoint = (
                    f" This session was compacted; the raw commands and output were "
                    f"saved to {path} — read it, the detail is not in context anymore."
                )
        except OSError:
            pass

    reason = (
        "This session did real work and nothing was written to a buildlog. "
        f"{where} Use the buildlog skill: write the entries now, while the transcript "
        "still holds the actual error text and command output — that detail is what "
        "the eventual post is made of, and it is gone once this session is. "
        "Saw / Cause / Fix, plus any [life] entries Mark mentioned."
        f"{checkpoint} "
        "If the work genuinely was not worth logging, say so in one line and stop."
    )

    mark_fired(session_id)
    # Blocking a Stop is done with exit 2 and the reason on stderr — that is what
    # reaches Claude as context. A JSON {"decision": "block"} payload is the shape
    # other hook events use and is silently ignored here, which makes the hook look
    # like it works while doing nothing at all.
    print(reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
