#!/usr/bin/env python3
"""SessionStart hook: put the current state of the vault into context.

Anything printed to stdout is injected into Claude's context at session start.
That makes this the cheapest possible orientation: instead of rediscovering what
is in flight by reading a dozen notes, the session opens already knowing.

Kept deliberately short. This runs on every session and competes for context with
actual work, so it reports counts and names, never content.
"""

import os
import re
import sys
from pathlib import Path

VAULT = Path(os.environ.get("SECOND_BRAIN", Path.home() / "Documents/Second_Brain"))
MAX_LISTED = 8  # Beyond this, a list stops being orienting and starts being noise.


def frontmatter(path: Path) -> dict[str, str]:
    """Parse the leading --- block. Good enough for flat scalar fields."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def notes(folder: str, pattern: str = "*.md") -> list[Path]:
    """Notes in a folder, searched recursively.

    Recursive on purpose. This used a flat glob until 2026-08-22, when projects
    moved into domain subfolders and the hook silently stopped reporting active
    projects — no error, just an empty list where seven projects used to be.

    That failure is the exact one this vault's drift checks exist to catch, and
    it landed in the tooling that briefs Claude at session start. The narrowest
    possible blast radius for a stale note is one wrong answer; the blast radius
    for a broken session brief is every answer in the session.
    """
    d = VAULT / folder
    if not d.is_dir():
        return []
    return [p for p in sorted(d.rglob(pattern)) if p.name != "README.md"]


def main() -> int:
    if not VAULT.is_dir():
        return 0  # No vault, nothing to say. Never fail a session start.

    lines: list[str] = []

    active, paused = [], []
    for p in notes("10_Projects"):
        status = frontmatter(p).get("status", "")
        if status == "active":
            active.append(p.stem)
        elif status == "paused":
            paused.append(p.stem)

    open_logs, candidates = [], []
    for outline in sorted((VAULT / "20_Buildlogs").glob("*/*-outline.md")):
        fm = frontmatter(outline)
        if fm.get("status") == "active":
            open_logs.append(outline.parent.name)
        if fm.get("post") == "candidate":
            candidates.append(outline.parent.name)

    inbox = [p.stem for p in notes("00_Inbox")]

    def fmt(label: str, items: list[str]) -> None:
        if not items:
            return
        shown = ", ".join(items[:MAX_LISTED])
        more = f" (+{len(items) - MAX_LISTED} more)" if len(items) > MAX_LISTED else ""
        lines.append(f"- {label}: {shown}{more}")

    fmt("Active projects", active)
    fmt("Paused", paused)
    fmt("Open buildlogs", open_logs)
    fmt("Marked post: candidate", candidates)
    fmt("Inbox (unfiled)", inbox)

    if not lines:
        return 0

    print("Second Brain vault state (~/Documents/Second_Brain):")
    print("\n".join(lines))
    print(
        "Read the project note before proposing work on it — it holds decisions "
        "already made. Full schema is in the vault's INDEX.md and folder READMEs."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
