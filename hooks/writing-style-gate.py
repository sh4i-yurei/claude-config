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

Once per note per session. The full reminder goes in front of the first edit of a
note in a session; later edits of that note get only the targeted hints, when the
draft matches one. The notes already reminded about are kept in a per-session record
under $XDG_RUNTIME_DIR/writing-style-gate/, one resolved path per line, so a new
session starts fresh and a reboot clears it. When that record can't be used, the
gate gives the full reminder every time, because a missing reminder costs more than
a repeated one.
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

# The per-session record lives in this folder under XDG_RUNTIME_DIR, in a file named
# by the session's id. Only ids made of these characters can name a file there.
RECORD_FOLDER = "writing-style-gate"
SESSION_ID = re.compile(r"[A-Za-z0-9_-]+")


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


def record_path(session_id: object) -> str | None:
    """Where this session's record lives, or None when it can't be used.

    XDG_RUNTIME_DIR must be an absolute path to an existing folder, and the session's
    id must be safe as a file name. Nothing is created here.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime or not os.path.isabs(runtime) or not os.path.isdir(runtime):
        return None
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        return None
    return os.path.join(runtime, RECORD_FOLDER, session_id)


def read_record(record: str) -> set[str] | None:
    """The notes this session has been reminded about, or None when the record can't
    be read. A missing folder or file means an empty record."""
    folder = os.path.dirname(record)
    if not os.path.lexists(folder):
        return set()
    if os.path.islink(folder) or not os.path.isdir(folder):
        return None
    try:
        fd = os.open(record, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return set()
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as handle:
            return set(handle.read().decode("utf-8").split("\n"))
    except (OSError, ValueError):
        return None


def append_record(record: str, note: str) -> None:
    """Add one note to the record, creating the folder with mode 0700 when nothing is
    at its path. Raises OSError or ValueError when it can't."""
    line = (note + "\n").encode("utf-8")
    folder = os.path.dirname(record)
    if not os.path.lexists(folder):
        os.makedirs(folder, mode=0o700)
        # The umask masks makedirs' mode, so set it outright.
        os.chmod(folder, 0o700)
    fd = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def reminded_before(session_id: object, note: str) -> bool:
    """True when this session's record already lists the note. Otherwise record the
    note, when the record can be used, and return False."""
    record = record_path(session_id)
    if record is None or "\n" in note:
        return False
    seen = read_record(record)
    if seen is None:
        return False
    if note in seen:
        return True
    try:
        append_record(record, note)
    except (OSError, ValueError):
        pass
    return False


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

    decision = {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
    if not reminded_before(payload.get("session_id"), str(path)):
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
        decision["additionalContext"] = reminder
    elif hits:
        decision["additionalContext"] = (
            "Writing a vault note: this draft appears to contain "
            + ", ".join(hits)
            + ". Full directive: 40_Reference/writing-and-teaching-directive.md."
        )

    print(json.dumps({"hookSpecificOutput": decision}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
