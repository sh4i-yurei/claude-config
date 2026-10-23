---
type: note
from: claude
to: codex
state: open
project: "[[Global development workflow]]"
created: 2026-10-22
answered:
tags: [handoff]
template: handoff-codex-build
---

# Global development workflow, W2: build handoffs checked against the template

## Request

```text
Goal: finish item W2 of Global development workflow in ~/Documents/worktrees/claude-config-w2, through Claude's review and a green CI run.

Work only in ~/Documents/worktrees/claude-config-w2, a worktree Claude created from origin/main. Do not touch ~/Documents/claude-config: it is the live configuration that running agents load. Run every command from there, with cd or -C. Issue: sh4i-yurei/claude-config #17.

Spec: ~/Documents/Second_Brain/10_Projects/16_Tooling/Global development workflow.md (read only this item's Next text and the decisions it cites, by line range)
Design: ARCHITECTURE.md in the working directory. Read it before writing code. What you build must fit it; if it can't, write why in the note's Open questions and stop.
Standard: ~/Documents/Second_Brain/40_Reference/testing-standard.md
Record: ~/Documents/Second_Brain/20_Buildlogs/global-development-workflow/global-development-workflow-log.md
This session is fresh and carries nothing from earlier sessions. This handoff, the buildlog and the repository are the whole state. Read the repository's AGENTS.md first: Codex loads it on its own only when it starts inside the repository. Run everything inside the dev container. git over HTTPS works only there, and gh needs eval "$(vault-env)" first, in the same command. Follow the build-from-spec skill and your global rules, with the changes below. Where they conflict, this handoff wins.

WHICH SESSION THIS IS
Each session runs at most one Claude review round and then ends, so no session carries an earlier round's context. Rounds count this handoff's own reviews only, starting at 1.
- If this handoff's Response has no "Round" line, this is the build session: do THE ITEM, then CI GATE, then CLAUDE REVIEW.
- If its Response ends with "Round <N>: changes required", this is a fix session. Skip THE ITEM. Read that round's review handoff, and only its blocking findings. Fix every one; after each fix run the tests that cover it and record it as Saw/Cause/Fix. Run the full check command once, then CI GATE, then CLAUDE REVIEW as round <N+1>.

WORKING TREE
- Branch: stay on feature/handoff-check. Create or switch to no other branch.
- This handoff authorises you to commit and push to that branch, and only that branch. Never push to main, never force-push, and never open, edit or merge a pull request. Commit messages say what changed and why, with no AI attribution. This repository takes no pull request: once the item is done, Claude makes one commit to main with "Closes #17".
- Touch only the files this item needs.

THE ITEM
1. Write the tests first, from TEST CASES below. Run them before writing the code and paste the failing output into the item's buildlog entry. Each test must fail on an assertion about behaviour, never on an import or collection error; create the interface first if the tests need it. Then build until they pass, never weakening a test to pass. Choose the design a careful engineer would choose with unlimited time; if a fix needs a second patch, redesign instead.
2. While building, run only the tests that cover the change. Run the full check command once before the done-when, then the done-when itself, and keep its real output.
3. Write one buildlog entry with the done-when output, plus a Saw/Cause/Fix entry for each real failure. Don't tick the item yet: that happens in DONE.
- Before using a tool, read its documentation through ~/.claude/skills/research/scripts/lookup.py (repo or docs), not from memory. Check every API, flag, configuration key and import against that documentation or the installed version before you use it.
- If the spec contradicts itself or is ambiguous, write the question in the note's Open questions and stop the item there. Never guess what was meant.
- Add no dependency, tool, library or pattern this handoff doesn't name. Never change a shared interface, file format or another piece's behaviour unless a test case says to. Respect what ARCHITECTURE.md says each piece must not do.
- Where existing code is being given tests, the tests describe what it does today, with exact values. Where today's behaviour looks wrong, don't change it: put it in Open questions with the evidence.
- A mutation run counts only when it finished every mutant and reflects the current code and tests: a fresh run, or one where the mutation tool's own cache invalidation reran every mutant a source or test change affects. Never judge freshness by comparing file timestamps, and never treat a partial or stale run as a pass. Give it a time limit long enough to finish in one call.
- A survivor may be explained only when no test could kill it. If a test could, write the test.
- Make live network requests only when a done-when requires one.

CI GATE, before Claude's review
1. CI must run on a push to any branch. If this repository has CI but it runs only on pull requests or on main, add a push trigger for every branch in your first commit, with a test that checks the trigger.
2. Commit the work and push it with git push -u origin feature/handoff-check, naming the branch every time. Never a bare git push.
3. Wait for that commit's CI run in one call: find it with gh run list --branch feature/handoff-check --commit <sha> --limit 1, then gh run watch <id> --exit-status, with a time limit long enough to finish.
4. If CI fails, read only the failing step's log (gh run view <id> --log-failed | tail -60), fix the cause, record Saw/Cause/Fix, commit and push again. Never ask for review on a red or unfinished run.
5. If the repository has no CI at all and this item doesn't add it, skip steps 1, 3 and 4: still commit and push the branch, run the full check command locally on that commit, and say in the review request that the repository has no CI yet, with that output.

CLAUDE REVIEW
1. Post a review handoff from Codex to Claude at 05_Agents/handoffs/<date>-codex-to-claude-<this handoff's slug>-review-<round>.md, from ~/Documents/Second_Brain/_Templates/handoff.md. Its Request gives the item, its files, the pushed commit SHA, the green CI run's URL and the final check output. It asks Claude to:
   - review the code against this handoff's test cases, the decisions they cite and the repository's ARCHITECTURE.md;
   - before deciding any finding's severity, check it against every TEST CASES bullet: a finding that shows the code breaking a stated case is blocking, however small it looks. Also blocking: any design chosen because it was quicker to build, and any problem fixed by stacking patches;
   - where the repository has CI, confirm with gh run view that the run at that URL is green and ran on that SHA, and treat it as blocking if not; where it has none, confirm the local full check output is for that SHA;
   - check the code against what ARCHITECTURE.md says each piece it touches must and must not do;
   - check for hallucinations, each one blocking: APIs, flags, configuration keys or imports that don't exist at the pinned version, and references to documents that don't exist;
   - treat a test that pins implementation detail instead of behaviour as a defect;
   - check the buildlog entry against the code and the real output;
   - from round 2 on, verify each earlier blocking finding's fix and check for regressions instead of reviewing everything again;
   - return a verdict and findings marked blocking or non-blocking, with file, line and evidence. The verdict is pass whenever no finding is blocking.
2. Run it inside dev from the repository in one call:
   eval "$(vault-env)"; claude -p "Read ~/Documents/Second_Brain/05_Agents/handoffs/<review file>.md and carry out its Request." --output-format json --json-schema '{"type":"object","required":["verdict","findings"],"properties":{"verdict":{"enum":["pass","changes_required"]},"findings":{"type":"array","items":{"type":"object","required":["severity","summary","breaks_test_case"],"properties":{"severity":{"enum":["blocking","non_blocking"]},"breaks_test_case":{"type":"string","description":"the TEST CASES bullet this finding shows broken, quoted exactly, or none"},"file":{"type":"string"},"line":{"type":"integer"},"summary":{"type":"string"},"evidence":{"type":"string"}}}}}}' --add-dir ~/Documents/Second_Brain --allowedTools "Read,Grep,Glob,Bash(git diff:*),Bash(git log:*),Bash(git show:*),Bash(git status:*),Bash(gh run view:*),Bash(<full check command>:*)" --disallowedTools "Edit,Write,NotebookEdit,WebFetch,WebSearch" --settings '{"disableAllHooks": true}' | jq -c '{verdict: .structured_output.verdict, cost: .total_cost_usd, findings: .structured_output.findings}'
   Replace <full check command> with the full check command you ran. If it hits a usage limit, wait for the reset in one call and run the same request again.
3. Write the verdict, cost and one line per finding into the review handoff's Response, including the test case each one breaks, and set it done. Write one buildlog entry with the round, verdict and cost.
4. List non-blocking findings in the buildlog, and put any that need a decision in Open questions. Claude files the rest as tech debt.
5. Any finding whose breaks_test_case is not "none" is blocking, whatever its severity says. If any finding is blocking, add one line to this handoff's Response: "Round <N>: changes required, see [[<review file without .md>]]". Leave this handoff's state open and end the session. Do not start the fixes: a fresh session does them. If no finding is blocking, go to DONE.

EFFICIENCY
- Never wait in a loop. Give slow commands a time limit long enough to finish in one call, and keep only the summary or the last lines.
- One patch per change across the files it touches. Do not run the formatter yourself.
- Keep output short: quiet flags, tail, grep for failures. Find code with rg -n and read only the function you need. Never cat a whole vault note.
- Get the time with date inside a command you are already running.
- Create no files outside this item's work and 05_Agents/handoffs. The one exception is the lookup tool's own records under 70_Research/_lookups, which it saves by itself: they are the research record, so never delete or edit them.

VAULT BOUNDARY
In the vault you edit only the project note, its buildlog and handoffs in 05_Agents/handoffs. Do not change the note's status or move it. Never delete anything in the vault, including the lookup records in 70_Research/_lookups.

DONE
The item has passed Claude's review, and CI is green on the reviewed commit, or, in a repository with no CI yet, the full check command passed locally on that commit. Only now tick the item in the note if it is a Next item, and rewrite Where it stands. Write the summary into this handoff's Response, below any Round lines, with the commit SHA and the CI run's URL if there is one, and set its state to done.

TEST CASES
Added by Claude after review round 1. In the round 2 fix session, fix both blocking findings of 05_Agents/handoffs/2026-10-23-codex-to-claude-workflow-w2-handoff-check-review-1.md, and these of its non-blocking findings, two of which contradict the cases below: the order of problems, the empty Branch name, the Branch check tied to one section name, wrapped bullets, quoted frontmatter values and CRLF line endings, the warning channel, the Edit no-read test, and exact-value assertions. Settled by Claude: a double-brace expression that starts with a dollar sign, as in GitHub Actions syntax, is not a template placeholder.
- WHEN the tests run, THEN they read only fixture copies inside the repository, never files in the live vault, and the hook takes its handoff root and template path from arguments or environment variables so a test can point it at a temporary folder.
- WHEN the TEST CASES section is followed by other text before the end of the Request block, THEN only bullets inside TEST CASES are judged; the section ends at the next section name or the closing fence of the Request block.
- WHEN a file has several problems, THEN placeholder problems are listed in their place in template order alongside section problems, not after them.
- WHEN the Branch line names no branch, or its name is followed by more text after the period, THEN the hook denies it as missing or unfilled.
- WHEN the Branch line appears anywhere in the Request block, THEN it satisfies the Branch check, whatever the section around it is called.
- WHEN a test case bullet wraps onto following lines before the next bullet or a blank line, THEN the continuation lines count as part of that bullet, so a wrapped THEN is accepted.
- WHEN the content contains a GitHub Actions expression such as ${{ matrix.python }}, THEN it is not a placeholder and the hook allows it.
- WHEN the frontmatter writes the template value in quotes, or the file uses CRLF line endings, THEN the hook still recognises and checks it.
- WHEN the template can't be read, THEN the warning reaches Claude through the hook's documented JSON output, such as additional context, and the write is allowed; read Claude Code's hooks documentation through the lookup tool to choose the field.
- WHEN an Edit targets a path outside 05_Agents/handoffs/, THEN the hook allows it without reading the file, and a test proves no read happens.

- WHEN Claude's Write tool writes a file under 05_Agents/handoffs/ whose frontmatter has template: handoff-codex-build, and the content has every template section, no unfilled double-brace placeholder, a filled "- Branch: stay on <name>." line, and every TEST CASES bullet in the form "WHEN …, THEN …", THEN the hook allows it and prints nothing.
- WHEN that file lacks one section, such as "CI GATE", THEN the hook denies the write with a reason naming that section exactly as the template writes it.
- WHEN the content contains an unfilled double-brace placeholder, such as the template's branch placeholder, THEN the hook denies it and the reason quotes each placeholder found. A placeholder is two opening braces, text, then two closing braces.
- WHEN the content holds the review command's JSON schema, which ends in six closing braces, THEN that is not a placeholder and the hook allows it.
- WHEN the Branch line is missing, or its branch name still contains a brace, THEN the hook denies it and says the Branch line is missing or unfilled.
- WHEN a TEST CASES bullet doesn't begin with "WHEN" or has no ", THEN", THEN the hook denies it and quotes that bullet's first 60 characters.
- WHEN the TEST CASES section holds plain paragraphs between its bullets, THEN they are allowed; only bullets must be WHEN and THEN cases.
- WHEN the TEST CASES section has no bullet at all, THEN the hook denies it and says the handoff has no test cases.
- WHEN a file has several problems, THEN one denial lists every problem, one per line, in the order the template puts its sections.
- WHEN the Edit tool changes such a file, THEN the hook checks the file as it would be after the edit: the current file on disk with old_string replaced by new_string, once, or everywhere when replace_all is true. An edit that completes a file passes; an edit that breaks one is denied.
- WHEN the frontmatter has no template field, as in every older handoff and every Codex review handoff, THEN the hook allows the write and prints nothing, whatever the content.
- WHEN the path isn't under 05_Agents/handoffs/, THEN the hook allows it without reading the file.
- WHEN the template file can't be read, THEN the hook allows the write and prints a warning naming the template path. It is a quality check, not a security control.
- WHEN a new section is added to the template, THEN the hook requires it with no code change: the section names are read from the template's Request block at run time. A section name is a line in that block made of upper-case words, optionally followed by a comma and more text, such as "CI GATE, before Claude's review". A test points the hook at a temporary template to prove it.
Real inputs: the tests use copies of real handoffs as fixtures: _Templates/handoff-codex-build.md itself, which must be denied for its placeholders; 05_Agents/handoffs/2026-10-22-claude-to-codex-testing-2.1-infra-python.md as it is today, which must be denied only for its test cases not being WHEN and THEN; and 05_Agents/handoffs/2026-10-22-codex-to-claude-testing-1r-plumbing-review-1.md, which has no template field and must be allowed.
Where it runs: locally. The tests follow the style of tests/test_git_guard.py and run with python3 tests/test_handoff_check.py. Item 3.1 later moves every test to pytest with coverage and mutation testing, so test every branch with exact values now.
The deny output uses the same PreToolUse decision format as hooks/git-guard.py. Read Claude Code's hooks documentation through the lookup tool to confirm the format and the Write and Edit tool input fields before writing the code.
Don't edit ~/.claude/settings.json: Claude registers the hook there after the item is done. Document the settings entry it needs in README.md, and add the hook's row to ARCHITECTURE.md's pieces table.
```

## Response

Round 1: changes required, see [[2026-10-23-codex-to-claude-workflow-w2-handoff-check-review-1]]
