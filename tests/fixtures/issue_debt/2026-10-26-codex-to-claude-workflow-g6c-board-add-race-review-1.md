---
type: note
from: codex
to: claude
state: done
project: "[[Global development workflow]]"
created: 2026-10-26
answered: 2026-10-26
tags: [handoff]
---

# Review G6c board add race, round 1

## Request

Review G6c, claude-config #28, against [[2026-10-26-claude-to-codex-workflow-g6c-board-add-race]] TEST CASES, the cited project decisions, and `ARCHITECTURE.md` in `~/Documents/worktrees/claude-config-g6c`. The pushed commit is `811d4d825aeff5260bc1a0a726e255ea009d7d61` on `fix/board-add-race`. Review `tools/workflow/issue.py`, `tests/test_issue_open.py`, `tests/fixtures/issue_open/fake_gh.py`, and `tests/fixtures/issue_open/issue-board-card.json`. The buildlog is [[global-development-workflow-log]].

This repository has no root CI workflow. Confirm that the local full check below ran on the pushed SHA. The command from this worktree was `for test in tests/test_*.py; do /usr/bin/python3 "$test" || exit 1; done; git diff --check`; it exited 0 on the clean committed worktree:

```text
308/308 passed
round 3 regressions passed
Ran 21 tests in 1.610s
OK
Ran 44 tests in 9.227s
OK
Ran 27 tests in 9.713s
OK
Ran 11 tests in 78.740s
OK
```

The fresh `mutmut run --max-children 4` finished `1369/1369`: 1187 killed, 182 survived, zero skipped or without tests. All 41 new `board_card` mutants and the mutants on changed `open_issue` lines were killed.

Before deciding a finding's severity, check it against every TEST CASES bullet. A finding that breaks a stated case is blocking regardless of apparent size. Also block a design chosen because it was quicker to build or repaired by stacking patches. Confirm the code respects what `ARCHITECTURE.md` says each touched piece must and must not do. Check that APIs, flags, configuration keys, imports, and referenced documents exist at the pinned version; any hallucination is blocking. A test that pins an implementation detail instead of behavior is a defect. Compare the buildlog with the code and real output. Return a verdict of `pass` when no finding is blocking; mark each finding blocking or non-blocking and include file, line, evidence, and the exact TEST CASES bullet it breaks, or `none`.

## Response

```json
{"repo":"sh4i-yurei/claude-config","issue":28,"item":"G6c","verdict":"changes_required","cost":0.9874974000000001,"findings":[{"severity":"blocking","summary":"The step loop now records whatever each planned action returns as its completed-step text. The parent-link and blocked-by-link actions are lambdas that return the GitHub API response, so against real GitHub the completed output prints a Python dict instead of 'linked parent #N'. If any later step fails, the '; '.join(completed) call raises TypeError and open crashes with a traceback instead of exiting 2 with its completed/not completed/failed report. This is a regression from 978956f, where line 474 was completed.append(description). It breaks ARCHITECTURE.md's contract for tools/workflow/issue.py, which says open 'prints the issue URL and completed and remaining steps' and 'exits 0 for success or 2 for refusal or failure'. The cause is a design shortcut: the board step's 'found' wording is passed through the shared action return value, which every other action also uses. A better design keeps the step's description separate from the API call's return value, for example by having the board step update its own entry in a description map or return a sentinel only the board planner produces.","breaks_test_case":"none","file":"tools/workflow/issue.py","line":499,"evidence":"In 978956f, `git show 978956f:tools/workflow/issue.py` has `action()` at line 467 and `completed.append(description)` at line 474. In 811d4d8 these lines are `result = action()` and `completed.append(result or description)`. The parent and blocked-by actions are `lambda: api(...sub_issues...)` and `lambda issue=issue: api(...blocked_by...)`, so they return gh's parsed JSON. GitHub's add-sub-issue and add-blocked-by endpoints answer 201 with the issue object, which is truthy. (I did not re-fetch GitHub's docs in this session.) The tests miss this because tests/fixtures/issue_open/fake_gh.py:84-86 returns `{}`, which is falsy, for both endpoints. I reproduced it in-process with the existing harness, writing no files, by patching issue_tool.api to return {\"id\": 1, \"number\": 20, \"title\": \"parent\"} for those two endpoints, then running run_open(valid(\"parent = 20\\nblocked_by = [22]\")). The success path exited 0 and printed `{'id': 1, 'number': 20, 'title': 'parent'}` twice where `linked parent #20` and `linked blocked-by #22` belong. With an item-edit failure (HTTP 502) added, the same run raised `TypeError sequence item 1: expected str instance, dict found` instead of returning 2. The fix should also make the fake return GitHub's real issue-shaped response for these POSTs, so a test covers this path."},{"severity":"non_blocking","summary":"board_card assumes the GraphQL response always has data.resource.projectItems.nodes. If resource is null, for example when the URL doesn't resolve to an issue the token can see, the subscript raises TypeError. Nothing catches TypeError, so open crashes. A missing key raises KeyError, which the outer loop does catch, but the report then reads `failed: 'data'` and the original item-add error is dropped. Either way the 'failed: <add error>' report the TEST CASES describe is lost. A malformed or null response should be turned into an IssueError, so it goes through the existing 'checking the board also failed' path.","breaks_test_case":"none","file":"tools/workflow/issue.py","line":262,"evidence":"`for card in response[\"data\"][\"resource\"][\"projectItems\"][\"nodes\"]:`. The inner handler in add() catches only IssueError, at `except IssueError as lookup_error`. The outer loop catches `(IssueError, KeyError)`, which does not include TypeError. GraphQL returns `\"resource\": null` for a URI it can't resolve."},{"severity":"non_blocking","summary":"test_successful_add_makes_no_board_lookup_and_keeps_calls checks less than its case requires. It compares only the first two arguments of the last seven api/project calls, but the case says the gh calls are 'exactly those it makes on main at 978956f'. A change to any later argument, or to an earlier call, would pass. The code's success path is unchanged, so this is a gap in the test's evidence and not a broken case. Comparing the full ordered argument lists with the sequence recorded from 978956f would make the test prove its case.","breaks_test_case":"none","file":"tests/test_issue_open.py","line":761,"evidence":"`[call[\"args\"][:2] for call in self.calls() if call[\"args\"][:1] in ([\"project\"], [\"api\"])][-7:]` is compared to seven two-element prefixes."}]}
```

Verdict: changes_required. Cost: $0.9874974000000001.

- Blocking: `tools/workflow/issue.py:499` lets truthy parent and blocked-by API responses replace completed-step descriptions, then raises `TypeError` on a later failure. Test case broken: none; architecture's open output and exit contract is broken.
- Non-blocking: `tools/workflow/issue.py:262` can crash on a null or malformed GraphQL resource. Test case broken: none.
- Non-blocking: `tests/test_issue_open.py:761` compares only call prefixes for the successful add path. Test case broken: none.
