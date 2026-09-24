#!/usr/bin/env python3
"""PreToolUse gate: refuse a web fetch that would be impolite or avoidable.

Mark's address got flagged by enough sites that he could not create accounts.
The cause was not the total — it was the shape: bursts, parallel subagents, and
254 fetches at one domain. A skill asking me to be careful is a rule I can talk
myself past. This is a lock.

Every threshold here comes from published practice rather than being picked.
Sources in 70_Research/client-side-rate-limiting/.

  gap before refetching a site   ~10x how long the last fetch to it took
                                 (Mercator's adaptive heuristic: a slow response
                                 usually means a loaded server, so back off when
                                 it matters; a flat delay cannot do that)
  floor / ceiling on that gap    1s / 120s
  one fetch per site at a time   Mercator: one connection per host
  five errors in a row           leave that site alone for hours

There is deliberately NO global fetch counter. Counting requests is the metric
Google's SRE book rejects, because request costs differ and the ratio drifts. The
unit of politeness is the site.

A denial here means the approach was wrong, not that the hook is in the way. The
response is to step down the ladder in the research skill, never to route around.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
from research_log_shared import registered_domain  # noqa: E402

STATE = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
STATE_FILE = STATE / "research-state.json"
KNOWN_APIS = STATE / "skills" / "research" / "known-apis.md"

FETCH_TOOLS = {"WebFetch"}
FETCH_TOOL_SUFFIXES = ("firecrawl_scrape",)

GAP_MULTIPLIER = 10
GAP_FLOOR_S = 1.0
GAP_CEILING_S = 120.0
IN_FLIGHT_STALE_S = 300.0
ERROR_STREAK = 5
ERROR_COOLDOWN_S = 4 * 3600
RUNAWAY_PER_DOMAIN_PER_DAY = 300

DOMAIN_IN_BACKTICKS = re.compile(r"`([a-z0-9.-]+\.[a-z]{2,})`")


def deny(reason: str) -> int:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


def allow() -> int:
    return 0


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


def known_api_domains() -> dict:
    """Domains the research skill says to reach a cheaper way, with the advice.

    Read from the skill's own file rather than duplicated here, so adding a row
    there changes behaviour without touching this script. That file is a growing
    cache, because which domains get hammered follows whatever is being built.
    """
    out = {}
    try:
        for line in KNOWN_APIS.read_text().splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            m = DOMAIN_IN_BACKTICKS.search(cells[0])
            if m:
                out[m.group(1)] = cells[1]
    except OSError:
        pass
    return out


def is_subagent(payload: dict) -> bool:
    """True when this call is coming from a delegated agent rather than the main
    session. Parallel subagents each searching is the single worst pattern in the
    recorded history, and it has no legitimate use for web research.

    The payload field carrying this is not documented, so several plausible names
    are checked and the default is to allow. Verify against research-fetches.log,
    which records the keys actually received.
    """
    for key in ("is_subagent", "subagent", "agent_id", "parent_session_id"):
        v = payload.get(key)
        if isinstance(v, bool) and v:
            return True
        if isinstance(v, str) and v:
            return True
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return allow()

    tool_name = payload.get("tool_name") or ""
    if not (tool_name in FETCH_TOOLS or tool_name.endswith(FETCH_TOOL_SUFFIXES)):
        return allow()

    url = (payload.get("tool_input") or {}).get("url") or ""
    domain = registered_domain(urlparse(url).hostname or "")
    if not domain:
        return allow()

    if is_subagent(payload):
        return deny(
            "Subagents must not fetch the web. Parallel agents each searching is "
            "the pattern that got this address flagged. Do the research in the "
            "main session, one fetch at a time."
        )

    now = time.time()
    state = load_state()
    entry = (state.get("domains") or {}).get(domain, {})

    # A one-off goes through; a run of them is research and should use the API.
    apis = known_api_domains()
    if domain in apis and entry.get("known_api_used_at"):
        if now - entry["known_api_used_at"] < 6 * 3600:
            return deny(
                f"{domain} has a cheaper route and you have already fetched it "
                f"directly once recently. Use it instead: {apis[domain]}. "
                "See known-apis.md in the research skill."
            )

    errors = int(entry.get("consecutive_errors", 0))
    last_error = entry.get("last_error") or 0
    if errors >= ERROR_STREAK and now - last_error < ERROR_COOLDOWN_S:
        wait_h = round((ERROR_COOLDOWN_S - (now - last_error)) / 3600, 1)
        return deny(
            f"{domain} has failed {errors} times in a row. Standard practice is "
            f"to leave a site alone for hours after that, not minutes. About "
            f"{wait_h}h left. Find the material somewhere else."
        )

    pending = entry.get("pending_since")
    if isinstance(pending, (int, float)) and now - pending < IN_FLIGHT_STALE_S:
        return deny(
            f"A fetch to {domain} is already in flight. One connection to a site "
            "at a time. Wait for it to finish."
        )

    last_fetch = entry.get("last_fetch") or 0
    if last_fetch:
        last_ms = entry.get("last_duration_ms")
        gap = (last_ms / 1000.0) * GAP_MULTIPLIER if last_ms else GAP_FLOOR_S
        gap = max(GAP_FLOOR_S, min(GAP_CEILING_S, gap))
        waited = now - last_fetch
        if waited < gap:
            return deny(
                f"Too soon for {domain}. The last fetch there took "
                f"{int(last_ms or 0)}ms, so the polite gap is {gap:.0f}s and only "
                f"{waited:.0f}s have passed. Fetch a different site meanwhile, or "
                "wait. Pacing is per site, not overall."
            )

    if int(entry.get("count_today", 0)) >= RUNAWAY_PER_DOMAIN_PER_DAY:
        return deny(
            f"{domain} has been fetched {entry['count_today']} times today. That "
            "is a loop, not research. Stop and work out what is repeating."
        )

    # Allowed. Stamp the start so the recorder can work out how long it took,
    # which is what sets the next gap.
    domains = state.setdefault("domains", {})
    e = domains.setdefault(domain, {})
    e["pending_since"] = now
    if domain in apis:
        e["known_api_used_at"] = now
    save_state(state)
    return allow()


if __name__ == "__main__":
    sys.exit(main())
