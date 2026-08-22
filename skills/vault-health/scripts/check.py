#!/usr/bin/env python3
"""Check the Second Brain vault against its own conventions.

vault-inspector already covers the generic problems — broken links, orphan
attachments, duplicates, frontmatter type drift. It knows nothing about the rules
this vault actually runs on, which is what this checks: the naming that keeps
wikilinks unambiguous, the frontmatter the queries depend on, and the boundaries
that keep secrets and history out of the wrong notes.

Read-only. Reports, never edits — deciding what to do about a finding needs
judgement this script does not have.

    check.py [--vault PATH] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

VALID_TYPE = {"project", "buildlog", "buildlog-log", "post", "reference", "note",
              "journal"}
# "simmering" means real but never started; "paused" means started then stopped.
# Collapsing them is what let fourteen of twenty-two projects sit under "idea".
VALID_STATUS = {"idea", "active", "simmering", "paused", "done",
                "drafted", "published"}
VALID_POST = {"none", "candidate", "drafted", "published"}
VALID_GENRE = {"technical", "personal"}

# Properties each type must carry. Validating that a *value* is allowed is not the
# same as validating that the property *exists*: a project note with no `status` at
# all passed every check until 2026-08-22, because every rule only looked at values
# that were present. A missing property is invisible to a query, which makes the
# note invisible to every dashboard and every drift rule.
REQUIRED_PROPS = {
    "project": {"type", "status", "created"},
    "buildlog": {"type", "status", "created", "project"},
    "post": {"type", "status", "created"},
    "reference": {"type", "created"},
    "journal": {"type", "created"},
}

STALE_REFERENCE_DAYS = 180
STALE_INBOX_DAYS = 21

# The folders the vault is built from. Each belongs at the root and nowhere else.
TOP_LEVEL = [
    "00_Inbox",
    "10_Projects",
    "20_Buildlogs",
    "30_Posts",
    "40_Reference",
    "50_Personal",
    "60_Operational_Manual",
    "70_Research",
    "_Templates",
]

# Things that should never be pasted into a note. Deliberately narrow: the cost of
# a false positive here is a moment of doubt, the cost of a miss is a leaked key.
SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
    (re.compile(r"-----BEGIN CERTIFICATE-----"), "certificate block"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "GitHub token"),
    (re.compile(r"\bdop_v1_[a-f0-9]{32,}"), "DigitalOcean token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "API key"),
    (
        re.compile(
            r"(?i)^\s*(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{8,}"
        ),
        "credential assignment",
    ),
]


@dataclass
class Report:
    problems: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, severity: str, path: str, message: str) -> None:
        self.problems.append((severity, path, message))


def frontmatter(text: str) -> dict[str, str]:
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


def days_old(value: str) -> int | None:
    """Age in days of a YYYY-MM-DD string, via `date` so there's no clock drift."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return None
    try:
        then = subprocess.run(
            ["date", "-d", value, "+%s"], capture_output=True, text=True, check=False
        ).stdout.strip()
        now = subprocess.run(
            ["date", "+%s"], capture_output=True, text=True, check=False
        ).stdout.strip()
        return (int(now) - int(then)) // 86400
    except (ValueError, OSError):
        return None


def file_age_days(p: Path) -> int | None:
    """Age from mtime, for notes with no `created:` field to read (inbox items)."""
    try:
        mtime = int(p.stat().st_mtime)
    except OSError:
        return None
    now = subprocess.run(
        ["date", "+%s"], capture_output=True, text=True, check=False
    ).stdout.strip()
    try:
        return (int(now) - mtime) // 86400
    except ValueError:
        return None


def check(vault: Path) -> Report:
    r = Report()
    if not vault.is_dir():
        r.add("error", str(vault), "vault directory does not exist")
        return r

    # Skip every dot-directory, not just .obsidian. Since the skills moved into
    # the vault at .claude/skills, seven SKILL.md files were being read as notes:
    # they share a basename, so they tripped the duplicate-basename error, and
    # they carry Claude's own frontmatter rather than a vault `type:`. They are
    # tooling that lives beside the notes, not notes.
    notes = [
        p
        for p in vault.rglob("*.md")
        if not any(part.startswith(".") for part in p.relative_to(vault).parts)
    ]
    rel = lambda p: str(p.relative_to(vault))  # noqa: E731

    # --- top-level folders in the right place ---------------------------------
    # One accidental drag in Obsidian's file explorer can nest a whole top-level
    # folder inside another, and nothing complains: links still resolve by
    # basename, so the vault looks fine while its structure is quietly wrong.
    # Worth naming explicitly, because the symptom otherwise shows up as some
    # unrelated confusing message.
    for folder in TOP_LEVEL:
        expected = vault / folder
        if not expected.is_dir():
            r.add("error", folder, "expected top-level folder is missing")
        for found in vault.rglob(folder):
            if found.is_dir() and found != expected and ".obsidian" not in found.parts:
                r.add(
                    "error",
                    rel(found),
                    f"'{folder}' is a top-level folder but was found nested here — "
                    "probably dragged by accident; move it back to the vault root",
                )

    # --- basename collisions: wikilinks resolve on filename alone -------------
    # Compared lowercased, because Obsidian resolves links ignoring case: Pong.md
    # and pong.md are the same target to it, and a [[Pong]] link will silently
    # pick one of them. Comparing case-sensitively here misses that entirely.
    seen: dict[str, list[Path]] = {}
    for p in notes:
        if p.name in ("README.md", "INDEX.md"):
            continue
        seen.setdefault(p.name.lower(), []).append(p)
    for name, paths in seen.items():
        if len(paths) > 1:
            distinct = {p.name for p in paths}
            note = (
                " (they differ only by capitalisation, which Obsidian ignores)"
                if len(distinct) > 1
                else ""
            )
            r.add(
                "error",
                ", ".join(rel(p) for p in paths),
                f"{len(paths)} notes share the basename '{name}'{note} — "
                "[[wikilinks]] to it are ambiguous and may resolve to the wrong one",
            )

    # --- buildlog structure ---------------------------------------------------
    logs_dir = vault / "20_Buildlogs"
    if logs_dir.is_dir():
        for folder in sorted(p for p in logs_dir.iterdir() if p.is_dir()):
            slug = folder.name
            if (folder / "log.md").exists() or (folder / "outline.md").exists():
                r.add(
                    "error",
                    rel(folder),
                    "buildlog uses bare log.md/outline.md — rename to "
                    f"{slug}-log.md / {slug}-outline.md so links stay unambiguous",
                )
            if not (folder / f"{slug}-log.md").exists():
                r.add(
                    "warning", rel(folder), f"no {slug}-log.md — buildlog has no record"
                )

    # --- per-note checks ------------------------------------------------------
    for p in notes:
        name = p.name
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            r.add("warning", rel(p), "could not read file")
            continue

        for pattern, label in SECRET_PATTERNS:
            if pattern.search(text):
                r.add(
                    "error",
                    rel(p),
                    f"looks like a {label} pasted into a note — "
                    "reference the lockbox path instead of the value",
                )
                break

        if name in ("README.md", "INDEX.md") or "_Templates" in p.parts:
            continue

        in_inbox = p.parent.name == "00_Inbox"

        fm = frontmatter(text)
        if not fm:
            # The inbox is exempt on purpose. Its README promises frontmatter is
            # optional there, because requiring a schema at the moment of capture is
            # friction in the one place friction cannot exist. A checker that nags
            # for following the documented rule is how people stop running it.
            if not in_inbox:
                r.add("warning", rel(p), "no frontmatter — invisible to queries")
            else:
                age = file_age_days(p)
                if age is not None and age > STALE_INBOX_DAYS:
                    r.add(
                        "warning",
                        rel(p),
                        f"sitting in the inbox for {age} days — file it or drop it",
                    )
            continue

        if "title" in fm:
            r.add(
                "warning",
                rel(p),
                "has a title: field — the filename is the note's identity, "
                "a second copy only drifts",
            )

        t = fm.get("type", "")
        if not t:
            r.add("warning", rel(p), "frontmatter has no type:")
        elif t not in VALID_TYPE:
            r.add("warning", rel(p), f"unknown type: '{t}'")
        if t in REQUIRED_PROPS:
            missing = sorted(REQUIRED_PROPS[t] - set(fm))
            if missing:
                r.add(
                    "warning",
                    rel(p),
                    f"type={t} is missing required "
                    f"{'property' if len(missing) == 1 else 'properties'}: "
                    + ", ".join(missing),
                )

        for key, valid in (
            ("status", VALID_STATUS),
            ("post", VALID_POST),
            ("genre", VALID_GENRE),
        ):
            val = fm.get(key)
            if val and val not in valid:
                r.add(
                    "warning", rel(p), f"{key}: '{val}' is not one of {sorted(valid)}"
                )

        if t == "reference":
            upd = fm.get("updated", "")
            age = days_old(upd) if upd else None
            if not upd:
                r.add("warning", rel(p), "reference note has no updated: field")
            elif age is not None and age > STALE_REFERENCE_DAYS:
                r.add(
                    "warning",
                    rel(p),
                    f"reference note not updated in {age} days — "
                    "a stale reference is worse than a missing one",
                )

        if p.parent.name == "00_Inbox":
            age = days_old(fm.get("created", ""))
            if age is not None and age > STALE_INBOX_DAYS:
                r.add(
                    "warning",
                    rel(p),
                    f"sitting in the inbox for {age} days — file it or drop it",
                )

    return r




WIKILINK = re.compile(r"(?<!!)\[\[([^\]|#^]+)")
EMBED = re.compile(r"!\[\[([^\]|#^]+)")


def strip_link_noise(body: str) -> str:
    """Remove everything that looks like a link but is not one.

    Three sources, all of which produced false positives when this was first
    written as a separate script — thirty-one of them on the first run:

      %% ... %%    Obsidian comments, holding template guidance full of examples
      ``` ... ```  fenced code, e.g. the YAML schema block in INDEX.md showing
                   project: "[[Project Note Name]]"
      ` ... `      inline code, e.g. README prose explaining that Obsidian
                   resolves wikilinks on basename

    All three are documentation *about* links rather than links, and Obsidian
    does not resolve them either. A check that cries wolf is worse than no
    check, because it trains you to skim past the output.
    """
    body = re.sub(r"%%.*?%%", "", body, flags=re.S)
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    body = re.sub(r"`[^`\n]*`", "", body)
    return body


def check_links(vault: Path, report: Report) -> None:
    """Every wikilink resolves to a real file.

    Duplicates what `npx vault-inspector` does, deliberately. That tool is
    richer — orphan attachments, duplicate files by hash, oversized files — but
    it needs npm and a network. This needs neither, so the same check runs on a
    CI runner and in a pre-commit hook. Locally `obsidian unresolved` is cheaper
    still, but Obsidian is not running on a GitHub Actions box.
    """
    names: set[str] = set()
    paths: set[str] = set()
    for f in vault.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(vault)
        if any(part.startswith(".") for part in rel.parts):
            continue
        # Both forms: notes are linked without an extension ([[my-note]]) while
        # attachments are linked with one ([[diagram.png]]).
        names.add(f.stem)
        names.add(f.name)
        paths.add(str(rel.with_suffix("")))
        paths.add(str(rel))

    for f in vault.rglob("*.md"):
        rel = f.relative_to(vault)
        if any(part.startswith(".") or part == "_Templates" for part in rel.parts):
            continue
        body = strip_link_noise(f.read_text(encoding="utf-8", errors="replace"))
        for m in list(WIKILINK.finditer(body)) + list(EMBED.finditer(body)):
            target = m.group(1).strip()
            if not target or target.startswith(("http", "/")):
                continue
            if target not in names and target not in paths:
                report.add("error", str(rel), f"unresolved link [[{target}]]")


def check_drift(vault: Path, report: Report) -> None:
    """Documentation disagreeing with what actually happened.

    Not staleness. Staleness is a property of one note and needs an arbitrary
    "N days" threshold; a correct note nobody edited for six months is fine.
    Drift is a *gap between two things* — work happened here, the record over
    there did not follow — so it needs no threshold at all.

    Every rule below was written against a real failure found in this vault on
    2026-08-22, and verified by running it against the commit before those
    failures were corrected by hand.
    """
    projects: dict[str, tuple[Path, dict[str, str]]] = {}
    buildlogs: list[tuple[Path, dict[str, str], str]] = []
    post_names: set[str] = set()

    for path in vault.rglob("*.md"):
        rel = path.relative_to(vault)
        if any(part.startswith(".") or part == "_Templates" for part in rel.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        props = frontmatter(text)
        kind = props.get("type")
        if kind == "project":
            projects[path.stem] = (rel, props)
        elif kind == "buildlog":
            buildlogs.append((rel, props, text))
        elif kind == "post":
            post_names.add(path.stem)

    # 1. Every box ticked, but the status never followed.
    #    Caught: Contact form backend, 16 done / 0 open, still status=active.
    for rel, props in projects.values():
        if props.get("status") == "done":
            continue
        full = vault / rel
        body = full.read_text(encoding="utf-8", errors="replace")
        done = len(re.findall(r"^[ \t]*-[ \t]*\[x\]", body, re.M))
        todo = len(re.findall(r"^[ \t]*-[ \t]*\[ \]", body, re.M))
        if done and not todo:
            report.add("warning", str(rel),
                       f"all {done} tasks are ticked but status is "
                       f"'{props.get('status')}'")

    for rel, props, _ in buildlogs:
        slug = rel.parent.name
        project = props.get("project", "").strip('"').strip("[]")
        status = props.get("status")

        # 2. The post shipped, but the buildlog never closed.
        #    Caught: contact-form, post published, buildlog still active.
        if slug in post_names and status == "active":
            report.add("warning", str(rel),
                       f"post '{slug}' exists but this buildlog is still active")

        if project in projects:
            pstatus = projects[project][1].get("status")

            # 3. A buildlog exists for a project claiming to be unstarted.
            #    Caught: CI-CD pipeline — which rules 1 and 2 both missed, since
            #    it had no ticked boxes and no post yet. Its only tell was a
            #    contradiction in kind rather than in dates: you do not keep a
            #    buildlog for something you have not started. It was also the
            #    most dangerous, because a project claiming 'idea' while running
            #    three required CI checks is exactly the note that makes an
            #    assistant propose building what already exists.
            if pstatus == "idea":
                report.add("warning", str(rel),
                           f"buildlog exists but [[{project}]] is status 'idea'")

            # 4. The project finished and the buildlog stayed open.
            #    Caught: ci-cd-pipeline, still active after its project was
            #    archived. Found by the convention checker flagging an invented
            #    status value, not by any drift rule — which is why both halves
            #    of this script earn their place.
            if pstatus == "done" and status == "active":
                report.add("warning", str(rel),
                           f"[[{project}]] is done but this buildlog is still active")



def check_index_coverage(vault: Path, report: Report) -> None:
    """The operational manual's contents page lists every procedure in it.

    Added 2026-08-22 after an audit found the manual held 34 procedures while its
    index listed 33: `github-issue-and-pr-workflow` was moved in and the contents
    page was never updated. Nothing complained, because an index that is merely
    incomplete still renders perfectly.

    This is drift between a folder and the note that claims to describe it, which
    is a different shape from the note-to-note rules above and needs its own check.
    An index nobody can trust to be complete is worse than no index, because you
    stop checking whether the thing you need is missing or simply not there.
    """
    manual = vault / "60_Operational_Manual"
    index = manual / "operational-checklists-index.md"
    if not index.is_file():
        return

    linked = set(re.findall(r"\[\[([^\]|#^]+)", index.read_text(encoding="utf-8")))
    linked = {x.strip() for x in linked}

    for p in sorted(manual.rglob("*.md")):
        if p.name in ("README.md", index.name):
            continue
        if p.stem not in linked:
            report.add(
                "warning",
                str(p.relative_to(vault)),
                "procedure is not listed in operational-checklists-index",
            )



def check_skills_map(vault: Path, report: Report) -> None:
    """INDEX.md's skills table matches the skills that actually exist.

    Same shape as the manual's index-coverage check: a note that claims to
    describe a folder, drifting from the folder. Added 2026-08-22 after a wiring
    pass found two skills — `write-post` and `teaching` — described nowhere
    outside their own files, and no single place listing all of them.

    Both directions matter. A skill missing from the table is undiscoverable, and
    a table entry with no skill behind it sends a reader looking for something
    that is not there — which is worse, because they will assume they are wrong
    rather than the index.
    """
    index = vault / "INDEX.md"
    skills_dir = vault / ".claude" / "skills"
    if not index.is_file() or not skills_dir.is_dir():
        return

    # Match the full range of legal directory names, not just the ones that happen
    # to exist today. The narrower [a-z][a-z-]* would silently skip any skill with
    # a digit or underscore in its name — the same bug fault injection found in
    # check_own_docs, which is why both were widened together.
    listed = set(
        re.findall(r"^\| `([a-z][a-z0-9_-]*)` \|", index.read_text(encoding="utf-8"), re.M)
    )
    if not listed:
        return  # no skills table in this vault; nothing to check against

    actual = {d.name for d in skills_dir.iterdir() if (d / "SKILL.md").is_file()}

    for name in sorted(actual - listed):
        report.add("warning", ".claude/skills/" + name,
                   "skill exists but is not in INDEX.md's skills table")
    for name in sorted(listed - actual):
        report.add("warning", "INDEX.md",
                   f"skills table lists '{name}' but no such skill exists")


def check_folder_readmes(vault: Path, report: Report) -> None:
    """A folder README that lists its contents actually lists all of them.

    Applies to any README containing a "Holds:" or "Currently:" line. Those lists
    are the fastest thing in the vault to go stale — `69_Homelab/README.md` was
    wrong within twenty minutes of a procedure landing in it, on 2026-08-22.

    This rule only became possible once those lists used wikilinks. As prose
    ("node provisioning") it would have needed fuzzy matching against a filename
    (`homelab-node-provisioning.md`), and fuzzy matching is how a check starts
    producing findings nobody acts on. Aliased links — `[[target|display text]]` —
    read exactly like the prose did and match exactly, so the check is reliable
    without the README getting uglier.
    """
    for readme in sorted(vault.rglob("README.md")):
        rel = readme.relative_to(vault)
        if any(part.startswith(".") for part in rel.parts):
            continue
        text = readme.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"^(Holds|Currently):", text, re.M):
            continue
        linked = {x.split("|")[0].strip()
                  for x in re.findall(r"\[\[([^\]]+)\]\]", text)}
        for note in sorted(readme.parent.glob("*.md")):
            if note.name == "README.md":
                continue
            if note.stem not in linked:
                report.add("warning", str(note.relative_to(vault)),
                           f"not listed in {rel.parent}/README.md")


def check_own_docs(vault: Path, report: Report) -> None:
    """This script's own SKILL.md lists every rule this script implements.

    Added 2026-08-22 after doing the same thing three times in one day: changing
    the tool and leaving its documentation behind. The first instance was writing
    a drift detector and, an hour later, having its SKILL.md still describe a
    two-checker workflow that no longer existed.

    None of the other rules could see it. They all compare notes to notes, or a
    note to a folder. Nothing compared code to the prose describing the code, so
    the tooling was the one part of the vault with no drift detection at all —
    which is a poor place for a blind spot, since everything else depends on it.

    Self-referential on purpose: the checker is the only thing positioned to
    notice that the checker has drifted.
    """
    src = Path(__file__).resolve()
    skill = src.parent.parent / "SKILL.md"
    if not skill.is_file():
        return

    # [a-z0-9_] rather than [a-z_]: the first version silently skipped any
    # function name containing a digit, which fault injection caught only
    # because the dummy rule happened to be called check_z6.
    implemented = set(
        re.findall(r"^def (check_[a-z0-9_]+)\(", src.read_text(encoding="utf-8"), re.M)
    )
    documented = skill.read_text(encoding="utf-8")
    for fn in sorted(implemented - {"check_own_docs"}):
        if fn not in documented:
            report.add("warning", str(skill.relative_to(vault)),
                       f"does not document the rule implemented by {fn}()")


def check_archive_leaks(vault: Path, report: Report) -> None:
    """Dashboard queries that read a folder do not silently include its archive.

    Added 2026-08-22 after this bit three times in one day. Creating an archive
    subfolder does not break a query that reads the parent — Dataview's
    `FROM "folder"` recurses, so the query keeps running and keeps looking healthy
    while quietly widening to include finished work.

    Instances: the manual moving out of 40_Reference narrowed a staleness query
    from 42 notes to 4; creating 00_Inbox/09_Archive made the inbox list show
    archived items; and "What's next" pulled open tasks out of two archived
    projects for hours before anyone noticed.

    A query is considered safe if it either excludes the archive path explicitly
    or filters on `status`, since archived notes carry `status: done`.
    """
    dash = vault / "Dashboard.md"
    if not dash.is_file():
        return

    archived_parents = {
        d.parent.relative_to(vault).as_posix(): d.relative_to(vault).as_posix()
        for d in vault.rglob("*_Archive")
        if d.is_dir() and not any(x.startswith(".") for x in d.parts)
    }
    if not archived_parents:
        return

    text = dash.read_text(encoding="utf-8")
    for heading, query in re.findall(
        r"##\s*(.+?)\n.*?```dataview\n(.*?)```", text, re.S
    ):
        flat = " ".join(query.split())
        for parent, archive in archived_parents.items():
            if f'"{parent}"' not in flat:
                continue
            if f'!"{archive}"' in flat or "status" in flat:
                continue
            report.add(
                "warning",
                "Dashboard.md",
                f"query '{heading.strip()}' reads {parent} without excluding "
                f"{archive} or filtering on status",
            )

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--vault",
        default=os.environ.get(
            "SECOND_BRAIN", str(Path.home() / "Documents/Second_Brain")
        ),
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser()
    rep = check(vault)
    check_links(vault, rep)
    check_drift(vault, rep)
    check_index_coverage(vault, rep)
    check_skills_map(vault, rep)
    check_folder_readmes(vault, rep)
    check_archive_leaks(vault, rep)
    check_own_docs(vault, rep)

    if args.json:
        print(
            json.dumps(
                [{"severity": s, "path": p, "message": m} for s, p, m in rep.problems],
                indent=2,
            )
        )
        return 0

    errors = [x for x in rep.problems if x[0] == "error"]
    warns = [x for x in rep.problems if x[0] == "warning"]
    if not rep.problems:
        print("Convention check: clean.")
        return 0
    for label, items in (("ERROR", errors), ("WARN", warns)):
        for _, path, msg in items:
            print(f"[{label}] {path}\n         {msg}")
    print(f"\n{len(errors)} error(s), {len(warns)} warning(s).")
    # Errors are broken conventions and must block. Warnings are advisory:
    # drift is worth surfacing every time without making it impossible to
    # commit work in progress.
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
