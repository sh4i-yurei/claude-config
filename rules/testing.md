# Testing

This loads every session because a build can start outside a handoff, and the testing bar
must still apply. Every change ships with its tests. The authority is
`~/Documents/Second_Brain/40_Reference/testing-standard.md`.

## Show what the change does

Claude writes each build handoff's test cases as WHEN and THEN from real inputs, so the
expected result is known before building. Codex writes the tests first. For new or changed
behaviour, each test fails on an assertion about behaviour before the code changes. A test
of existing behaviour passes from the start and proves itself when it kills mutants of
the code it covers (Testing and CI decision 11).

A test is never weakened to pass. Tests check behaviour, not implementation: a test that
only checks an internal call can pass while the result seen by a user is wrong.

## Check that the evidence is current

Mutation evidence counts only when the run finished every mutant and reflects the current
code and tests, through a fresh run or the tool's own cache invalidation. Never compare
timestamps to judge freshness; an old verdict can survive a code change. For example, a
coverage number can rise while a test never checks the result; a mutant that survives
exposes that gap. A survivor may be explained only when no test of behaviour could kill it.
If only a test pinning an internal detail could kill a mutant, explain it instead of
writing that test (testing-standard rule 4).

Build handoffs come only from `_Templates/handoff-codex-build.md` and pass the verification
gate in `60_Operational_Manual/68_Dev_Workflow/codex-build-loop.md`: every fact with its
evidence, each test case shown on the starting commit to run where it says and to fail
without the change, and a read-only pre-flight. The pre-handoff checklist there lists the
kinds of claim the gate checks. That manual and
`~/Documents/Second_Brain/40_Reference/testing-standard.md` are the authorities.
