---
name: reviewing
description: Use when reviewing a change, such as a builder's commit, a pull request, a configuration or instructions pull request, or a spec, and when acting on findings from a reviewer, Copilot, a Codex critique or Mark. Covers judging and grading a change, and answering findings without agreeing by reflex.
---

# Reviewing

A review is judgement about evidence. It is not agreement, and it is not proof: model reviews have
passed real defects at least 8% of the time (Workflow engine decision 39). That is why escalation
rests on tests, CI and mutation, and a review adds to them rather than replacing them.

For code built through the build loop, the review's command, schema and finding fields are in
codex-build-loop step 4. This skill is the judgement inside that review, and the method for reviews
the loop does not cover: configuration and instructions pull requests (Workflow engine decision 32),
specs and research write-ups.

## Giving a review

- **Stay read-only and do it yourself.** Don't start another reviewer for a second opinion. If the
  change is too big for one pass, review it in passes and say so.
- **Treat the builder's report as claims.** A Response, a commit message or a rationale such as
  "kept it simple on purpose" is the builder grading its own work. Check each claim against the diff
  and the real output. A rationale never lowers a finding's severity.
- **The spec is a vision, not a list of every input.** Where it is silent, what a reasonable person
  using the result would expect is still a requirement. Grade a finding by what that person gets if
  it ships, not by whether the spec names the input that triggers it.
- **A defect the handoff asked for is still a finding.** Report it, say the handoff required it, and
  let the orchestrator and Mark decide.
- **List what you declined to judge.** Before the verdict, list every behaviour you considered and
  set aside as outside the spec, one line each with the reason, so nothing is dropped silently.
- **Missing evidence is not negative evidence.** If output looks cut off or a file isn't where a
  report says, re-read it at its path. If it really is missing, report the gap. Don't rerun the
  suite to regenerate what you failed to read.
- **Name what the diff cannot show.** A requirement in unchanged code, or one that spans items, is
  reported as "cannot verify from the diff", with what the orchestrator should check.
- **Cite the file and line for every finding.** Severity follows effect on a user or maintainer.
- **Describe the code.** A finding never refers to Mark, to any agent or AI, or to a vault note,
  because non-blocking findings are copied into public tech-debt issues (Workflow upkeep decision
  87).

Beyond the handoff's cases, look at whether tests check behaviour through the public interface
(testing standard rule 4), CI's surviving mutants, errors that are swallowed, security, and whether
a piece gained a second responsibility against `ARCHITECTURE.md`.

## Asking for a review

- **Hand the reviewer files, not your session:** the commit, the file list, the rehearsal output,
  CI's finished run with its mutation result, and the handoff's cases.
- **Never pre-judge a finding.** If your request says "do not flag", "at most minor", "the handoff
  chose" or "don't treat X as a defect", stop: you are sparing yourself a fix round.
- **Resolve every "cannot verify" item yourself** before the item counts as passed. A real gap
  becomes a blocking finding.

## Acting on findings

Read all of it, restate each item in your own words, check it against the code, decide whether it is
right for this codebase, answer, then act.

- **No agreement by reflex.** Don't write "You're absolutely right", "Great point" or thanks. State
  the fix, or the technical reason the code stands. If you pushed back and were wrong, say what you
  checked and that you were wrong, in one sentence, and move on.
- **When some items are unclear, clarify before acting on any.** Items are often related.
- **Weigh findings by source.** Mark's are trusted; still ask when the scope is unclear. For a
  reviewer seat, Copilot or a Codex critique, check whether it is correct for this code, whether it
  breaks something that works, whether the current code had a reason, whether it holds on every
  version the estate runs, and whether the reviewer had the context.
- **A finding that contradicts a numbered decision goes to Mark.** Don't pick a side alone.
- **Check for real callers before building something "properly".** If nothing uses it, ask whether
  to remove it instead.
- **Code fixes go to Codex** as a fix round, each blocking finding reproduced and its fix proven in a
  scratch copy first (Workflow upkeep decision 49).

## Checking a claim that work is done

| Claim | What proves it | What doesn't |
|---|---|---|
| The tests pass | A fresh run with zero failures | An earlier run, or "should pass" |
| The bug is fixed | The original symptom checked again | The code changed |
| A regression test works | It passes, fails with the fix reverted, then passes again | It passed once |
| A builder finished | The diff shows the change and the output shows the checks | The builder's report |
| The item is done | Each case and the done-when checked one by one | The tests are green |

## Replying on GitHub

Answer an inline comment in its own thread with
`vault-run --env GH_TOKEN -- gh api repos/<owner>/<repo>/pulls/<pr>/comments/<id>/replies`, not as a
new top-level comment. The GitHub writing rules apply: describe the work.

## Who uses this

The reviewer and the pre-flight checker. Every owner, when it orchestrates a build or reads a Codex
critique, Copilot's comments or Mark's notes. The integrator. The editor, for the second half, when
the work is prose.

## Attribution

Adapted from the requesting-code-review, receiving-code-review, subagent-driven-development,
executing-plans and verification-before-completion skills of the superpowers plugin 7.0.2
(https://github.com/obra/superpowers), under the MIT License. The notice the licence requires is in
`NOTICE.md` in this folder.
