---
name: journal
description: Runs Mark's daily journal as an interview and writes it up as one cohesive narrative entry in ~/Documents/Second_Brain/50_Personal/51_Journal/<year>/. He journals in the MORNING about the DAY BEFORE. Use it when he asks to journal, runs /journal, or when the session brief says yesterday's entry is missing. This is a real interview producing a human story with self-reflection, not a log of events — read the whole skill before starting, because the obvious approach produces a log.
---

# Journal

Mark journals **in the morning, about the day before.** A day written at 10pm is
missing its own evening; written next morning it is complete. That is not
backfilling — the rule against that is about reconstructing from memory days later.

The entry is a **human story with self-reflection**, not a record of events. If what
comes out could be described as "a log of what happened", it has failed, no matter how
accurate it is.

## Run it as a real interview

You ask, he answers, you write. He is never handed a template.

**Two questions is not an interview.** Open broadly, then follow every thread that has
weight. Expect four or five rounds. The material that makes an entry worth keeping
almost never arrives in the first answer — it arrives when you ask about something he
said in passing.

Ask **insight** questions, not only causal ones. "Why did that happen" and "what was
that pointed at" produce explanations. "What do you make of that", "what did that tell
you", "has that changed" produce understanding. The first entry ran heavy on causal
questions and light on insight, and it showed.

Openers, then follow the day:

- What did yesterday actually look like? Work, family, what interrupted, what got away
  from you.
- How were you feeling going into it?

Then chase. If he mentions a phone call, ask how it sat afterwards. If he states
something flatly about a person he loves, ask whether he has made peace with it or
whether it still costs him. If he describes a rule he lives by, ask whether it still
fits when it is aimed at his kids.

**When something surprises him, that is always worth a question.** Surprise means an
expectation got broken, and the expectation is the interesting part.

**Do not stop at the hard beat.** Ask what happened next. The first entry ended a story
on him refusing to buy his stepdaughter dinner, which read as cold — because nobody
asked, and it turned out he and Misty combined their leftovers and gave them to her
anyway. That one detail changed who he was in the entry.

## Writing it up

```bash
~/.claude/skills/journal/scripts/new-entry.sh 2026-08-21   # the day being written about
```

Named for the day it describes, not the day it is written.

**One cohesive narrative.** Never an events section followed by a reflection section.
Deleting the headings is not enough — if the first half is what happened and the second
half is what it meant, it is still two documents. **Interleave**: something happens,
what it did to him, the next thing.

**Put the belief where it explains something.** His grandfather's line about liars and
thieves belongs next to the lie that triggered the reaction, not eight paragraphs later
in a philosophy block. Reflection stacked at the back reads as a manifesto.

**State feelings, not just actions.** "Late start to work, a couple of large batch
deliveries" is a telegram. "I got a late start, and I was already exhausted before it
began, because it feels like every night lately I'm burning the midnight oil" is a
person.

**Stage the scenes physically.** Where was he standing, what was he doing. He was at the
refrigerator getting his tea when the call came. That single detail turns a reported
call into a moment.

**Show emotion moving inside a moment.** Not "I was angry" but on edge, then apprehensive,
then real anger with disappointment underneath, wanting the call over before it reached
the point.

**Dialogue goes in quotes, on its own lines, with beats:**

```
*"That is fucking dumb. Do you have anything else to say?"*

*"No."*

*"Ok then. Have a good night."*

And I hung up.
```

**Quotes are required; italics go around them.** Not one or the other — anything spoken
is wrapped in quotation marks, and the whole thing is italicised.

Everything he said to someone goes inside the quote, including the second and third
sentences of a text message. Those are speech, not narration about speech.

**Keep his chronology.** If a moment would land better somewhere else, that is your
aesthetic preference and it does not belong in his record.

**No em dashes.** Mark's writing rules forbid them, in the vault as much as on the site.
They are an AI tell and he spots them instantly. Use a full stop, a comma, or restructure
the sentence. The first entry had none; the second had six, and he caught every one.

**Recall order is not chronology.** He tells you the day in the order things occur to
him, which is almost never the order they happened. Establish the actual sequence before
writing, or you will open on something that took place in the afternoon.

**When he tells you how something felt, that belongs inside the scene.** Not in a
reflection paragraph afterwards. He said the memories came flooding back while a young
man was thanking him; putting that two paragraphs later turned the emotional centre of
the day into a report of an event followed by commentary on it. Editing is placement, not
just wording.

**Be an editor, not a transcriber.** He is handing you raw material for a memoir, not
dictating finished prose. Make the inferences a good editor would: connect the stacked
observations into a thought, put the feeling where it landed, cut what repeats. He will
tell you when an inference is wrong, and that is a cheaper failure than a flat entry.

**Never invent.** No sensory detail he did not give you, and never a causal claim about
his own feelings that he did not make. Writing "which is why the hanging up bothers me"
when he only said it "didn't sit well" puts your inference in his mouth, and in a year
he will read it as his own realisation.

**Length is not the enemy.** Do not compress. An entry that runs long because the day
had a lot in it is correct.

## Missed days cost one line

Catch up in a sentence and move on. Never backfill in detail, never present a streak, a
count of missed days, or a backlog to clear. A system that guilt-trips a gap is a system
that gets abandoned, and an abandoned journal records nothing at all.

If he has been away a week, ask what stands out from the week and write one entry.

## When to offer it

In the morning, or when the session brief reports yesterday's entry missing. Offer once.
If he says no, drop it and do not raise it again that session.
