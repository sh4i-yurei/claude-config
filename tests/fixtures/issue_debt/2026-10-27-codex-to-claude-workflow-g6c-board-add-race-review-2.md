---
type: note
from: codex
to: claude
state: done
project: "[[Global development workflow]]"
created: 2026-10-27
answered: 2026-10-27
tags: [handoff]
---

# Review G6c board add race, round 2

## Request

Review G6c, claude-config #28, against [[2026-10-26-claude-to-codex-workflow-g6c-board-add-race]] TEST CASES, the cited project decisions, and `ARCHITECTURE.md` in `~/Documents/worktrees/claude-config-g6c`. The pushed commit is `cbe3acceeab7e8e02e1a359f44602e52ab546256` on `fix/board-add-race`. Review this round's changes in `tools/workflow/issue.py`, `tests/test_issue_open.py`, and `tests/fixtures/issue_open/fake_gh.py`. The buildlog is [[global-development-workflow-log]]. Round 1's blocking and non-blocking findings are in [[2026-10-26-codex-to-claude-workflow-g6c-board-add-race-review-1]]. Verify each fix and check for regressions.

This repository has no root CI workflow. Confirm that the local full check below ran on the pushed SHA. The command from this clean worktree was `for test in tests/test_*.py; do /usr/bin/python3 "$test" || exit 1; done; git diff --check`; it exited 0 and its summary output was:

```text
308/308 passed
round 3 regressions passed
Ran 21 tests in 1.075s
OK
Ran 46 tests in 10.859s
OK
Ran 27 tests in 6.830s
OK
Ran 11 tests in 55.422s
OK
```

The final fresh `mutmut run --max-children 4` finished `1416/1416`: 1266 killed, 150 survived, zero skipped or without tests. No `board_card` mutant or mutant on this round's changed completion loop survived.

Before deciding a finding's severity, check it against every TEST CASES bullet. A finding that breaks a stated case is blocking regardless of apparent size. Also block a design chosen because it was quicker to build or repaired by stacking patches. Confirm the code respects what `ARCHITECTURE.md` says each touched piece must and must not do. Check that APIs, flags, configuration keys, imports, and referenced documents exist at the pinned version; any hallucination is blocking. A test that pins implementation detail instead of behavior is a defect. Compare the buildlog with the code and real output. Return a verdict of `pass` when no finding is blocking; mark each finding blocking or non-blocking and include file, line, evidence, and the exact TEST CASES bullet it breaks, or `none`.

## Response

```json
{"repo":"sh4i-yurei/claude-config","issue":28,"item":"G6c","verdict":"pass","cost":0.9077492000000001,"findings":[{"severity":"non_blocking","summary":"Round 1's blocking finding is fixed by a redesign, not a stacked patch. The step's description now lives in the step itself, and only the board step's own closure rewrites it to the 'found ... already on board' wording. Action return values are ignored, so GitHub's link responses can no longer leak into the report. The mechanism is positional, though. Every planned step became a two-element list, the loop reads step[0] and step[1], and add() reaches the outer step variable through a closure that is assigned after add() is defined. A small named type, such as a dataclass with description and action fields, would say the same thing without index arithmetic. This is about readability only, and the behaviour is correct.","breaks_test_case":"none","file":"tools/workflow/issue.py","line":491,"evidence":"Lines 491 and 493: `step[0] = f\"found {description} already on board\"` and `step = [f\"added {description} to board\", add]`. Lines 507-516: `step[1]()` and then `completed.append(step[0])`. I loaded 811d4d8's issue.py in memory into the test harness and ran test_link_responses_keep_completed_text_when_status_fails. It failed with `TypeError: sequence item 1: expected str instance, dict found`, which is round 1's crash. Against 978956f and against cbe3acc it passes, with the exact line `completed: created https://github.com/sh4i-yurei/claude-config/issues/99 with labels type:feature, scope:ci; linked parent #20; linked blocked-by #22; added new issue to board`. The fake now returns the issue-shaped issue-20.json fixture for both link POSTs (fake_gh.py:119), so the test exercises a truthy response."},{"severity":"non_blocking","summary":"board_card now validates every card before it matches any of them. One malformed node, such as a null list entry or a card with a null project on some other board, makes the whole lookup raise 'board card is incomplete'. That happens even when a valid card on the configured board appears later in the list, so a race that could be recovered is reported as a failure. The report is still correct and safe: exit 2, with both errors named. GraphQL allows null entries in a connection's nodes list, but in practice this is rare. Skipping invalid cards and raising only when no valid match exists would recover more often. Strict validation is a defensible choice, so this needs no change.","breaks_test_case":"none","file":"tools/workflow/issue.py","line":272,"evidence":"Lines 272-284 check each card in turn and raise IssueError(\"board card is incomplete\") on the first invalid one, before the board-number and owner match on line 283 is reached for later cards. The bad_card subtest makes nodes[0] = None with no second card, so it does not exercise the case where a valid match comes later."}]}
```

Verdict: pass. Cost: $0.9077492000000001.

- Non-blocking: `tools/workflow/issue.py:491` uses two-element lists and positional indexes for step descriptions and actions. Test case broken: none.
- Non-blocking: `tools/workflow/issue.py:272` stops on a malformed card before a later valid card. Test case broken: none.
