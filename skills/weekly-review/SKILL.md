---
name: weekly-review
description: Runs Mark's weekly review over his Obsidian vault — rolls up the week from its buildlogs and changed notes, runs the vault health and drift checks, and turns what they find into decisions. Use it when he asks for a weekly review, says he wants to catch up on the week, or runs /weekly. Also offer it on a Sunday or Monday, or when the vault has not been reviewed in more than a week. This is the only recurring step that keeps the vault honest, so it matters more than it looks.
---

# Weekly review

Everything else in this vault is one-time work. Folders get arranged once, the
schema gets written once, the checks get built once. **This is the only part that
has to happen again**, and it is therefore the only part that can decay — which
makes it the piece the whole design rests on.

It does two jobs that happen to share a cadence: it rolls up what the week's work
recorded, and it resolves what the drift checks found so the vault keeps telling the
truth.

## Recap before planning

Do them in this order and do not shortcut it. Planning a week before reading the
one that just happened produces a plan built on what you *meant* to do rather than
what you did. The recap is what makes the plan honest.

## 1. Roll up the week

```bash
python3 ~/.claude/skills/vault-query/scripts/query.py status
python3 ~/.claude/skills/vault-query/scripts/query.py recent --days 7
```

Read the week's buildlog entries and the notes that changed. Pull out what actually
happened, what went well, and anything that reads like it wants to become writing.

If the week recorded little, say so plainly and move on. **Do not count quiet days and
do not suggest backfilling.** A review that opens with a scolding is a review he stops
running.

## 2. Run the checks and resolve what they find

```bash
python3 ~/Documents/Second_Brain/.github/scripts/check.py
```

Errors are broken conventions and get fixed. Warnings are usually drift, and drift
is a decision rather than a defect — the note is wrong or the world is, and only he
knows which.

For each finding, land on one of three answers and say which:

- **Fix now**, if it is a one-line correction. A status that should have changed, a
  buildlog that should have closed.
- **Archive it**, if it is an inbox item whose work is finished. Set `status: done`,
  write where the work went, move it to `00_Inbox/09_Archive`. The inbox should trend
  toward empty, and finished items sitting in it are what stops that happening.
- **Capture it**, if it is real work. Into `00_Inbox`, so it survives.
- **It is fine**, if the check is wrong about this case. Say why, out loud — a rule
  that produces a finding nobody acts on should be changed or removed, because
  findings nobody acts on are how a check becomes noise.

**Never leave a finding without a disposition.** The value of a check is entirely in
what happens after it runs.

## 3. Look for drift the checks cannot see

The rules now cover four kinds of coverage drift automatically — the manual's index
against its procedures, `INDEX.md`'s skills table against `.claude/skills`, and any
folder README that lists its contents against that folder. What they still cannot
see:

- **A project note whose prose has gone stale** while its properties are correct.
  "Where it stands" describing a state that ended a month ago.
- **Tooling whose documentation no longer matches it.** This happened on
  2026-08-22: a script was changed and its skill file was not, an hour apart, by
  the person building the drift detector.
- **Work done outside the vault entirely** — commits in a code repo with no
  corresponding note.

Ask about the active projects specifically. Six or seven is a short enough list to
walk.

## 4. Then plan

Now, with the week actually read, ask what he would genuinely pick up. Whatever is
in `## Next` on a project note should be something he would do if he sat down now.
Anything else is an open question or a different project.

If a project has not moved in weeks and he does not intend to pick it up, that is
what `simmering` is for. Moving it there is not giving up — it is what keeps
`active` meaning something.

## Keep it short

This should take fifteen minutes, not an hour. A review that feels like a chore
stops happening, and a review that stops happening takes the rest of the system's
accuracy with it.
