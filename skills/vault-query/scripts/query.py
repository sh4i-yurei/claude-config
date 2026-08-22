#!/usr/bin/env python3
"""Answer questions about the vault from frontmatter, without reading every note.

A vault only pays for the discipline of consistent frontmatter if something reads
it back. This is that. It returns note paths and fields — never note bodies — so
the answer stays small and Claude can then read only what actually matters.

    query.py status                  overview: active work, open logs, inbox
    query.py projects [--status active]
    query.py buildlogs [--post candidate]
    query.py posts [--status drafted]
    query.py recent [--days 7]       notes touched recently
    query.py find <text>             filename/frontmatter match
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

VAULT = Path(os.environ.get("SECOND_BRAIN", Path.home() / "Documents/Second_Brain"))
SKIP = {"README.md", "INDEX.md"}


def notes() -> list[Path]:
    return [
        p
        for p in VAULT.rglob("*.md")
        # Skip every dot-directory, not just .obsidian. Since the skills and
        # hooks moved into the vault at .claude/, a check for one folder name
        # let SKILL.md files show up in "recent notes" as though they were notes.
        # They are tooling that lives beside the notes.
        if not any(part.startswith(".") for part in p.relative_to(VAULT).parts)
        and "_Templates" not in p.parts
        and p.name not in SKIP
    ]


def frontmatter(p: Path) -> dict[str, str]:
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out: dict[str, str] = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def rel(p: Path) -> str:
    return str(p.relative_to(VAULT))


def show(rows: list[tuple[str, str]], empty: str) -> None:
    if not rows:
        print(f"  ({empty})")
        return
    width = max(len(a) for a, _ in rows)
    for a, b in rows:
        print(f"  {a.ljust(width)}   {b}" if b else f"  {a}")


def collect(kind: str | None = None, **filters: str) -> list[tuple[Path, dict]]:
    out = []
    for p in sorted(notes()):
        fm = frontmatter(p)
        if kind and fm.get("type") != kind:
            continue
        if any(fm.get(k) != v for k, v in filters.items() if v):
            continue
        out.append((p, fm))
    return out


def cmd_status() -> None:
    print("Projects — active:")
    show([(p.stem, "") for p, _ in collect("project", status="active")], "none")
    print("Projects — paused:")
    show([(p.stem, "") for p, _ in collect("project", status="paused")], "none")
    print("Open buildlogs:")
    show([(p.parent.name, "") for p, _ in collect("buildlog", status="active")], "none")
    print("Worth writing up (post: candidate):")
    show(
        [(p.parent.name, "") for p, _ in collect("buildlog", post="candidate")], "none"
    )
    print("Inbox (unfiled):")
    inbox = [p for p in notes() if p.parent.name == "00_Inbox"]
    show([(p.stem, "") for p in sorted(inbox)], "empty")


def cmd_list(kind: str, **filters: str) -> None:
    rows = []
    for p, fm in collect(kind, **filters):
        bits = [
            f"{k}={fm[k]}" for k in ("status", "post", "genre", "project") if fm.get(k)
        ]
        rows.append((rel(p), "  ".join(bits)))
    show(rows, "none")


def cmd_recent(days: int) -> None:
    cutoff = subprocess.run(
        ["date", "-d", f"-{days} days", "+%s"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    rows = []
    for p in sorted(notes()):
        try:
            mt = int(p.stat().st_mtime)
        except OSError:
            continue
        if cutoff and mt >= int(cutoff):
            when = subprocess.run(
                ["date", "-d", f"@{mt}", "+%Y-%m-%d %H:%M"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            rows.append((rel(p), when))
    rows.sort(key=lambda r: r[1], reverse=True)
    show(rows, f"nothing touched in {days} days")


def cmd_find(needle: str) -> None:
    n = needle.lower()
    rows = []
    for p, fm in collect():
        hay = " ".join([p.stem, *(f"{k} {v}" for k, v in fm.items())]).lower()
        if n in hay:
            rows.append((rel(p), fm.get("type", "")))
    show(rows, f"no note matching '{needle}'")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    for name in ("projects", "buildlogs", "posts"):
        s = sub.add_parser(name)
        s.add_argument("--status", default="")
        s.add_argument("--post", default="")
    r = sub.add_parser("recent")
    r.add_argument("--days", type=int, default=7)
    f = sub.add_parser("find")
    f.add_argument("text")
    args = ap.parse_args()

    if not VAULT.is_dir():
        print(f"vault not found: {VAULT}", file=sys.stderr)
        return 1

    match args.cmd:
        case "status" | None:
            cmd_status()
        case "projects":
            cmd_list("project", status=args.status, post=args.post)
        case "buildlogs":
            cmd_list("buildlog", status=args.status, post=args.post)
        case "posts":
            cmd_list("post", status=args.status)
        case "recent":
            cmd_recent(args.days)
        case "find":
            cmd_find(args.text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
