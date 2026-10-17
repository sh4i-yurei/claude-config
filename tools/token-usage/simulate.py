"""Replay real conversations with a kind of work outsourced, and recompute every call.

A step is one model call's output (thinking, text, tool call) plus everything that
arrived before the next call (tool output, reminders). Outsourcing a kind of work
means: every run of consecutive steps of that kind becomes ONE step, whose tool
call stays but whose output is replaced by a short answer (RESULT tokens). The
calls in between disappear, and every later call carries less.

The saving per call j is the size of the removed items still alive at j. Removed
calls save their whole context. Compaction points are kept where they really
happened, which understates the saving (a shorter conversation compacts later).
"""

import json, collections, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))

RESULT = 300  # tokens a local model hands back for one outsourced run


def load(agent):
    if agent == "claude":
        ns = {}
        exec(open(os.path.join(HERE, "analyze_claude.py")).read(), ns)
        items, calls, base, group = ns["items"], ns["byf"], ns["base"], ns["group"]
        key = lambda c: c["f"]
        out_kinds = ("thinking", "Claude reply", "tool_input", "message framing")
        human = ("Mark message",)
    else:
        ns = {}
        exec(open(os.path.join(HERE, "analyze_codex.py")).read(), ns)
        items, calls, base, group = ns["items"], ns["byf"], ns["base"], ns["group"]
        out_kinds = ("reasoning", "Codex reply", "tool_input")
        human = ()
    return items, calls, base, group, out_kinds, human


def step_category(step_items, group, human):
    """What kind of work a step was: from its tool output, else reply/human."""
    if any(it["kind"] in human for it in step_items):
        return "turn boundary"
    for it in step_items:
        if it["kind"] == "tool_input":
            t, d = it.get("tool"), it.get("detail", "")
            if t in ("Write", "Edit", "NotebookEdit") or d == "write file (heredoc)" or it.get("action") == "apply_patch":
                return "Writing files, code and notes (Claude: Write/Edit/heredoc; Codex: apply_patch)"
            if t == "Skill":
                return "Loading a skill"
            if t == "AskUserQuestion":
                return "Asking me a question"
            if t == "ToolSearch":
                return "Loading tool definitions (ToolSearch)"
            if d.startswith("small shell (") and d[13:-1] in ("cp", "mkdir", "rm", "mv", "touch", "chmod", "ln"):
                return "File housekeeping (cp, mkdir, rm, mv)"
            if d in ("bw", "get") or "bitwarden" in (it.get("desc") or "").lower():
                return "Secrets (Bitwarden)"
            break
    for it in step_items:
        if it["kind"] == "tool_result":
            g = group(it)[1]
            if g.startswith("Reading vault notes"):
                if "30_Posts" in g or it.get("target") == "vault:30_Posts":
                    return "Reading blog posts (vault 30_Posts)"
                return "Reading vault notes (not posts)"
            return g
    return "no tool (reply or thinking only)"


GATHER = {
    "Claude": {
        "Reading vault notes (not posts)",
        "Searching and listing (grep, find, ls, wc)",
        "Web search and pages (WebSearch, WebFetch, Firecrawl, lookups)",
        "Reading code and repo files",
        "Reading session records and saved tool output",
        "Reading skill and agent config files",
        "Reading scratch and other files",
        "git and GitHub",
    },
    "Codex": {
        "Reading vault notes (not posts)",
        "Reading code and repo files",
        "Reading skills and agent config",
        "Reading review results, logs and scratch files",
        "Web search",
        "git and GitHub (diffs, status, log)",
    },
}


def simulate(items, calls, group, out_kinds, human, cats, mode="run"):
    """Total context sent if steps in `cats` were outsourced. Returns (total, calls_removed, removed_runs)."""
    by_file = collections.defaultdict(lambda: collections.defaultdict(list))
    for it in items:
        by_file[it["f"]][it["born"]].append(it)
    total, removed_calls, runs = 0, 0, 0
    for f, cs in calls.items():
        n = len(cs)
        steps = by_file.get(f, {})
        cat = {
            k: step_category(steps.get(k, []), group, human) for k in range(1, n + 1)
        }
        removed = []  # (start_call, end_call_inclusive, tokens) alive windows of removed tokens
        dead_calls = set()
        k = 1
        while k <= n:
            if cat[k] in cats and mode == "step":
                runs += 1
                for it in steps.get(k, []):
                    if it["kind"] == "tool_result":
                        removed.append((it["born"] + 1, it["born"] + it["rides"], it["carried"] / it["rides"] if it["rides"] else 0))
                        removed.append((it["born"] + 1, it["born"] + it["rides"], -min(RESULT, it["tok"])))
                k += 1
                continue
            if cat[k] in cats:
                j = k
                while j + 1 <= n and cat[j + 1] in cats:
                    j += 1
                runs += 1
                # keep step k's own output (thinking, the tool call); drop its tool output
                for it in steps.get(k, []):
                    if it["kind"] not in out_kinds:
                        removed.append(
                            (
                                it["born"] + 1,
                                it["born"] + it["rides"],
                                it["carried"] / it["rides"] if it["rides"] else 0,
                            )
                        )
                # drop steps k+1..j entirely, and the calls k+1..j that produced them
                for s in range(k + 1, j + 1):
                    dead_calls.add(s)
                    for it in steps.get(s, []):
                        removed.append(
                            (
                                it["born"] + 1,
                                it["born"] + it["rides"],
                                it["carried"] / it["rides"] if it["rides"] else 0,
                            )
                        )
                # the short answer rides as long as step k's output would have
                ride = max(
                    (
                        it["rides"]
                        for it in steps.get(k, [])
                        if it["kind"] == "tool_result"
                    ),
                    default=0,
                )
                removed.append((k + 1, k + ride, -RESULT))
                k = j + 1
            else:
                k += 1
        removed_calls += len(dead_calls)
        # per-call removed tokens via a difference array
        diff = [0.0] * (n + 2)
        for a, b, t in removed:
            if a <= b and a <= n:
                diff[a] += t
                diff[min(b, n) + 1] -= t
        run = 0.0
        for idx in range(1, n + 1):
            run += diff[idx]
            if idx in dead_calls:
                continue
            total += max(cs[idx - 1]["ctx"] - run, 0)
    return total, removed_calls, runs


def main(agent):
    items, calls, base, group, out_kinds, human = load(agent)
    real = sum(c["ctx"] for cs in calls.values() for c in cs)
    ncalls = sum(len(cs) for cs in calls.values())
    name = "Claude" if agent == "claude" else "Codex"
    # how many steps of each kind, and how much each kind costs when outsourced alone
    by_file = collections.defaultdict(lambda: collections.defaultdict(list))
    for it in items:
        by_file[it["f"]][it["born"]].append(it)
    count = collections.Counter()
    for f, cs in calls.items():
        for k in range(1, len(cs) + 1):
            count[step_category(by_file[f].get(k, []), group, human)] += 1
    print(f"{name}: {ncalls:,} calls, {real / 1e6:,.0f}M tokens sent")
    print(
        f"{'Outsource this work':52} {'steps':>6} {'step by step':>14} {'whole runs':>14} {'calls gone':>10}"
    )
    rows = []
    for c in count:
        if c in ("turn boundary", "no tool (reply or thinking only)"):
            continue
        tot, rc, runs = simulate(items, calls, group, out_kinds, human, {c})
        lo, _, _ = simulate(items, calls, group, out_kinds, human, {c}, "step")
        rows.append((real - tot, c, count[c], rc, real - lo))
    for saved, c, st, rc, lo in sorted(rows, reverse=True)[:25]:
        print(f"{c[:52]:52} {st:>6} {lo/1e6:>7,.0f}M {100*lo/real:>4.1f}% {saved/1e6:>7,.0f}M {100*saved/real:>4.1f}% {rc:>10}")
    lo, _, _ = simulate(items, calls, group, out_kinds, human, GATHER[name], "step")
    print(f'\nAll read-only gathering, step by step (no calls removed): {(real-lo)/1e6:,.0f}M = {100*(real-lo)/real:.1f}%')
    tot, rc, runs = simulate(items, calls, group, out_kinds, human, GATHER[name])
    print(
        f"\nAll read-only gathering together ({', '.join(sorted(GATHER[name]))[:200]}...):"
    )
    print(
        f"  {runs:,} runs outsourced, {rc:,} calls gone, {(real - tot) / 1e6:,.0f}M saved = {100 * (real - tot) / real:.1f}% of all tokens sent"
    )


if __name__ == "__main__":
    main(sys.argv[1])
