---
name: debugging
description: Use when a bug, failing test, failing CI job, broken service, flaky result or unexpected behaviour needs explaining, before proposing any fix, including when something broke after a deploy or change, or works in one place and not another. Also use when an agent session went wrong, such as repeated work, an ignored plan or a high token cost, and the cause has to be shown from its transcript.
argument-hint: "<error message or problem description>"
---

# Debugging

Find the root cause before proposing any fix. A fix for a symptom is a failure, even when the error
goes away, because the cause comes back somewhere else.

Three binding rules frame this method:

- **The root-cause fix, not the patch** (Operating model decision 7 and the engineering rules).
  When a fix needs a second patch, stop and redesign. The second patch on the same problem already
  says the design is wrong.
- **Correct before fast** (Operating model decision 17). Facts come from the file, the whole
  repository or the machine. When work goes wrong or Mark is frustrated, slow down further.
- **Codex writes the code** (Operating model decision 5). You diagnose. A fix to code goes to Codex
  through the build loop, proven in a scratch copy before it is handed off (Workflow upkeep
  decision 49). The exceptions are the trivial one-file fix Mark asks for while editing, and
  configuration or instructions, which Claude changes through a pull request Mark merges
  (Workflow engine decision 32).

## 1. Investigate

1. **Read the whole error:** every warning, the full stack trace, line numbers, paths and the exit
   code. They often name the cause. Keep the exact text; never paraphrase it, because the exact
   text is what finds earlier occurrences and what the record needs.
2. **State expected against actual.** Write one sentence each for what should happen and what
   happens instead. A bug you can't state that way isn't understood yet.
3. **Reproduce it.** Find the exact steps and whether it happens every time. If it does not
   reproduce, gather more evidence; never guess.
4. **Set the scope:** when it started, and what is affected, such as which machines, services,
   repositories or sessions, and which are not. The start time is what you line changes up
   against, and the unaffected cases are free comparisons for section 2.
5. **Look for an earlier occurrence.** Search the buildlogs, the vault and the repository's and
   `platform-tickets`' issues for the exact error text. If it was solved before, start from that
   record.
6. **Check what changed** around the start time: commits that touched the failing path
   (`git log -- <path>`), deploys, Ansible runs, dependency updates, configuration and
   environment. Read the logs and metrics from that window too: Loki and Prometheus on `hub`
   through Grafana, `journalctl` and `podman logs` on the machine, and the CI run's own log. Many
   of this estate's failures were differences between the laptop, the dev container and the CI
   runner, such as an interpreter that found a package on one and not the other.
7. **Find the failing layer.** When work passes through several components, such as a CI
   workflow, a container, a script and a service, log what enters and leaves each boundary once,
   and check that environment and configuration reach each layer. Run it once, see where the data
   breaks, then investigate only that component.
8. **Trace a bad value back to where it starts.** Ask what called this with the bad value, and keep
   asking until you reach the source. An empty path that makes `git init` run in the current folder
   is a symptom; the test setup that handed over the empty path is the cause.

## 2. Compare

When it works in one place and not another, such as staging and production, or the laptop and CI,
that working place is your comparison. Otherwise, find similar code in the same repository that
works, and read it completely rather than skimming it. Either way, list every difference between
the working case and the broken one before forming a theory, and do not decide in advance that one
cannot matter.

## 3. Test one hypothesis at a time

Write it as "I think X is the cause, because Y." Test it with the smallest change that could prove
it wrong, one change at a time. If it was wrong, form a new hypothesis; do not stack another change
on top. When you do not understand something, say "I don't understand X" and mark it unchecked.

## 4. Prove the fix

A bug fix starts with a test that fails on the bug (testing standard, "Bugs"). Write the case as
WHEN and THEN from the real input that triggered it, show it failing on the starting commit, and put
it in the handoff. Before handing it off, name what else the fix touches: other callers of the
changed code, other inputs that reach it, and anything that relied on the old behaviour, and add a
case for each that could break. After the build, confirm the original symptom is gone, not only that
the new test passes.

## Write it up

The diagnosis goes where the fix is decided, which is the fix's handoff or the incident's issue, in
this shape:

- **Reproduction:** expected, actual, and the exact steps.
- **Root cause:** why it happens, with the evidence that shows it: the trace, the log lines, or the
  hypothesis test that confirmed it.
- **Fix:** the proven fix from the scratch copy and the failing test case it answers. Codex builds
  it.
- **Prevention:** the checks at each layer and the guards from the section below.

The buildlog gets the story as `Saw:`, `Cause:` and `Fix:`, with the real error text pasted in.

## Timing and flaky results

A test that sleeps for a fixed time is guessing how long something takes; it passes on a fast
machine and fails under load or in CI. Wait for the condition you care about instead, with a time
limit and a clear error when it runs out, reading the state fresh inside the loop. A fixed delay is
right only when the behaviour under test is itself timed, and then it comes after waiting for the
triggering condition, with a comment saying why that length. The build loop works this way:
`herdr pane wait-output` waits for the run's end line, not for a number of seconds.

## A test that changes something it shouldn't

When a file or folder appears that no test should create, run the test files one at a time and
check after each one. The first test after which it exists is the one that makes it. On 2026-11-11
a mutant dropped a test's temporary root and wrote into the real vault.

## After the root cause: make the bug impossible

One check at the point of failure can be bypassed by another code path, a refactor or a test
double. Consider a check at every layer the bad value passes through, each one a test case in the
fix's handoff: reject plainly invalid input at the entry point; check the value makes sense in the
logic; add an environment guard that refuses a dangerous operation in the wrong context, such as
writing outside a temporary folder during tests; and log enough context before the dangerous
operation to diagnose the next occurrence.

## When there seems to be no root cause

If the cause really is outside your control, such as timing or an outside service, record what you
checked, add handling such as a retry, a time limit or a clear message, and add logging. Most "no
root cause" findings are an investigation that stopped early, so say how far it went.

## Signs you have skipped the method

"Quick fix for now, investigate later." "Just try changing X and see." "It's probably X." Several
changes at once, then run the tests. A second patch on the same problem. Mark asking "Is that not
happening?" or "Stop guessing". Each means going back to step 1.

## When the thing that went wrong is an agent session

Read `sessions.md` in this folder.

## Who uses this

The incident responder, for triage. The reviewer and the orchestrating owner, when a finding must
be reproduced before its fix. The prover. The cost keeper and workflow steward, for agent sessions.
The teacher, when Mark debugs his own code in `15_Code`: coach him through these steps rather than
giving him the answer.

## Attribution

Adapted from the systematic-debugging and diagnosing-superpowers skills of the superpowers plugin 7.0.2
(https://github.com/obra/superpowers), under the MIT License. The notice the licence requires is in
`NOTICE.md` in this folder.

Expected against actual, setting the scope, looking for earlier occurrences, reading logs from the
window when it started, the side-effects check and the write-up shape come from the debug skill of
the engineering plugin in Anthropic's knowledge-work plugins.
