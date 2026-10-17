"""Rank what put tokens into Claude's context, from items.jsonl and calls.jsonl."""

import json, collections, sys

calls = [json.loads(l) for l in open("calls.jsonl")]
items = [json.loads(l) for l in open("items.jsonl")]

# Per file: base context (system prompt + tool definitions) and a scale factor so
# attributed tokens add up to the real context the API recorded.
byf = collections.defaultdict(list)
for c in calls:
    if c["new"]:
        byf[c["f"]].append(c)
carried_f = collections.Counter()
for it in items:
    carried_f[it["f"]] += it["tok"] * it["rides"]
scale, base = {}, {}
for f, cs in byf.items():
    b = max(min(c["ctx"] - c["est_live"] for c in cs[:3]), 0)
    base[f] = b
    real = sum(c["ctx"] for c in cs) - b * len(cs)
    scale[f] = real / carried_f[f] if carried_f[f] else 1
for it in items:
    it["carried"] = it["tok"] * it["rides"] * scale.get(it["f"], 1)

TOTAL = sum(c["ctx"] for cs in byf.values() for c in cs)
NCALLS = sum(len(cs) for cs in byf.values())
BASE = sum(base[f] * len(cs) for f, cs in byf.items())
OUT = sum(c["out"] for cs in byf.values() for c in cs)
THINK = sum(c["think"] for cs in byf.values() for c in cs)
CW = sum(c["cw"] for cs in byf.values() for c in cs)
IN = sum(c["in"] for cs in byf.values() for c in cs)


def M(x):
    return f"{x / 1e6:,.1f}M"


def pct(x):
    return f"{100 * x / TOTAL:.1f}%"


def table(title, keyfn, n=25, filt=lambda it: True, show_new=True):
    agg = collections.defaultdict(lambda: [0, 0, 0])
    for it in items:
        if not filt(it):
            continue
        k = keyfn(it)
        a = agg[k]
        a[0] += it["carried"]
        a[1] += it["tok"]
        a[2] += 1
    rows = sorted(agg.items(), key=lambda kv: -kv[1][0])
    print(f"\n## {title}")
    print(
        f"{'':60} {'carried':>9} {'share':>6} {'size':>8} {'count':>6} {'avg rides':>9}"
    )
    for k, (car, tok, cnt) in rows[:n]:
        rides = car / tok if tok else 0
        print(
            f"{str(k)[:60]:60} {M(car):>9} {pct(car):>6} {tok / 1e3:>7.0f}k {cnt:>6} {rides:>9.0f}"
        )
    rest = rows[n:]
    if rest:
        print(
            f"{'(' + str(len(rest)) + ' more)':60} {M(sum(r[1][0] for r in rest)):>9} {pct(sum(r[1][0] for r in rest)):>6}"
        )


if __name__ == '__main__' and 'summary' not in sys.argv:
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    print(
        f"Calls {NCALLS:,}  context sent {M(TOTAL)}  of which base (system prompt + tool defs) {M(BASE)} = {pct(BASE)}"
    )
    print(
        f"Written to cache {M(CW)}  uncached input {M(IN)}  output {M(OUT)} (thinking {M(THINK)})"
    )
    if what in ("all", "top"):
        table("By kind", lambda it: it["kind"])
        table("By agent", lambda it: it["agent"])
        table("By project", lambda it: it["proj"])
    if what in ("all", "tools"):
        table(
            "Tool output, by tool",
            lambda it: it["tool"],
            filt=lambda it: it["kind"] == "tool_result",
        )
        table(
            "Tool output, by tool and action",
            lambda it: (it["tool"], it["detail"]),
            n=45,
            filt=lambda it: it["kind"] == "tool_result",
        )
        table(
            "Tool output, by action and target",
            lambda it: (it["tool"], it["detail"], it["target"]),
            n=60,
            filt=lambda it: it["kind"] == "tool_result",
        )
    if what in ("all", "inputs"):
        table(
            "What Claude wrote into tool calls, by tool and action",
            lambda it: (it["tool"], it["detail"], it["target"]),
            n=40,
            filt=lambda it: it["kind"] == "tool_input",
        )
    if what in ("all", "injected"):
        table(
            "Reminders and injected text",
            lambda it: it["detail"],
            n=40,
            filt=lambda it: it["kind"] == "reminder",
        )
        table(
            "Skill text loaded",
            lambda it: it["detail"],
            n=30,
            filt=lambda it: it["kind"] == "skill text",
        )
        table(
            "Other injected kinds",
            lambda it: (it["kind"], it["detail"]),
            n=30,
            filt=lambda it: (
                it["kind"]
                not in (
                    "reminder",
                    "skill text",
                    "tool_result",
                    "tool_input",
                    "thinking",
                    "Claude reply",
                )
            ),
        )
    if what in ("all", "singles"):
        top = sorted(items, key=lambda it: -it["carried"])[
            : int(sys.argv[2]) if len(sys.argv) > 2 else 40
        ]
        print("\n## Largest single items")
        for it in top:
            print(
                f"{M(it['carried']):>8} {it['tok'] / 1e3:6.1f}k x{it['rides']:<4} {it['ts'][:10]} {it['proj'][:22]:22} {it['kind']}/{it['tool']}/{it['detail']} :: {(it.get('desc') or '')[:110]!r}"
            )


def group(it):
    """Readable category for the summary table: (family, category)."""
    k, t, d, tg = it['kind'], it['tool'], it['detail'], it['target']
    readish = t == 'Read' or d.startswith('read file')
    if k == 'tool_result':
        if tg == 'home:Pictures':
            return ('Tool output', 'Screenshots and images')
        if readish:
            if tg.startswith('vault:'):
                return ('Tool output', 'Reading vault notes: ' + tg[6:])
            if tg in ('claude:skills', 'claude:config', 'claude:plugins', 'codex:config'):
                return ('Tool output', 'Reading skill and agent config files')
            if tg in ('claude:session transcripts', 'claude:saved tool output', 'codex:session files'):
                return ('Tool output', 'Reading session records and saved tool output')
            if tg.startswith('repo:') or tg.startswith('home:'):
                return ('Tool output', 'Reading code and repo files')
            return ('Tool output', 'Reading scratch and other files')
        if t in ('Grep', 'Glob') or d.startswith('search') or d.startswith('list/find'):
            return ('Tool output', 'Searching and listing (grep, find, ls, wc)')
        if t in ('WebSearch', 'WebFetch', 'MCP') or tg == 'lookup.py':
            return ('Tool output', 'Web search and pages (WebSearch, WebFetch, Firecrawl, lookups)')
        if d.startswith('inline') or d.startswith('run ') or d == 'vault script' or d.startswith('lint'):
            return ('Tool output', 'Output of scripts Claude ran')
        if d.startswith('ssh') or d in ('ansible', 'curl', 'dev container', 'podman', 'systemctl', 'journalctl', 'tailscale'):
            return ('Tool output', 'Remote machines (ssh, ansible, curl)')
        if d.startswith('git') or d.startswith('gh'):
            return ('Tool output', 'git and GitHub')
        if t == 'Agent':
            return ('Tool output', 'Subagent reports')
        return ('Tool output', 'Other tool output')
    if k == 'tool_input':
        if t in ('Write', 'Edit') or d == 'write file (heredoc)':
            return ('Claude writing', 'Files and notes written (Write, Edit, heredoc)')
        if d.startswith('inline'):
            return ('Claude writing', 'Inline scripts Claude wrote to run')
        if t == 'Agent':
            return ('Claude writing', 'Subagent prompts')
        return ('Claude writing', 'Commands and other tool arguments')
    if k == 'thinking':
        return ('Claude writing', 'Thinking (hidden reasoning)')
    if k == 'Claude reply':
        return ('Claude writing', 'Replies to me')
    if k == 'message framing':
        return ('Overhead', 'Per-step overhead (IDs, thinking signatures, wrappers)')
    if k == 'reminder':
        if d == 'skill_listing':
            return ('Injected', 'Skill list')
        if d in ('agent_listing_delta', 'deferred_tools_delta', 'mcp_instructions_delta'):
            return ('Injected', 'Agent, tool and MCP listings')
        if d in ('instructions', 'nested_memory'):
            return ('Injected', 'CLAUDE.md, rules and memory')
        if d.startswith('hook'):
            return ('Injected', 'Hook output')
        if d.startswith('edited_text_file'):
            return ('Injected', 'Edited-file snippets')
        if d == 'total_tokens_reminder':
            return ('Injected', 'Token-budget reminders')
        return ('Injected', 'Other reminders')
    if k == 'skill text':
        if d.startswith('built-in'):
            return ('Injected', 'Skill text: built-in skills')
        if d == 're-sent after compaction':
            return ('Injected', 'Skill text: re-sent after compaction')
        return ('Injected', 'Skill text: my skills')
    if k == 'Mark message':
        return ('Conversation', 'My messages')
    if k in ('agent message',):
        return ('Conversation', 'Messages from other agents')
    return ('Conversation', 'Other (' + k + ')')


def summary():
    agg = collections.defaultdict(lambda: [0, 0])
    for it in items:
        g = group(it)
        agg[g][0] += it['carried']; agg[g][1] += it['tok']
    agg[('Overhead', 'System prompt and tool definitions')] = [BASE, sum(base.values())]
    fam = collections.defaultdict(float)
    for (f, _), v in agg.items():
        fam[f] += v[0]
    size_total = sum(v[1] for v in agg.values())
    print(f'\n{"":66} {"carried":>9} {"share":>6} {"new":>7} {"new share":>9}')
    for f in sorted(fam, key=lambda x: -fam[x]):
        print(f'{f.upper():66} {M(fam[f]):>9} {pct(fam[f]):>6}')
        for (ff, c), (car, tok) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
            if ff == f:
                print(f'  {c:64} {M(car):>9} {pct(car):>6} {tok/1e6:>6.2f}M {100*tok/size_total:>8.1f}%')

if 'summary' in sys.argv:
    print(f'Calls {NCALLS:,}  context {M(TOTAL)}')
    summary()
