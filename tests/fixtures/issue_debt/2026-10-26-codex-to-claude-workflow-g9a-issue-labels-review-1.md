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

# G9a issue labels, review round 1

## Request

Review G9a against the TEST CASES in [[2026-10-26-claude-to-codex-workflow-g9a-issue-labels]], Global development workflow decisions 27, 28 and 38, and the `tools/workflow/issue.py` and `config.py` rows of `ARCHITECTURE.md`. The worktree is `~/Documents/worktrees/claude-config-g9a` on `feature/issue-labels`. The pushed commit is `6553ca5` (`Allow checked global labels when opening issues`). Changed files are `tools/workflow/issue.py`, `tests/test_issue_open.py`, `README.md` and `pyproject.toml`. The repository has no root CI workflow.

The full check ran locally on that commit in `dev` from the worktree: `for test in tests/test_*.py; do /usr/bin/python3 "$test" || exit 1; done; git diff --check`. It exited 0. The output included:

```text
308/308 passed
round 3 regressions passed
Ran 21 tests in 1.092s
OK
Ran 36 tests in 7.070s
OK
Ran 27 tests in 7.434s
OK
Ran 11 tests in 59.330s
OK
```

The live GitHub dry run exited 0 and planned an issue request with `"labels": ["type:chore", "scope:ci", "tech-debt", "debt:code", "debt:accidental"]`. The buildlog has the complete planned request and the red test output. A complete mutmut run processed 1,314 candidates, but marked `open_issue` mutants as `no tests`: the fake `gh` tests launch the tool in a subprocess, which mutmut does not link to its test process. Please judge this limitation explicitly against the testing standard.

Before deciding a finding's severity, check it against every TEST CASES bullet. A finding that shows a stated case broken is blocking, however small it looks. A design chosen because it was quicker to build, or a problem fixed by stacking patches, is also blocking. Confirm that the local full check output is for `6553ca5`. Check the code against `ARCHITECTURE.md`'s responsibilities and prohibitions. Check that APIs, flags, configuration keys and imports exist at the pinned version and that cited documents exist; any hallucination is blocking. Treat a test that pins implementation rather than behavior as a defect. Check the buildlog against code and actual output.

Return `pass` when no finding is blocking. Give every finding a blocking or non-blocking severity, its file, line, evidence, and the exact TEST CASES bullet it breaks or `none`.

## Response

```json
{"repo":"sh4i-yurei/claude-config","issue":23,"item":"G9a Extra labels when opening an issue","verdict":"changes_required","cost":1.293298,"findings":[{"severity":"blocking","summary":"The mutation-testing setup was changed by two stacked patches, and together they produce no mutation evidence. In pyproject.toml, test_issue_open.py was added to mutmut's test selection and a '-k not test_missing_pyyaml_names_dependency' exclusion was added. In the test fixture's setUp, a copy of pyproject.toml is placed into every test's temporary directory. Because test_issue_open.py runs issue.py only as a subprocess, mutmut still links none of its tests to any mutant. These changes should be removed, and the gap they were meant to close should be redesigned or raised as an open question (see the next finding).","breaks_test_case":"none","file":"pyproject.toml","line":8,"evidence":"Buildlog 19:36 entry, first patch: 'Saw: FileNotFoundError: Could not figure out where the code to mutate is ... Fix: I am making the fixture's temporary directory carry the repository's mutation configuration', which became tests/test_issue_open.py:25 `shutil.copy(ROOT / \"pyproject.toml\", self.root / \"pyproject.toml\")`. Buildlog 19:38 entry, second patch: 'Saw: ... test_missing_pyyaml_names_dependency: AssertionError: 1 != 2 ... Fix: I excluded this dependency-only test', which became pyproject.toml:9 `pytest_add_cli_args = [\"-k\", \"not test_missing_pyyaml_names_dependency\"]`. Buildlog 19:53 entry, the result: '611 marked no tests ... Mutmut marked the open_issue mutants as no tests because the issue-opening tests run the tool in a subprocess.' Why the patches cannot work: tests/test_issue_open.py never imports issue.py (its only import from the tools package is `from tools.workflow.config import load_boards`, line 17), and config.py is not in source_paths. mutmut 3.8.0's stats.record_trampoline_hit records hits in the memory of the process that makes them, so hits inside the subprocess are lost and the selection change attributes no test to any mutant. The handoff and the engineering rule both treat a problem fixed by stacking patches as blocking ('When a fix needs a second patch, stop and redesign'). The handoff also says 'Touch only the files this item needs', and these edits are not needed for any TEST CASES bullet."},{"severity":"non_blocking","summary":"Judged against the testing standard, as the review request asked: the code this item changed in open_issue has no mutation evidence. That falls short of 'Mutation testing on changed code', and the mutants cannot be written up as survivors, because tests of behaviour could kill them. The open tests just need to run in-process. The fix is a change to the test harness for all 36 open tests, which no TEST CASES bullet asks for, so it needs a decision in Open questions rather than a fix inside G9a.","breaks_test_case":"none","file":"tools/workflow/issue.py","line":298,"evidence":"The completed run was fresh and finished all mutants ('1314/1314 ... 581 killed, 611 marked no tests, and 122 survived'), so it counts as a run. It still gives no verdict on the new lines 298-317 or on the labels line in the request construction (lines 380-384). Testing-standard 'What full coverage means' point 2 requires mutants in changed code to be killed or explained in the survivors file. Rule 4 allows an explanation only when no test of behaviour could kill the mutant, and that is not the case here. Calling issue.py's command entry in-process, with argv and captured stdout and the fake gh still on PATH, tests the same public interface (exit code, stdout, gh calls), and mutmut would link it. I reasoned through the new code's mutants by hand. The existing subprocess tests would catch each of these: removing \"labels\" from the allowed set, flipping `if \"labels\" in data`, changing `or` to `and` in the shape check, dropping `isinstance(label, str)` (which crashes with exit 1, not 2), altering the 'type:' or 'scope:' prefix, flipping `not in global_labels`, and changing or removing `*data.get(\"labels\", [])`. The one exception is dropping `label.strip()`: `labels = [\"\"]` would still be refused, but with the message 'labels:  is not a global label' instead, and no test covers an empty name. So the tests are meaningful. Mutmut just cannot see them. The gap predates G9a: .mutation-survivors.yml already notes 'unchanged G3a Open behavior', and open_issue was never in mutmut's selection on main. The 'no labels key' case passes from the start, and the handoff's rule says its proof must be the mutation run, so that proof is still missing until the harness decision is made."},{"severity":"non_blocking","summary":"The labels check is written inline in open_issue, while validate() is where every other input key's shape is checked, including milestone, parent, blocked_by and scope. 'labels' was added to validate()'s allowed set but is not checked there, so a key's acceptance and its checks are now split between two functions.","breaks_test_case":"none","file":"tools/workflow/issue.py","line":298,"evidence":"tools/workflow/issue.py:110 `def validate(data, form=None, scopes=None)` lists \"labels\" in `allowed` (line 120) and checks the other optional keys at lines 153-174. The labels checks sit in open_issue at lines 298-317 and use `global_labels` from `load()` at line 262. Passing global labels into validate() would keep each key's checks in one place. The behaviour does not change, and every TEST CASES bullet holds either way."},{"severity":"non_blocking","summary":"The buildlog paraphrases the red (failing-first) test run instead of pasting it. The review request says 'The buildlog has the complete planned request and the red test output', but only fragments of the red output are there.","breaks_test_case":"none","file":"/var/home/sh4i_yurei/Documents/Second_Brain/20_Buildlogs/global-development-workflow/global-development-workflow-log.md","line":2409,"evidence":"The 19:35 entry says 'It ran 36 tests and failed 9 assertions' and quotes only `unknown file key labels` and `FAILED (failures=9)`. The build handoff's step 1 says 'paste the failing output into the item's buildlog entry'. The fragments do agree with the code: 9 failing assertions matches the 9 new cases and subtests that need the labels key, and the no-labels case passed. The live dry-run output in the 19:53 entry matches the done-when exactly: `\"labels\": [\"type:chore\", \"scope:ci\", \"tech-debt\", \"debt:code\", \"debt:accidental\"]`. I confirmed independently that HEAD is 6553ca514c25898e807bb917f0361dbd5e0012d3, that it equals origin/feature/issue-labels, and that the tree is clean. The full check on it exits 0 with '308/308 passed', 'round 3 regressions passed', and Ran 21/36/27/11 tests, all OK."}]}
```

Verdict: changes_required. Cost: $1.293298.

- Blocking, `pyproject.toml:8`: The stacked mutation setup patches provide no mutation evidence. Breaks test case: none.
- Non-blocking, `tools/workflow/issue.py:298`: The changed `open_issue` code has no mutation evidence; an in-process harness needs a scope decision. Breaks test case: none.
- Non-blocking, `tools/workflow/issue.py:298`: Label checks are split between `validate()` and `open_issue()`. Breaks test case: none.
- Non-blocking, `global-development-workflow-log.md:2409`: The red run was paraphrased instead of pasted. Breaks test case: none.
