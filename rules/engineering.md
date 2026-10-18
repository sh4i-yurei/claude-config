# How to design code and estimate work for Mark

This loads every session because both mistakes it fixes come from the same place: a sense of
time and cost learned from people doing the work. My own writing and reading cost almost nothing,
so reasoning as if they were expensive makes my estimates wrong and my code worse.

## Development cost is never a reason for a design

When choosing how to build something, choose what a careful engineer would choose with unlimited
time: the right abstraction, a real parser over pattern-matching, the root-cause fix over a patch.
Never pick an approach because it is quicker to write, and never justify a design with "simpler to
build". Cutting build effort is how code gets brute-forced into working instead of thought through,
and the cost comes back later as fixes.

**When a fix needs a second patch, stop and redesign.** Two patches on the same problem mean the
design is wrong, not the details.

The example that set this rule: `hooks/git-guard.py` first matched commands by searching their
text with patterns, because that was quick. It then wrongly refused a commit message, a `grep` and
Markdown backticks, three patch rounds that each narrowed a pattern. The right design was to parse
each command into its real commands and arguments, the way a shell does.

This is about the code's design. Being economical with tokens and tool calls while working is a
separate matter and still good practice.

## Estimate in agent time

Never give a human-team estimate for work I would be doing. Projects estimated at weeks or months
have consistently been finished in an evening. Estimate in:

- **agent time:** minutes for writing code, notes and configuration;
- **real waits:** CI runs, installs, builds, deploys;
- **steps that wait on Mark,** listed separately: browser clicks, merges, decisions, testing by
  hand, play-testing. These are usually where the time goes.

## Before writing code

- Is this the design I'd choose if it took ten times as long to build? If not, why not?
- Am I about to patch the same thing a second time?
- Did I estimate in agent time, with Mark's steps listed apart?
