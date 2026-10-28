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

# G9a issue labels, review round 2

## Request

Review the round-1 blocking finding and its fix for G9a Extra labels when opening an issue, claude-config #23. The worktree is `~/Documents/worktrees/claude-config-g9a`, branch `feature/issue-labels`, pushed commit `dcd4a7e58efee2bbd0919fc809920c225173e779`. The round-1 verdict is in [[2026-10-26-codex-to-claude-workflow-g9a-issue-labels-review-1]]. The governing handoff is [[2026-10-26-claude-to-codex-workflow-g9a-issue-labels]], including its added TEST CASES, and the project note's decision 39 authorizes the in-process harness.

Changed files in this fix commit: `tests/test_issue_open.py`, `tools/workflow/issue.py`, and `pyproject.toml`. The copied `pyproject.toml` and mutation exclusion are removed. The open tests call `issue_tool.main()` in-process with fake `gh` and copied configuration; only the missing-PyYAML test remains a subprocess. Labels checks live in `validate()` now. The buildlog contains the full reproduced failing-first output. The fresh `mutmut run` completed 1318/1318 with 1132 killed, zero no-tests, and 186 survivors; all mutants on G9a's changed lines were killed, including `x_validate__mutmut_17` and `_18`, `_168` through `_193`, and `x_open_issue__mutmut_62` through `_77` and `_203` through `_224`.

The repository has no root CI workflow. On pushed SHA `dcd4a7e58efee2bbd0919fc809920c225173e779`, the full check ran locally in `dev` from the worktree: `for test in tests/test_*.py; do /usr/bin/python3 "$test" || exit 1; done; git diff --check`. It exited 0. Its final output was:

```text
308/308 passed
round 3 regressions passed
Ran 21 tests in 1.084s
OK
Ran 38 tests in 5.968s
OK
Ran 27 tests in 9.557s
OK
Ran 11 tests in 68.326s
OK
```

Verify each earlier blocking finding's fix and check for regressions, rather than reviewing everything again. Review against every TEST CASES bullet, decisions 27, 28, 38 and 39, and the `issue.py` and `config.py` rows of `ARCHITECTURE.md`. Before assigning severity, check each finding against every test case: breaking a stated case is blocking, regardless of size. A design chosen because it was quicker to build, or a problem fixed by stacking patches, is blocking. Confirm the local full check output is for the pushed SHA, since there is no root CI. Check responsibilities and prohibitions in `ARCHITECTURE.md`; APIs, flags, configuration keys, imports and document references against their pinned or installed versions; and the buildlog against code and real output. Treat tests of implementation detail as defects. Return `pass` when no finding is blocking. Give every finding blocking or non-blocking severity, file, line, evidence, and the exact TEST CASES bullet it breaks or `none`.

## Response

```json
{"repo":"sh4i-yurei/claude-config","issue":23,"item":"G9a Extra labels when opening an issue","verdict":"pass","cost":0.9571295999999998,"findings":[{"severity":"non_blocking","summary":"The missing-PyYAML test now has to know mutmut's folder layout. When the test file sits in a folder named 'mutants', it runs the issue.py one level up instead of the copy beside the tests. This replaces round 1's '-k' exclusion, so it is not a stacked patch, and it changes no assertion. But it ties a behaviour test to the mutation tool's folder name, and it would pick the wrong script if the repository were ever checked out into a folder called 'mutants'. A design that doesn't depend on the tool would make yaml impossible to import directly, for example with a PYTHONPATH folder whose yaml module raises ImportError, instead of hiding the user site-packages folder, which also hides mutmut.","breaks_test_case":"none","file":"tests/test_issue_open.py","line":614,"evidence":"tests/test_issue_open.py:611 sets `PYTHONNOUSERSITE=1`, and :614 has `source_root = ROOT.parent if ROOT.name == \"mutants\" else ROOT`. The buildlog's 20:22 UTC entry gives the reason: 'That subprocess hid the user site to test the missing PyYAML message, and it also hid mutmut from the instrumented issue.py copy.' The TEST CASES bullet 'WHEN tests/test_issue_open.py runs, THEN every test except test_missing_pyyaml_names_dependency calls issue.py's main in the test's own process' still holds, because this is the one test the bullet exempts."}]}
```

Verdict: pass. Cost: $0.9571295999999998.

- Nonblocking, `tests/test_issue_open.py:614`: the dependency test recognizes mutmut's `mutants` directory. Breaks test case: none. Claude will file this as tech debt.
