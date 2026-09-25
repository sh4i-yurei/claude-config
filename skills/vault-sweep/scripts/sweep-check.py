#!/usr/bin/env python3
"""One aggregated check for the vault sweep.

Prints every finding the sweep still has to fix, grouped by priority, and exits 1
while anything remains. When it prints nothing and exits 0, one pass is clean and
the sweep loop is allowed to stop. Nothing here fixes anything.

Six sections, highest priority first:

  correctness  everything vault-health's check.py reports (run as a subprocess)
  drift        status and folder disagree, or a buildlog and its post disagree
  manual       a command in the operational manual that runs as the wrong user,
               or describes a deploy path that no longer exists
  scaffold     template scaffolding left in a real note, empty sections
  style        the writing-style gate's heuristics and Vale, over every prose note
  ledger       notes that have not had their full writing-directive review, or
               changed since they had it

The ledger lives in the vault at .sweep-ledger.json and maps a note's path
to the sha256 of its content when it was reviewed. `--mark PATH...` records a
review; a note changed afterwards drops out of the ledger on its own because the
hash no longer matches.

Usage:
  sweep-check.py                 full report
  sweep-check.py --summary       counts per section only
  sweep-check.py --section style only one section
  sweep-check.py --limit 20      at most N findings per section
  sweep-check.py --mark A.md B.md   record a completed review, then exit
  sweep-check.py --no-vale       skip Vale (it is the slow part)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("SECOND_BRAIN", Path.home() / "Documents/Second_Brain")).resolve()
HEALTH = VAULT / ".github/scripts/check.py"
GATE = Path.home() / ".claude/hooks/writing-style-gate.py"
LEDGER = VAULT / ".sweep-ledger.json"
# The Vale config lives in this repository: scripts/ -> vault-sweep/ -> skills/ -> the
# repository root -> vale/. resolve() follows the ~/.claude/skills link to find it.
VALE_INI = Path(__file__).resolve().parents[3] / "vale" / "vale-sweep.ini"

# Prose notes the sweep owns. Everything else is either structure (READMEs, the
# index, the dashboard), the templates themselves, Mark's own journal, archived
# capture that is finished, or the published posts, which are live pages and stay
# as published (Mark's call, 2026-09-12). The drift check still reads 30_Posts
# for its status field; the style and ledger checks do not.
SKIP_DIRS = (
    "_Templates",
    "30_Posts",
    ".claude",
    ".vale",
    ".obsidian",
    ".git",
    ".trash",
    "50_Personal/51_Journal",
    "00_Inbox/09_Archive",
)
SKIP_NAMES = {"README.md", "INDEX.md", "Dashboard.md"}
# The manual's folder READMEs are structure too, but the checklist index is prose
# about each procedure and is read like one.
STRUCTURE_ONLY = {"60_Operational_Manual/operational-checklists-index.md"}

SECTIONS = ("correctness", "drift", "manual", "scaffold", "style", "ledger")


def in_scope(rel: str) -> bool:
    if any(rel == d or rel.startswith(d + "/") for d in SKIP_DIRS):
        return False
    if Path(rel).name in SKIP_NAMES:
        return False
    return rel.endswith(".md")


def notes() -> list[str]:
    out = []
    for p in VAULT.rglob("*.md"):
        rel = p.relative_to(VAULT).as_posix()
        if in_scope(rel):
            out.append(rel)
    return sorted(out)


def read(rel: str) -> str:
    return (VAULT / rel).read_text(encoding="utf-8", errors="replace")


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    fm = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm


def strip_fences(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def body_without_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            return text[end + 4 :]
    return text


# ---------------------------------------------------------------- correctness
def check_correctness(add) -> None:
    res = subprocess.run([sys.executable, str(HEALTH), "--json"], capture_output=True, text=True)
    try:
        items = json.loads(res.stdout)
    except json.JSONDecodeError:
        add(
            "correctness",
            "vault-health",
            f"check.py did not return JSON: {res.stderr.strip()[:200]}",
        )
        return
    for it in items:
        # Inbox items have no expiry — see memory. Everything else check.py says, we say.
        if "sitting in the inbox" in it["message"]:
            continue
        add("correctness", it["path"], f"[{it['severity']}] {it['message']}")


# ---------------------------------------------------------------------- drift
def check_drift(add) -> None:
    posts = {}
    for p in (VAULT / "30_Posts").glob("*.md"):
        if p.name != "README.md":
            posts[p.stem] = frontmatter(p.read_text(encoding="utf-8")).get("status", "")

    for rel in notes():
        fm = frontmatter(read(rel))
        status = fm.get("status", "")
        if (
            rel.startswith("10_Projects/")
            and status == "done"
            and not rel.startswith("10_Projects/19_Archive/")
        ):
            add("drift", rel, "status is done but the note is not in 10_Projects/19_Archive")
        if rel.startswith("00_Inbox/") and status == "done":
            add(
                "drift",
                rel,
                "status is done but the note is still in the live inbox — archive to 09_Archive or delete",
            )
        if rel.startswith("10_Projects/19_Archive/") and status and status != "done":
            add("drift", rel, f"in the archive but status is {status}")
        if rel.startswith("20_Buildlogs/") and rel.endswith("-log.md"):
            slug = Path(rel).parent.name
            post = fm.get("post", "")
            if slug in posts:
                want = "published" if posts[slug] == "published" else "drafted"
                if post != want:
                    add(
                        "drift",
                        rel,
                        f"post: {post or '(missing)'} but 30_Posts/{slug}.md is {posts[slug] or 'unset'}",
                    )
            elif post in ("drafted", "published"):
                add("drift", rel, f"post: {post} but there is no 30_Posts/{slug}.md")
            if not fm.get("status"):
                add("drift", rel, "buildlog log has no status: field")

    # A README's Currently: list naming something that lives in an archive folder.
    for readme in VAULT.glob("10_Projects/*/README.md"):
        if readme.parent.name == "19_Archive":
            continue
        text = readme.read_text(encoding="utf-8")
        # Only the Currently: paragraph counts. A line saying a note "finished and is
        # in 19_Archive" is the convention, not drift.
        m = re.search(r"Currently:(.*?)(?:\n\s*\n|\Z)", text, re.S)
        current = m.group(1) if m else ""
        for name in re.findall(r"\[\[([^\]|#]+)", current):
            if (VAULT / "10_Projects/19_Archive" / f"{name}.md").exists():
                add(
                    "drift",
                    readme.relative_to(VAULT).as_posix(),
                    f"lists [[{name}]] as current but it is archived",
                )


# --------------------------------------------------------------------- manual
NEEDS_ROOT = re.compile(
    # state-changing systemctl, any --user systemctl (needs -M through root), and the
    # tools and paths that are root- or container-user-only. Read-only queries such
    # as `systemctl is-active` or reading /etc/os-release work as keepbreath0.
    r"systemctl\s+--user|systemctl\s+(restart|reload|start|stop|enable|disable|daemon-reload)\b|"
    r"\b(podman|journalctl|fail2ban-client|postfix|postconf|postqueue|postmap|"
    r"certbot|restorecon|firewall-cmd|sudoreplay|tee|last)\s|\bdnf\s|"
    r"/etc/(postfix|dkimkeys|letsencrypt|fail2ban|sudoers|systemd)|/root/|/srv/|/var/log/"
)
SSH_CMD = re.compile(r"ssh(?:\s+-t)?\s+(?:-t\s+)?(web|mail|bastion|control|\$h|\$host)\s+'([^']*)'")
STALE_OK = re.compile(r"(?i)decision #1[459]|came off|no longer|removed|retired|destroyed|there is no|replaced|since #19|was the old")
STALE_MANUAL = [
    (
        re.compile(r"/root/\.ssh/authorized_keys"),
        "reads root's authorized_keys; nothing logs in as root now",
    ),
    (
        re.compile(r"DEPLOY_SSH_KEY|DEPLOY_KNOWN_HOSTS|DEPLOY_HOST"),
        "names a deploy secret that was deleted on 2026-09-11",
    ),
    (re.compile(r"(?i)there are no snapshots"), "says there are no snapshots; there are seven"),
    (
        re.compile(r"(?i)github-hosted runner.*deploy|deploy.*github-hosted runner"),
        "describes the deploy on a GitHub-hosted runner",
    ),
    (re.compile(r"22 \| whole internet, until"), "says port 22 is open to the internet until the bastion lands"),
    (re.compile(r"(?i)opendkim|dkimkeys|mail\.private"), "mentions OpenDKIM or its key; removed from the mail box 2026-08-26 (migration decision #15), Brevo signs"),
    (re.compile(r"(?i)docker-compose|compose file|compose\b.*(stack|service)"), "describes the stack as compose; it has been Quadlet units since #19"),
    (re.compile(r"(?i)caddy volume|keepbreath_caddy"), "mentions Caddy volumes on a box that was destroyed on 2026-09-01"),
]


def check_manual(add) -> None:
    for rel in notes():
        if not rel.startswith("60_Operational_Manual/"):
            continue
        text = read(rel)
        for n, line in enumerate(text.splitlines(), 1):
            for m in SSH_CMD.finditer(line):
                host, cmd = m.group(1), m.group(2)
                if host == "bastion" or host == "control":
                    pass  # same rule applies; keepbreath0 there too
                if NEEDS_ROOT.search(cmd) and "sudo" not in cmd:
                    add(
                        "manual",
                        f"{rel}:{n}",
                        f"runs as keepbreath0 but needs root or the container user: ssh {host} '{cmd[:70]}'",
                    )
            for pat, why in STALE_MANUAL:
                # A note is allowed to say a thing is gone; the rule catches notes
                # that still describe it as present.
                if pat.search(line) and not STALE_OK.search(line):
                    add("manual", f"{rel}:{n}", why)


# ------------------------------------------------------------------- scaffold
PLACEHOLDERS = re.compile(
    r"Title goes here|One line on what this covers|%% The trigger|^(created|updated): <% tp\."
)


def check_scaffold(add) -> None:
    for rel in notes():
        text = read(rel)
        starts = [i for i, l in enumerate(text.splitlines(), 1) if l.startswith("%%")]
        if starts:
            n = (len(starts) + 1) // 2
            add(
                "scaffold",
                f"{rel}:{starts[0]}",
                f"{n} Obsidian comment block(s) — template scaffolding left in a real note",
            )
        for n, line in enumerate(text.splitlines(), 1):
            if PLACEHOLDERS.search(line) and not line.startswith("%%") and '"' not in line:
                add("scaffold", f"{rel}:{n}", f"template placeholder text: {line.strip()[:70]}")
        fences = [i for i, l in enumerate(text.splitlines(), 1) if l.startswith("```")]
        if len(fences) % 2:
            add("scaffold", f"{rel}:{fences[-1]}", "odd number of code fences — one is never closed, so everything after it renders as code")
        lines = body_without_frontmatter(text).splitlines()
        offset = len(text.splitlines()) - len(lines)
        for i, l in enumerate(lines):
            if l.startswith("## "):
                j = i + 1
                while j < len(lines) and lines[j].strip() == "":
                    j += 1
                if j >= len(lines):
                    add(
                        "scaffold",
                        f"{rel}:{i + 1 + offset}",
                        f"empty section at end of note: {l.strip()}",
                    )
                elif lines[j].startswith("## "):
                    add("scaffold", f"{rel}:{i + 1 + offset}", f"empty section: {l.strip()}")
                # a ## followed directly by ### is a container heading, not empty


# ---------------------------------------------------------------------- style
def load_gate():
    spec = importlib.util.spec_from_file_location("gate", GATE)
    assert spec is not None and spec.loader is not None, f"cannot load {GATE}"
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


def check_style(add, use_vale: bool) -> None:
    gate = load_gate()
    for rel in notes():
        if rel in STRUCTURE_ONLY:
            continue
        text = strip_fences(body_without_frontmatter(read(rel)))
        for n, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith(("|", "%%", "![[", "```")):
                continue
            if gate.ARROW_CHAIN.search(s):
                add("style", f"{rel}:{n}", f"arrow chain: {s[:80]}")
            if gate.MIDDOT_LIST.search(s):
                add("style", f"{rel}:{n}", f"middot list: {s[:80]}")
            if len(s) >= 40:
                spans = gate.BACKTICKED.findall(s)
                if len(spans) >= 3 and sum(len(x) for x in spans) / len(s) > 0.45:
                    add("style", f"{rel}:{n}", f"backtick-heavy line: {s[:80]}")
    if not use_vale:
        return
    files = [str(VAULT / r) for r in notes() if r not in STRUCTURE_ONLY]
    res = subprocess.run(
        ["vale", "--config", str(VALE_INI), "--output=JSON", "--no-exit", *files],
        capture_output=True,
        text=True,
        cwd=VAULT,
    )
    try:
        data = json.loads(res.stdout or "{}")
    except json.JSONDecodeError:
        add("style", "vale", f"vale did not return JSON: {res.stderr.strip()[:200]}")
        return
    for path, alerts in data.items():
        rel = (
            Path(path).resolve().relative_to(VAULT).as_posix() if Path(path).is_absolute() else path
        )
        for a in alerts:
            add(
                "style",
                f"{rel}:{a['Line']}",
                f"vale {a['Check']} ({a['Severity']}): {a['Message'][:90]}",
            )


# --------------------------------------------------------------------- ledger
def load_ledger() -> dict[str, str]:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {}


def digest(rel: str) -> str:
    return hashlib.sha256((VAULT / rel).read_bytes()).hexdigest()


def check_ledger(add) -> None:
    ledger = load_ledger()
    for rel in notes():
        if rel in STRUCTURE_ONLY:
            continue
        h = digest(rel)
        if rel not in ledger:
            add("ledger", rel, "not yet reviewed against the writing directive")
        elif ledger[rel] != h:
            add("ledger", rel, "changed since its review — review again and re-mark")


def mark(paths: list[str]) -> None:
    ledger = load_ledger()
    for p in paths:
        rel = Path(p).resolve().relative_to(VAULT).as_posix() if Path(p).is_absolute() else p
        if not (VAULT / rel).exists():
            print(f"no such note: {rel}", file=sys.stderr)
            continue
        ledger[rel] = digest(rel)
        print(f"marked {rel}")
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(dict(sorted(ledger.items())), indent=1) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--section", choices=SECTIONS)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-vale", action="store_true")
    ap.add_argument("--mark", nargs="+", metavar="PATH")
    args = ap.parse_args()

    if args.mark:
        mark(args.mark)
        return 0

    findings: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def add(section: str, where: str, msg: str) -> None:
        findings[section].append((where, msg))

    wanted = [args.section] if args.section else list(SECTIONS)
    if "correctness" in wanted:
        check_correctness(add)
    if "drift" in wanted:
        check_drift(add)
    if "manual" in wanted:
        check_manual(add)
    if "scaffold" in wanted:
        check_scaffold(add)
    if "style" in wanted:
        check_style(add, use_vale=not args.no_vale)
    if "ledger" in wanted:
        check_ledger(add)

    total = sum(len(v) for v in findings.values())
    if total == 0:
        print("Sweep check: clean." + ("" if not args.no_vale else " (Vale skipped)"))
        return 0

    for sec in SECTIONS:
        items = findings.get(sec, [])
        if not items:
            continue
        print(f"== {sec} ({len(items)})")
        if args.summary:
            continue
        shown = items[: args.limit] if args.limit else items
        for where, msg in shown:
            print(f"  {where}\n      {msg}")
        if args.limit and len(items) > args.limit:
            print(f"  ... {len(items) - args.limit} more")
    print(
        f"\n{total} finding(s) across {len([s for s in SECTIONS if findings.get(s)])} section(s)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
