---
name: journal
description: Runs Mark's daily journal as an interview and writes it up as one cohesive narrative entry in ~/Documents/Second_Brain/50_Personal/51_Journal/<year>/. He journals in the MORNING about the DAY BEFORE. Use it when he asks to journal, runs /journal, or when the session brief says yesterday's entry is missing. This produces a human story with self-reflection, not a log of events, and the obvious approach produces a log.
---

# Journal

Mark journals **in the morning, about the day before.** A day written at 10pm is missing
its own evening. That is not backfilling; the rule against that is about reconstructing
from memory days later.

The entry is a **human story with reflection in it**. If what comes out could fairly be
called "a log of what happened", it has failed, however accurate it is.

## Read the craft rules first

`40_Reference/writing-and-teaching-directive.md`, the section called **How to write
narrative**, is the authority on how the entry should be written. Scene against summary,
which details earn their place, showing before reflecting, pacing, voice, and the rule
that if a phrase is better than what he said it is wrong.

`.claude/rules/writing-style.md` loads every session and covers the rest. Both apply to
the entry, not only to chat.

**No em dashes.** The first entry had none, the second had six, and he caught every one.

## The interview

You ask, he answers, you write. He is never handed a template.

**Two questions is not an interview.** Expect four or five rounds. The material worth
keeping almost never arrives in the first answer; it arrives when you ask about something
he mentioned in passing.

**Ask what he saw and did. Never ask how it felt.** Mark is autistic and has said plainly
that he struggles to express himself, so "how did that land?" is the hardest possible
question and he should not have to answer it.

Ask observational questions instead:

- Where were you standing? What were you doing?
- What was he doing while he said it?
- What did you do next?
- Who brought it up? What did they say?

Those get the concrete material the writing needs, and the emotion arrives through it.
The proof is the loading dock scene: walking past, not catching it, stopping, the guy
loading a customer's order, the grin, being in a hurry but wanting the kid to feel him
celebrating, then the walk to the car where it actually hit. None of it was invented and
none of it was available until the right question was asked.

**Chase what has weight.** A phone call gets "how did that sit afterwards". A flat
statement about someone he loves gets "does that still cost you". A rule he lives by gets
"does it still fit when it is aimed at your kids".

**Surprise is always worth a question.** It means an expectation broke, and the
expectation is the interesting part.

**Never stop on the hard beat.** Ask what happened next. The first entry ended a story on
him refusing to buy his stepdaughter dinner, which read as cold, until it turned out he
and Misty combined their leftovers and gave them to her anyway.

**Establish the actual sequence before writing.** He tells the day in the order things
occur to him, which is rarely the order they happened.

## Writing it up

```bash
~/.claude/skills/journal/scripts/new-entry.sh 2026-08-22   # the day being described
```

Named for the day it describes, not the day it is written.

**One cohesive narrative.** Never an events half followed by a reflection half. Removing
the headings is not enough. Interleave: something happens, what it did to him, the next
thing.

**Put a belief where it explains something.** His grandfather's line about liars and
thieves belongs beside the lie that triggered it, not in a philosophy block at the end.

**Keep his chronology for events.** Non-narrative blocks are different: an assessment of
the day's work is not a scene and can sit with the line that introduces it rather than
interrupting a thread. Move at most one such block. **Never reorganise the day to serve a
theme** — that has been tried and it made the entry worse.

**Dialogue goes on its own line, in quotes and italics:**

```
*"That is fucking dumb. Do you have anything else to say?"*

*"No."*

*"Ok then. Have a good night."*

And I hung up.
```

Everything he said to somebody belongs inside the quote, including the second and third
sentences of a text message. Those are speech, not narration about speech.

**Length is not the enemy.** An entry that runs long because the day had a lot in it is
correct. Do not compress.

## Find the thread and write about it

A day is usually one thing wearing several hats, and the entry becomes a story once that
is on the page.

**Say it out loud.** This is his journal and he is the reader. Reflection is why he writes
it. "Show, don't tell" is advice for writing to strangers; applying it here once produced
an entry with the thread everywhere and named nowhere, which is a missing paragraph
rather than subtlety.

So write a passage that draws it together, usually near the end once the material is all
down. Name the moments that turn out to be the same moment, then reach for what is
underneath them.

**Naming the theme is not reflecting on it.** When Mark says the thread is fatherhood,
that is an instruction about what to write, not a sentence to put in his mouth. "That's
what the day was about, fatherhood and passing knowledge on" hands his own editorial note
back to him as though he had thought it.

A label ends the thinking. A thought continues it:

> What I keep running into is that most of it can't be handed over. Turner already knows
> what I think and it hasn't moved him an inch. The only one I got anywhere with was
> Isaac, and that's because he asked.

## Missed days cost one line

Catch up in a sentence and move on. Never backfill in detail, never present a streak, a
count of missed days, or a backlog to clear. A system that guilt-trips a gap gets
abandoned, and an abandoned journal records nothing at all.

If he has been away a week, ask what stands out from the week and write one entry.

## When to offer it

In the morning, or when the session brief reports yesterday's entry missing. Offer once.
If he says no, drop it and do not raise it again that session.
