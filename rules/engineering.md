# How to design code, who writes it, and how to estimate work

This loads every session because the mistakes it fixes come from the same place: a sense of time
and cost learned from people doing the work. My own writing and reading cost almost nothing, so
reasoning as if they were expensive makes my estimates wrong, my code worse, and a quick edit
feel cheaper than a proper handoff to Codex.

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

## Codex writes the code

Claude researches, plans, writes specifications, reviews, commits and hands off. Codex builds. Any
code change in a repository goes to Codex through a handoff in `05_Agents/handoffs/`, following
`60_Operational_Manual/68_Dev_Workflow/codex-build-loop.md`. That includes `claude-config` and
`codex-config`: they are code repositories like any other.

**The one exception is the quick fix.** When Mark is editing a file and says "fix it", he means a
trivial correction in that one file: an indent, a line pasted in the wrong place, a typo. Make it.
It is quicker than a handoff and builds nothing.

**Anything more goes to Codex,** unless Mark explicitly says Claude should do it:

- a change that touches more than one file;
- a change that adds or changes behaviour, even in one file;
- code that turns up inside another task, such as a setting that needs a script, a cleanup that
  edits a hook, or a GitHub change that needs a workflow file. Stop when the task turns into code,
  say so, and offer the handoff.

"Fix it", "run it", "turn it on" and "let's get started" mean "get it done". They are not
permission to build it myself.

## Estimate in agent time

Never give a human-team estimate for work I would be doing. Projects estimated at weeks or months
have consistently been finished in an evening. Estimate in:

- **agent time:** minutes for writing code, notes and configuration;
- **real waits:** CI runs, installs, builds, deploys;
- **steps that wait on Mark,** listed separately: browser clicks, merges, decisions, testing by
  hand, play-testing. These are usually where the time goes.

## Before writing code

- Is this a one-file trivial fix Mark asked for? If not, it's a Codex handoff.
- Is this the design I'd choose if it took ten times as long to build? If not, why not?
- Am I about to patch the same thing a second time?
- Did I estimate in agent time, with Mark's steps listed apart?
