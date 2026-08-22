---
name: journal
description: Runs Mark's daily journal entry as an interview and writes it to ~/Documents/Second_Brain/50_Personal/51_Journal/<year>/YYYY-MM-DD.md. Use it when he asks to journal, says he wants to get the day down, or runs /journal. Also offer it at the end of a working session while the day is still accurate, and when the session-start brief says today's entry is missing. Do not use it to write about work that belongs in a buildlog — this is for the parts of life that do not happen next to a terminal.
---

# Journal

Mark's finished writing sounds like a person wrote it because of the `[life]`
entries in his buildlogs — past midnight before a semester starts, a programming
class that ended and left him looking up how to write a dictionary again, a hacked
Facebook account as the reason security does not get phoned in. Those exist only
because someone caught them while they were true.

This is that same capture, applied to the parts of life that do not happen next to
a terminal. Two payoffs, and the second is the one people underrate: it is raw
material for writing, and it is a record of a year that cannot be reconstructed
later, because memory smooths things over and notes do not.

## Run it as an interview

**This is the whole point of the skill.** He is not facing a blank note; you are
asking and he is answering. Answering is a much lower bar than composing,
especially at the end of a long day when the time is not really there — which is
precisely the day most worth capturing and the first one a blank page loses.

So: ask, listen, write it down. Do not hand him a template to fill in.

## The questions

A spine, not a script. Ask them in whatever order the conversation goes, skip what
does not apply, and follow anything that sounds like it has more behind it.

1. **What happened today?** Work, class, shifts, what interrupted, what took longer
   than it should have.
2. **What went well?** However small. These vanish first — a problem announces
   itself and a win does not.
3. **Anything you're grateful for?** One specific thing from *this* day. "My kids"
   is true every day and therefore records nothing.
4. **Anything memorable, or anything you learned?** This is the one that turns into
   writing later.
5. **How was the day, out of ten?** Goes in the `rating:` property, for spotting
   patterns across weeks. It is not a judgement of the day.

**Follow the specifics.** "Spent two hours on a wrong attribute name" is worth
more in six months than "debugged the form." When an answer is general, ask the
one question that makes it concrete.

**A fixed list goes stale.** If the same five questions produce the same five
shrugs three days running, ask about something that actually happened instead —
you can see the buildlogs and the day's commits.

## Writing the entry

```bash
~/.claude/skills/journal/scripts/new-entry.sh          # today
~/.claude/skills/journal/scripts/new-entry.sh 2026-08-21   # a specific day
```

Creates `50_Personal/51_Journal/<year>/YYYY-MM-DD.md` from
`_Templates/journal.md`, makes the year folder if needed, and refuses to overwrite
an existing entry — so a re-run can never clobber a day that is already written.

Write his words, not a tidied version of them. A journal entry rewritten into
your phrasing has lost the thing that made it worth keeping, and it will read as
false to him in a year.

Link what connects: a buildlog he worked in, a project he touched. Those links are
what let a future post find both halves of a day.

## Missed days cost one line

**Catch up in a sentence and move on. Never backfill in detail.**

Two reasons, and both matter. A system that guilt-trips a gap is a system that gets
abandoned — and an abandoned journal records nothing at all, which is strictly worse
than a thin one. And an entry reconstructed from memory three days later has already
lost the exact detail it existed to capture, while still reading as though it were
written live. That is the same dishonesty the buildlog never-prefill rule exists to
prevent.

Never present a streak, a count of missed days, or a backlog to clear. If he has
been away a week, ask what stands out from the week and write one entry.

## When to offer it

At the end of a working session, while the day is still accurate. When the
session-start brief reports today's entry missing. When he mentions being tired,
a shift running long, or something that happened outside work — that is a `[life]`
entry looking for somewhere to live.

Offer once. If he says no, drop it and do not raise it again that session.
