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

## Find the thread, and write about it

A day is not a list of events. There is usually one thing running underneath all of them,
and the entry is only a story once that thread is on the page.

**Say it out loud.** This is his journal, he is the reader, and reflection is the entire
point of writing it. "Show, don't tell" is advice for writing to strangers who have to be
trusted to work it out. It does not apply here, and applying it once produced an entry
that had the thread everywhere and named it nowhere, which is not subtlety, it is a
missing paragraph.

So when the thread is clear, write a passage that draws it together. Name the day's
subject, list the moments that turn out to be the same moment, and say what it meant.
Usually near the end, once the material has all been laid down.

For 2026-08-22 the thread was fatherhood and what it takes to pass what you know to the
next generation. A young man at the loading dock about to have a daughter. Wanting to
hand him everything and not being able to. Turner needing a step nobody can take for him.
Isaac at the keyboard learning what a pipe does. And Mark's own father, who gave him none
of it.

**Naming the theme is not reflecting on it.** When Mark says the thread is fatherhood,
that is an instruction about what to write, not a sentence to put in his mouth. Writing
"that's what the day was about, fatherhood and passing knowledge on" hands his own
editorial note back to him as though he had thought it, and it is hollow, because a label
ends the thinking where a thought continues it.

The real version reaches the thing underneath: most of what he wants to give away cannot
be handed over, the young father will have to find it himself, Turner already knows what
he thinks and it has not moved him, and Isaac only got anywhere because he asked. He
keeps offering anyway. That is a conclusion. "The day was about fatherhood" is a caption.

**Arrange for it too, but do not reorganise the day to chase it.** Chronology still rules.
Moving one off-thread block is fine; rebuilding the entry around a theme is not, and it
makes things worse. He will tell you when it reads badly.

## Ask what he saw and did, never how it felt

Mark is autistic and has said plainly that he has trouble expressing himself. "How did
that land?" is the hardest possible question and he should not have to answer it.

Ask observational questions instead. Where were you standing. What was he doing. What
did you do next. Who brought it up. What did they say.

That gets you the concrete material the writing needs, and **the emotion arrives through
it rather than being named.** The proof: asking those questions turned a flat paragraph
into the best scene in the entry. He was walking past, didn't catch it, stopped. The guy
was loading a customer's order while he told him. Mark grinned. He was in a hurry but
wanted the kid to feel him celebrating. Then he walked to his car, and *that* is where
it hit him.

None of that was invented and none of it was available until the right question was
asked. The first version had the emotion happening at the dock, in one collapsed moment,
because nobody asked what happened next.

## Show, do not tell

Telling names an emotion. Showing puts down the concrete thing and trusts it.

- Telling: "Turner is afraid and doesn't believe in himself."
- Showing: "Every time this comes up he finds reasons why he can't, and this time was no
  different."

**Do not do both.** Putting down the detail and then labelling it is the most common way
an emotional passage dies. The detail already did the work.

A scene needs three things: **dialogue, concrete detail, and action.** If a passage has
none of them it is summary, and summary is where an entry goes flat.

## Read the writing directive before writing

`.claude/rules/writing-style.md` is loaded every session, and
`40_Reference/writing-and-teaching-directive.md` is the full version. Apply them to the
entry, not just to chat. The test is theirs:

> **Would a person who is not me understand this on the first read, without already
> knowing what I was trying to say?**

The second entry needed a whole extra pass because it failed that test in thirteen
places, and every one was the same failure: **inflating his plain phrasing into
writing.**

He said *"there is nothing like being a father"* and it came out as *"there's nothing
on this earth like being a father."* He said *"he's young, obviously"* and it became a
sentence about what it is like to be young when the news is the biggest thing that has
ever happened to you, which is a whole interior life invented for a man he exchanged
four sentences with. He said the vault *"needs refinement"* and it became a paragraph
about watching something happen enough times to name it out loud.

Worst of the lot: **"None of which means being soft about it."** Soft about *what*? It
is a bridge between two paragraphs that refers to nothing. That sentence is the shape
to watch for — connective tissue that sounds like prose and carries no meaning.

The rule that catches all of it: **if a phrase is better than what he said, it is
wrong.** Editing is placement, structure and cutting. It is not upgrading his words.

Watch particularly for fragments used for effect. He speaks in flowing sentences. When
his *"all my failures as a father but also all of my victories, the times I failed to
protect my kids and the harm I inadvertently caused them"* gets chopped into three
punchy fragments, that is a writer's rhythm imposed on a man who does not talk that way.

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
