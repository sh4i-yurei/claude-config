---
name: writing-agent-instructions
description: Use when creating or changing a skill, a rules file, a role or startup file, or any other text an agent is meant to follow, and before deciding that a new rule should be text at all. Covers testing wording on an agent and choosing the form that fixes the failure.
---

# Writing agent instructions

An instruction is tested like code. If you have not watched an agent fail without it, you don't
know it teaches the right thing, and if you have not watched one succeed with it, you don't know it
works.

## First decide whether it should be text

- **A check beats a sentence.** If code can check the behaviour, through a hook, a CI step or a
  validator, build the check through the build loop and keep text for judgement. A rule broken twice
  is considered for a hook (Operating model decision 13).
- **One more rule per mistake is the failure, not the fix.** Operating model decision 17 records
  that rules for symptoms never changed the habit underneath. Find the cause the text would address.
- **Put it where it costs least.** A rules file loads in every session, so every word costs on
  every call. A skill costs its name and description until opened, and the listing is capped at 1%
  of the context window. Procedures belong in the operational manual, decisions in a note.

## Writing a skill's description

The description says only when to use the skill: the situations and symptoms that should trigger
it. It never summarises the steps, because an agent that reads a summary follows the summary
instead of opening the skill. Keep it short; every description is sent with every session.

## Match the form to the failure

Run the task without the change first and classify how the agent fails.

| How the agent fails | Form that works | Form that backfires |
|---|---|---|
| It knows the rule and breaks it under pressure | A plain prohibition, with its excuses answered one by one | Soft advice such as "prefer" |
| It complies, but the output has the wrong shape | A recipe: what the output is, its parts, in order | A list of things not to do |
| It leaves out an element of something it produces | A required slot in the template it fills in | A prose reminder near the template |
| The right behaviour depends on a condition | A rule keyed to something observable | An unconditional rule with exemptions |

Don't add nuance clauses such as "unless it matters": they reopen the negotiation the rule was meant
to close. An exemption clause doesn't limit a rule's reach; if part of the output must be exempt,
restructure so the rule cannot reach it.

## Test it on an agent

1. **Baseline.** Run a fresh headless session in a labelled pane, as `codex-build-loop` sets out,
   with the realistic context the text will live in and a task that tempts the failure. Record what
   it does and the reasons it gives, word for word.
2. **Control.** Always run the same task with no new guidance. If the control doesn't fail, there
   is nothing to fix; stop.
3. **Repetitions.** Run each variant at least five times. Read every flagged result yourself,
   because quoted examples look like hits to a script. When wording works, runs converge on one
   shape; five readings across five runs mean it doesn't bind yet.
4. **Pressure.** For a rule agents are tempted to break, combine time, sunk cost, an authority
   saying skip it, and tiredness in one scenario. Make the agent choose and act.
5. **Close gaps.** Answer each new excuse in the text and run the scenarios again.

These runs cost tokens. State a ceiling on the number of runs before you start, and run them
read-only with `--restricted`, `--tools` and `--permission-mode dontAsk`, as the pre-flight does.

A test that checks text contains a phrase guards against the phrase being deleted, but proves
nothing about behaviour. What an agent does with the text is the test that matters.

## Landing the change

Skills, rules, and role and startup files are configuration and instructions. Claude changes them
through a pull request Mark merges, and a change to permissions or a deny list says so (Workflow
engine decision 32). A script or hook that comes with a skill is code that runs and goes to Codex
through the build loop. The pull request quotes the baseline and the result with the change.

## Who uses this

The workflow steward and the Workflow upkeep rules seat. Any owner changing its role or startup
file. Operator, when a seat's definition changes.

## Attribution

Adapted from the writing-skills skill of the superpowers plugin 7.0.2
(https://github.com/obra/superpowers), under the MIT License. The notice the licence requires is in
`NOTICE.md` in this folder.
