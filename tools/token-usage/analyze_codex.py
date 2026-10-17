"""Rank what put tokens into Codex's context."""
import json, collections, sys

calls = [json.loads(l) for l in open('cx_calls.jsonl')]
items = [json.loads(l) for l in open('cx_items.jsonl')]
byf = collections.defaultdict(list)
for c in calls:
    byf[c['f']].append(c)
car = collections.Counter()
for it in items:
    car[it['f']] += it['tok'] * it['rides']
base, scale = {}, {}
for f, cs in byf.items():
    base[f] = max(cs[0]['ctx'] - cs[0]['est'] + (cs[0]['est'] - 0), 0) if False else max(min(c['ctx'] - c['est'] for c in cs[:2]), 0)
    real = sum(c['ctx'] for c in cs) - base[f] * len(cs)
    scale[f] = real / car[f] if car[f] else 1
for it in items:
    it['carried'] = it['tok'] * it['rides'] * scale.get(it['f'], 1)
TOTAL = sum(c['ctx'] for c in calls)
BASE = sum(base[f] * len(cs) for f, cs in byf.items())
M = lambda x: f'{x/1e6:,.1f}M'
pct = lambda x: f'{100*x/TOTAL:.1f}%'


def group(it):
    k, a, tg = it['kind'], it['action'], it['target']
    if k == 'reasoning':
        return ('Codex writing', 'Reasoning (hidden)')
    if k == 'Codex reply':
        return ('Codex writing', 'Commentary and replies')
    if k == 'tool_input':
        if a == 'apply_patch':
            return ('Codex writing', 'Code and note patches (apply_patch)')
        if 'inline script' in a:
            return ('Codex writing', 'Inline scripts')
        return ('Codex writing', 'Commands and other tool arguments')
    if k == 'tool_result':
        if a.startswith('wait') or 'write_stdin (poll)' in a:
            return ('Tool output', 'Waiting on running commands (wait, write_stdin polling)')
        if a == 'apply_patch':
            return ('Tool output', 'Patch results')
        if 'codex cli' in a:
            return ('Tool output', 'Starting codex review / codex exec')
        if a.startswith('shell: read file') or a.startswith('shell: list') or a.startswith('shell: search'):
            if tg.startswith('vault:'):
                return ('Tool output', 'Reading vault notes')
            if tg in ('claude:skills', 'claude:config', 'codex:config', 'claude:plugins'):
                return ('Tool output', 'Reading skills and agent config')
            if tg in ('codex:session files', 'claude:session transcripts', 'claude:saved tool output', 'tmp'):
                return ('Tool output', 'Reading review results, logs and scratch files')
            return ('Tool output', 'Reading code and repo files')
        if a.startswith('shell: git') or a.startswith('shell: gh'):
            return ('Tool output', 'git and GitHub (diffs, status, log)')
        if any(x in a for x in ('lint/test', 'pytest', 'ruff', 'make', 'uv', 'run script', 'run python', 'inline')):
            return ('Tool output', 'Running checks, tests and scripts')
        if any(x in a for x in ('ssh', 'ansible', 'curl', 'dev container', 'podman', 'pwsh', 'powershell')):
            return ('Tool output', 'Remote machines and containers')
        if a.startswith('web'):
            return ('Tool output', 'Web search')
        if a == 'get the time':
            return ('Tool output', 'Getting the time')
        return ('Tool output', 'Other tool output')
    if k == 'developer instructions':
        return ('Injected', 'Developer instructions (Codex system text, memory, permissions)')
    if k == 'user-side text':
        return ('Injected', 'User-side: ' + a)
    if k == 'compaction summary':
        return ('Injected', 'Compaction replacement history')
    return ('Other', k)


def table(title, keyfn, n=30, filt=lambda it: True):
    agg = collections.defaultdict(lambda: [0, 0, 0])
    for it in items:
        if filt(it):
            a = agg[keyfn(it)]; a[0] += it['carried']; a[1] += it['tok']; a[2] += 1
    print(f'\n## {title}')
    print(f'{"":64} {"carried":>9} {"share":>6} {"new":>8} {"count":>6} {"rides":>6}')
    rows = sorted(agg.items(), key=lambda kv: -kv[1][0])
    for k, (c, t, n_) in rows[:n]:
        print(f'{str(k)[:64]:64} {M(c):>9} {pct(c):>6} {t/1e3:>7.0f}k {n_:>6} {c/t if t else 0:>6.0f}')
    if rows[n:]:
        print(f'{"(" + str(len(rows) - n) + " more)":64} {M(sum(r[1][0] for r in rows[n:])):>9} {pct(sum(r[1][0] for r in rows[n:])):>6}')


if __name__ == '__main__':
    print(f'Codex: {len(byf)} sessions, {len(calls):,} calls, context sent {M(TOTAL)}, cached {M(sum(c["cached"] for c in calls))}, '
          f'output {M(sum(c["out"] for c in calls))} (reasoning {M(sum(c["rs"] for c in calls))}); base {M(BASE)} = {pct(BASE)}')
    st = collections.Counter(); stn = collections.Counter()
    for c in calls:
        st[c['stype']] += c['ctx']; stn[c['stype']] += 1
    for k, v in st.most_common():
        print(f'  {k:28} {M(v):>8} {pct(v):>6} calls {stn[k]}')
    agg = collections.defaultdict(lambda: [0, 0])
    for it in items:
        g = group(it); agg[g][0] += it['carried']; agg[g][1] += it['tok']
    agg[('Overhead', 'Base context (system prompt, tool definitions)')] = [BASE, sum(base.values())]
    fam = collections.Counter()
    for (f, _), v in agg.items():
        fam[f] += v[0]
    newtot = sum(v[1] for v in agg.values())
    print(f'\n{"":64} {"carried":>9} {"share":>6} {"new":>7} {"new share":>9}')
    for f, fv in fam.most_common():
        print(f'{f.upper():64} {M(fv):>9} {pct(fv):>6}')
        for (ff, c), (cv, tv) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
            if ff == f:
                print(f'  {c:62} {M(cv):>9} {pct(cv):>6} {tv/1e6:>6.2f}M {100*tv/newtot:>8.1f}%')
    if 'detail' in sys.argv:
        table('Tool output by action and target', lambda it: (it['action'], it['target']), 45, lambda it: it['kind'] == 'tool_result')
        table('By session type and group', lambda it: (it['stype'], group(it)[1]), 25)
