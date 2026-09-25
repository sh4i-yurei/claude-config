#!/usr/bin/env python3
"""Paced request gateway for research API calls.

Usage: python3 gw.py OUTFILE -- <curl arguments including one https:// URL>

Every research API request goes through this script, one at a time. It enforces:

- the provider's documented minimum gap between requests (PROVIDERS below, each with its
  source), and the skill's per-site gap of ten times the last request's duration, clamped
  to 1-120 seconds, whichever is larger;
- exponential backoff on HTTP 429, never an immediate retry, at most three attempts in total;
- a four-hour refusal after five consecutive errors from one host;
- at most 300 requests to one host per calendar day.

The response body goes to OUTFILE and the headers to OUTFILE.hdr. Every attempt is appended
to the log with keys and email addresses redacted. State and log live outside the vault.
"""

import json
import pathlib
import re
import subprocess
import sys
import time

STATE = pathlib.Path.home() / ".claude" / "research-gw-state.json"
LOG = pathlib.Path.home() / ".claude" / "research-gw-log.jsonl"

# host: (minimum seconds between requests, backoff base seconds, source of the limit)
PROVIDERS = {
    "export.arxiv.org": (3.0, 3.0, "arXiv API terms: one request per three seconds"),
    "api.semanticscholar.org": (
        1.1,
        2.0,
        "allenai/s2-folks API_RELEASE_NOTES.md: 1 RPS on all endpoints for new keys; "
        "exponential backoff required",
    ),
    "api.core.ac.uk": (6.0, 6.0, "CORE academic tier: 10 requests a minute"),
    "api.openalex.org": (
        0.0,
        2.0,
        "priced per call, no rate documented in known-apis.md",
    ),
    "api.github.com": (0.0, 2.0, "5,000 an hour with the research token"),
}
GAP_MULTIPLIER, GAP_FLOOR_S, GAP_CEILING_S = 10, 1.0, 120.0
ERROR_STREAK, ERROR_COOLDOWN_S, PER_DAY, MAX_ATTEMPTS = 5, 4 * 3600, 300, 3


def main() -> int:
    if len(sys.argv) < 4 or sys.argv[2] != "--":
        print(__doc__, file=sys.stderr)
        return 2
    out, args = sys.argv[1], sys.argv[3:]
    url = next((a for a in args if a.startswith("https://")), "")
    m = re.match(r"https://([^/?]+)", url)
    if not m:
        print("[gw] no https:// URL in the arguments", file=sys.stderr)
        return 2
    host = m.group(1)
    min_gap, backoff_base, _source = PROVIDERS.get(host, (0.0, 2.0, "none documented"))
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    e = state.get(host, {})
    today = time.strftime("%Y-%m-%d")

    if (
        e.get("errors", 0) >= ERROR_STREAK
        and time.time() - e.get("end", 0) < ERROR_COOLDOWN_S
    ):
        print(
            f"[gw] REFUSED {host}: {e['errors']} consecutive errors, 4h cooldown",
            file=sys.stderr,
        )
        return 3
    if e.get("day") == today and e.get("count", 0) >= PER_DAY:
        print(f"[gw] REFUSED {host}: {PER_DAY} requests today", file=sys.stderr)
        return 3
    if e:
        gap = max(
            min_gap, min(GAP_CEILING_S, max(GAP_FLOOR_S, GAP_MULTIPLIER * e["dur"]))
        )
        wait = e["end"] + gap - time.time()
        if wait > 0:
            print(f"[gw] pacing {host}: waiting {wait:.1f}s", file=sys.stderr)
            time.sleep(wait)

    safe = re.sub(r"(api_key|key|email|mailto)=[^&]+", r"\1=REDACTED", url)
    code, dur, attempts = "000", 0.0, 0
    for attempts in range(1, MAX_ATTEMPTS + 1):
        t0 = time.time()
        r = subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                out,
                "-D",
                out + ".hdr",
                "-w",
                "%{http_code} %{time_total}",
                *args,
            ],
            capture_output=True,
            text=True,
        )
        code, dur = (r.stdout.split() + ["000", "0"])[:2]
        dur = float(dur)
        with LOG.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "ts": round(t0, 1),
                        "host": host,
                        "url": safe,
                        "code": code,
                        "dur": dur,
                        "attempt": attempts,
                    }
                )
                + "\n"
            )
        print(f"[gw] {host} attempt {attempts} HTTP {code} {dur:.2f}s")
        if code != "429" or attempts == MAX_ATTEMPTS:
            break
        backoff = backoff_base * (2**attempts)
        print(
            f"[gw] 429 from {host}: exponential backoff {backoff:.0f}s", file=sys.stderr
        )
        time.sleep(backoff)

    err = code == "000" or (code.startswith(("4", "5")) and code not in ("404", "429"))
    # Scrapy AutoThrottle rule 4: latencies of non-2xx responses are not allowed to decrease
    # the delay, because errors return faster than real responses. Only a 2xx may shorten it.
    if not code.startswith("2"):
        dur = max(dur, e.get("dur", 0.0))
    state[host] = {
        "end": time.time(),
        "dur": dur,
        "code": code,
        "errors": e.get("errors", 0) + 1 if err else 0,
        "day": today,
        "count": (e.get("count", 0) if e.get("day") == today else 0) + attempts,
    }
    STATE.write_text(json.dumps(state))
    print(f"[gw] requests made: {attempts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
