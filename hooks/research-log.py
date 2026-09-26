#!/usr/bin/env python3
"""PostToolUse recorder: write down every web fetch, per site.

Fetches leave from Mark's home connection. Across 58 session transcripts on the
laptop there were 1,959 of them over 474 domains, several sessions of 44 to 50,
and four parallel subagents each running 20 to 30 searches. That burst-and-parallel
shape is what makes traffic look automated from outside, and nothing was recording
it, so nobody could see it happening.

This records. It never blocks — blocking is research-gate.py's job, and it needs
what this writes to do it.

The unit is the site, not the total. Four pages each from a hundred sites is
reading; four hundred from one site is hammering it. Recording per domain is what
makes that distinction visible at all. Reasoning and sources in
70_Research/client-side-rate-limiting/.

Two files:
  ~/.claude/research-state.json   current state per domain, read by the gate
  ~/.claude/research-fetches.log  append-only history, one JSON object per line
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
from research_log_shared import registered_domain

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "skills" / "research" / "scripts")
)
from common import append_log, repository_name

STATE = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
STATE_FILE = STATE / "research-state.json"

# Tools that fetch a named URL. Searches are recorded too, but they hit one search
# provider rather than the sites in the results, so per-site pacing does not apply
# to them and they carry no domain.
FETCH_TOOLS = {"WebFetch"}
FETCH_TOOL_SUFFIXES = ("firecrawl_scrape",)
SEARCH_TOOL_SUFFIXES = ("firecrawl_search", "firecrawl_developer_search")
SEARCH_TOOLS = {"WebSearch"}


def classify(tool_name: str) -> str:
    if tool_name in FETCH_TOOLS or tool_name.endswith(FETCH_TOOL_SUFFIXES):
        return "fetch"
    if tool_name in SEARCH_TOOLS or tool_name.endswith(SEARCH_TOOL_SUFFIXES):
        return "search"
    return ""


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        tmp.replace(STATE_FILE)
    except OSError:
        pass


def looks_like_error(response) -> bool:
    """Best-effort read of whether the fetch failed.

    Five errors in a row from a site means stop fetching it for hours rather than
    minutes, so the gate needs a count. The shape of a tool response varies, so
    this looks for the obvious signals and accepts that it will miss some.
    """
    blob = json.dumps(response) if not isinstance(response, str) else response
    low = blob.lower()[:4000]
    for marker in (
        "429",
        "too many requests",
        "403",
        "forbidden",
        "timed out",
        "timeout",
        '"error"',
        'statuscode": 5',
    ):
        if marker in low:
            return True
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = payload.get("tool_name") or ""
    kind = classify(tool_name)
    if not kind:
        return 0

    tool_input = payload.get("tool_input") or {}
    url = tool_input.get("url") or ""
    domain = registered_domain(urlparse(url).hostname or "") if url else ""

    now = time.time()
    state = load_state()
    domains = state.setdefault("domains", {})
    today = time.strftime("%Y-%m-%d", time.localtime(now))

    duration_ms = None
    if domain:
        entry = domains.setdefault(domain, {})

        # research-gate.py stamps this immediately before the call. The difference
        # is how long the fetch took, which is what sets the next gap.
        started = entry.pop("pending_since", None)
        if isinstance(started, (int, float)):
            duration_ms = max(0, int((now - started) * 1000))
            entry["last_duration_ms"] = duration_ms

        entry["last_fetch"] = now
        if entry.get("day") != today:
            entry["day"] = today
            entry["count_today"] = 0
        entry["count_today"] = int(entry.get("count_today", 0)) + 1

        if looks_like_error(payload.get("tool_response")):
            entry["consecutive_errors"] = int(entry.get("consecutive_errors", 0)) + 1
            entry["last_error"] = now
        else:
            entry["consecutive_errors"] = 0

    # Session totals, recorded so the pattern is visible later. Not enforced —
    # counting requests is a poor measure of load and the gate does not use it.
    session = state.setdefault("session", {})
    sid = payload.get("session_id") or "unknown"
    if session.get("id") != sid:
        session.clear()
        session["id"] = sid
        session["started"] = now
        session["fetches"] = 0
        session["searches"] = 0
    session["fetches" if kind == "fetch" else "searches"] += 1

    save_state(state)

    try:
        append_log(
            {
                "ts": datetime.fromtimestamp(now, timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "via": (
                    "firecrawl-connector"
                    if "firecrawl" in tool_name.lower()
                    else "webfetch"
                ),
                "host": (urlparse(url).hostname or domain).lower(),
                "url": url[:300],
                "status": None,
                "duration_s": duration_ms / 1000 if duration_ms is not None else None,
                "attempt": 1,
                "run": os.environ.get("RESEARCH_RUN"),
                "repo": repository_name(),
                "archive": None,
            }
        )
    except (OSError, ValueError):
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
