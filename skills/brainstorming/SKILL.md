---
name: brainstorming
description: Use when Mark asks for something new to be built, designed or planned, and what he wants or why is not yet clear from the request, the project note or the code. Covers drawing out intent, laying out approaches and agreeing a design before any spec, Next item or handoff.
---

# Brainstorming

You are good at building, and you build what you believe Mark wants. That belief is usually
thinner than it feels. This skill is for finding out what he actually wants, and why, before
anything is specified or handed to Codex. When you understand the why, you make the hundred small
decisions he never mentions the way he would have made them.

Operating model decision 4 says a project is fully decided before it is built. This skill is how
the deciding starts. The project-note skill says where the result is written, and the build loop
says how it is built.

## First, what do you already know?

- **Everything that matters is in the request,** as in "move this alert's threshold to 90%". Do
  it by the normal route, which for code is a Codex handoff, and say what you did.
- **Something that would change what gets built is missing.** Start the conversation below.

## Look before you ask

Read before your first message: the project note and its charter, their decisions, the Facts
section, and the code or files the request touches. Keep reading until you can explain how the
relevant parts work today and what the change would touch. Never ask what the note or the code
already answers, and never reopen a numbered decision. A request that contradicts a decision is
raised with Mark as a conflict; it is not settled in passing.

## Your first message

- **He has said what he wants.** In about 200 words, say the request back in your own words: what
  he wants, who it is for, and why. Add what you found that bears on it, such as a constraint, a
  conflict with a decision, or a cheaper path. End with one line inviting corrections. If he has
  not said why he wants it, ask that as one open question with nothing to pick from.
- **He has not.** Ask one open question about the biggest thing the request leaves unsettled, and
  say what the answer would change about what gets built.

If nothing is open and there is one sensible way, end the first message with the short design and
ask him to approve it.

## The conversation

Ask a question only when the answer would change what gets built and neither the request nor the
project answers it. Otherwise state your call and your reason as a proposal he can correct.
Process steps, such as where something is written or what to read next, are your calls: make them
and say so.

- **One question at a time,** in plain language, following the writing rules.
- **Get him describing before you offer options.** Until you know why he wants something, ask open
  questions with no example answers attached. Options steer, and his own words carry intent your
  options cannot. Once you know why, sketch each real choice concretely, with what it trades off and
  which you would pick.
- **Say your defaults out loud.** A default he never heard is one he could not reject.
- **Build each question on his last answer or on something you found,** so it helps him think
  through a consequence or a case he may have missed.

The ground to cover is territory, not a script: what kind of thing this is; why now and what
success looks like; goals, non-goals and anti-goals, meaning what would make it a failure even if it
technically works; prior art he liked or hated; what exists now and what he has tried; and the
details he cares about. Never read these out as a list of questions.

## Play it back as you go

As soon as you understand one part well enough to describe it, describe it back in 200 to 300
words, then return to questions about the next part. Only what he said goes in as his. Anything you
filled in goes in as your proposal, with your reason. End each chunk by asking what is wrong or
missing.

## Lay out the approaches

Once you understand what he wants, and before anything goes into the note, put the ways of
building it in a message of their own. Come up with several real alternatives and drop the weak
ones, including any that work against why he wants it and any an existing decision rules out.
Sketch the two or three that remain concretely, grounded in what the project actually does, with
what each trades off. Recommend one and say why. Development cost is never a reason for an approach
(Operating model decision 7).

## Size the work

Use the three questions in `00_Inbox/README.md` and the project-note skill's "Sizing the design".
A fix gets a sentence in its issue. A feature gets a short design. Architecture gets at least two
options compared, with the reasons the others lost, and a Codex critique before any build handoff.
If the work grows mid-conversation, stop, say so, and step up a size. If it is really several
projects, say so and agree an order.

## Learning by trying

Sometimes a quick experiment is the cheapest way to learn what he wants or whether something works.
Run it as a disposable test in a scratch folder, the kind of evidence the gate in `codex-build-loop`
accepts, and record its command and output as a Fact in the project note. An experiment is never
the start of the build. Anything worth keeping goes through the build loop.

## Where the design lands

The agreed design goes into the project note: Scope with its In and Out, numbered Decisions that
each name what was rejected and why, and Facts with their evidence. It never goes into a separate
design file in a repository, because the vault plans and the repositories carry out the work
(Operating model decisions 2 and 16).

## The builder check

For a feature or architecture, before items enter Next, run a fresh read-only Claude in a labelled
pane, as `codex-build-loop` sets out for every job, with this prompt:

> You are a skilled builder in this domain. You have been handed the project note at `<path>` and
> asked to plan its build. You cannot talk to its author. Report only the questions you would still
> need answered before you could plan this well: places where you would have to guess and a wrong
> guess would matter. For each, give the question and why the answer changes the plan. Rank them by
> importance. Skip anything the note leaves to the builder, anything you could reasonably decide
> yourself, and wording. If nothing important is left, say "nothing important left".

Sort the answers into three piles. Questions already answered by the conversation or the project
get the answer written into the note. Minor questions that a sensible builder could settle without
changing what gets built, you settle and mark in the note as your call. Questions only Mark can
answer, whose answer changes what gets built, go to him in one message, most important first. That
is the only round the check produces.

The builder check is not the pre-flight, which reads a finished handoff against the code, and not
the Codex critique, which attacks the design. It asks whether the note is complete enough to plan
from.

## The gate

Nothing is built until Mark has agreed the design and it is in the project note. Building includes
posting a handoff, opening issues for the work and scaffolding a repository. Reading and exploring
are fine.

## Red flags

| Thought | What to do instead |
|---|---|
| "I'll offer a menu of what he might want." | Ask him to describe it first. Options steer. |
| "I'll fill in sensible defaults." | Fill them in and say each one out loud. |
| "He said 'sounds good' to the idea." | Approval covers what you showed him. A design not yet in the note is not agreed. |
| "The experiment works, so I'll build on it." | Keeping it is a build. It goes through the loop. |
| "I should explain the process first." | Ask your question. The process shows itself. |

## Who uses this

Operator, the lead, when it turns what Mark wants into work. Project owners, when a project needs a
new decision. The designer and researcher roles. Any session in which Mark asks for something new.

## Attribution

Adapted from the brainstorming skill of the superpowers plugin 7.0.2
(https://github.com/obra/superpowers), under the MIT License. The notice the licence requires is in
`NOTICE.md` in this folder.
