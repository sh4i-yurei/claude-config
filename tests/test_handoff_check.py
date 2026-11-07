import contextlib
import importlib.util
import json
import io
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks/handoff-check.py"
FIXTURES = ROOT / "tests/fixtures"
HANDOFFS = FIXTURES / "handoffs"
TEMPLATE = FIXTURES / "handoff-codex-build.md"
BUILD = HANDOFFS / "2026-10-22-claude-to-codex-workflow-w2-handoff-check.md"
OLD = HANDOFFS / "2026-10-22-claude-to-codex-testing-2.1-infra-python.md"
REVIEW = HANDOFFS / "2026-10-22-codex-to-claude-testing-1r-plumbing-review-1.md"
SPEC = importlib.util.spec_from_file_location("hooks.handoff-check", HOOK)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
GOOD_FACT = (
    "- The hook reads the template on each call. "
    "Evidence: hooks/handoff-check.py line 139."
)


@contextlib.contextmanager
def handoff_folder():
    """Yield an empty temporary handoffs folder inside the repository."""
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        folder = Path(directory) / "handoffs"
        folder.mkdir()
        yield folder


def call_hook(stdin_text, *, template=None, handoffs=None):
    """Run the hook in-process on raw stdin; return its exit code, stdout and stderr."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch.object(CHECK, "HANDOFFS", Path(handoffs or HANDOFFS).resolve()),
        patch.object(CHECK, "TEMPLATE", Path(template or TEMPLATE)),
        patch.object(sys, "stdin", io.StringIO(stdin_text)),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        returned = CHECK.main()
    return returned, stdout.getvalue(), stderr.getvalue()


def write_event(path, content):
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(path), "content": content},
    }


def run_hook(
    path,
    content=None,
    *,
    tool="Write",
    old=None,
    new=None,
    all=False,
    template=None,
    handoffs=None,
):
    fields = {"file_path": str(path)}
    if tool == "Write":
        fields["content"] = content
    else:
        fields.update(old_string=old, new_string=new, replace_all=all)
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": fields}
    returned, printed, errors = call_hook(
        json.dumps(event), template=template, handoffs=handoffs
    )
    assert returned == 0, errors
    output = json.loads(printed)["hookSpecificOutput"] if printed else {}
    return output.get("permissionDecisionReason", ""), output.get(
        "additionalContext", errors
    )


class HandoffCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.complete = BUILD.read_text()

    def test_complete_real_handoff_and_json_schema_pass(self):
        with handoff_folder() as folder:
            self.assertEqual(
                run_hook(folder / BUILD.name, self.complete, handoffs=folder),
                ("", ""),
            )

    def test_missing_section_is_named(self):
        changed = self.complete.replace("CI GATE, before Claude's review", "CI work", 1)
        reason, warning = run_hook(BUILD, changed)
        self.assertEqual(reason, "Missing section: CI GATE, before Claude's review")
        self.assertEqual(warning, "")

    def test_placeholders_are_quoted_and_template_is_denied(self):
        with handoff_folder() as folder:
            new = folder / BUILD.name
            reason, _ = run_hook(
                new,
                self.complete.replace(
                    "# Global development workflow", "# {{Project}} and {{item}}", 1
                ),
                handoffs=folder,
            )
            template_reason, _ = run_hook(new, TEMPLATE.read_text(), handoffs=folder)
        self.assertEqual(
            reason, "Unfilled placeholder: {{Project}}\nUnfilled placeholder: {{item}}"
        )
        self.assertEqual(
            template_reason,
            "Branch line is missing or unfilled\n"
            "Unfilled placeholder: {{Project}}\n"
            "Unfilled placeholder: {{item}}\n"
            "Unfilled placeholder: {{what it builds}}\n"
            "Unfilled placeholder: {{item}}\n"
            "Unfilled placeholder: {{project}}\n"
            "Unfilled placeholder: {{working directory}}\n"
            "Unfilled placeholder: {{working directory: ~/Documents/<repository>, or the worktree ~/Documents/worktrees/<name> Claude created}}\n"
            "Unfilled placeholder: {{owner/repository #N}}\n"
            "Unfilled placeholder: {{Paths that belong to other work, which you leave alone and tell reviewers to ignore.}}\n"
            "Unfilled placeholder: {{domain}}\n"
            "Unfilled placeholder: {{project}}\n"
            "Unfilled placeholder: {{slug}}\n"
            "Unfilled placeholder: {{slug}}\n"
            "Unfilled placeholder: {{branch}}\n"
            "Unfilled placeholder: {{branch}}\n"
            "Unfilled placeholder: {{branch}}\n"
            "Unfilled placeholder: {{Claude writes these before posting, and checks each against the pre-handoff checklist in codex-build-loop: - real inputs: actual files, actual tool output, actual diffs, never shapes invented for the test; - the form WHEN <input or condition>, THEN <exact observable result>; - where it runs: CI or local, and nothing that depends on local state such as a .venv or a cache; - ask, don't copy: where an authoritative tool exists, the design calls it rather than copying its behaviour. Each case is one bullet: an input, the exact expected result and the conditions it runs under. Instructions about the cases, such as which fixtures to use, where they run and what to read first, go in plain paragraphs, never as bullets, so every bullet is a case.}}\n"
            "Handoff has no test cases",
        )

    def test_multiline_placeholder_is_one_problem(self):
        changed = self.complete.replace(
            "TEST CASES\n", "TEST CASES\n{{first  \n   second}}\n", 1
        )
        self.assertEqual(
            run_hook(BUILD, changed),
            ("Unfilled placeholder: {{first second}}", ""),
        )

    def test_section_heading_inside_placeholder_is_missing(self):
        changed = self.complete.replace("TEST CASES\n", "{{\nTEST CASES\n}}\n", 1)
        self.assertEqual(
            run_hook(BUILD, changed),
            ("Missing section: TEST CASES\nUnfilled placeholder: {{ TEST CASES }}", ""),
        )

    def test_branch_missing_and_unfilled(self):
        line = "- Branch: stay on feature/handoff-check."
        self.assertEqual(
            run_hook(BUILD, self.complete.replace(line, "", 1))[0],
            "Branch line is missing or unfilled",
        )
        self.assertEqual(
            run_hook(
                BUILD,
                self.complete.replace(line, "- Branch: stay on feature/{name}.", 1),
            )[0],
            "Branch line is missing or unfilled",
        )

    def test_cases_bullets_and_paragraphs(self):
        start = self.complete.index("TEST CASES\n", self.complete.index("## Request"))
        bullet = self.complete.index("- WHEN", start)
        changed = (
            self.complete[:bullet]
            + "A plain paragraph is permitted.\n"
            + self.complete[bullet:]
        )
        self.assertEqual(run_hook(BUILD, changed), ("", ""))
        changed = self.complete[:bullet] + self.complete[bullet:].replace(
            "- WHEN", "- IF", 1
        )
        self.assertEqual(
            run_hook(BUILD, changed)[0],
            "Invalid test case: - IF the tests run, THEN they read only fixture copies insid",
        )
        end_of_first = self.complete.index("\n", bullet)
        changed = (
            self.complete[:bullet]
            + self.complete[bullet:end_of_first].replace(", THEN", ", SO")
            + self.complete[end_of_first:]
        )
        self.assertEqual(
            run_hook(BUILD, changed)[0],
            "Invalid test case: - WHEN the tests run, SO they read only fixture copies insid",
        )
        end = self.complete.index("\nReal inputs:", bullet)
        changed = (
            self.complete[:bullet]
            + "The test cases will be added later.\n"
            + self.complete[end:]
        )
        self.assertEqual(run_hook(BUILD, changed)[0], "Handoff has no test cases")

    def test_multiple_problems_follow_template_order(self):
        changed = self.complete.replace("CI GATE, before Claude's review", "CI work", 1)
        changed = changed.replace("- Branch: stay on feature/handoff-check.", "", 1)
        changed = changed.replace("- WHEN Claude's Write", "- IF Claude's Write", 1)
        self.assertEqual(
            run_hook(BUILD, changed)[0],
            "Missing section: CI GATE, before Claude's review\n"
            "Branch line is missing or unfilled\n"
            "Invalid test case: - IF Claude's Write tool writes a file under 05_Agents/hando",
        )

    def test_edit_checks_resulting_file(self):
        heading = "CI GATE, before Claude's review"
        self.assertEqual(
            run_hook(BUILD, tool="Edit", old=heading, new="CI work")[0],
            "Missing section: CI GATE, before Claude's review",
        )
        self.assertEqual(
            run_hook(BUILD, tool="Edit", old="## Response", new="## Response\nDone")[0],
            "",
        )
        repeated = "Goal: finish item W2"
        self.assertEqual(
            run_hook(
                BUILD, tool="Edit", old=repeated, new="Goal: finish item W2", all=True
            )[0],
            "",
        )
        self.assertEqual(
            run_hook(
                BUILD,
                tool="Edit",
                old="- Branch: stay on feature/handoff-check.",
                new="- Branch: stay on {branch}.",
                all=True,
            )[0],
            "Branch line is missing or unfilled",
        )

    def test_older_and_review_handoffs_pass(self):
        with handoff_folder() as folder:
            reason, _ = run_hook(folder / OLD.name, OLD.read_text(), handoffs=folder)
            self.assertEqual(
                reason,
                "Invalid test case: - The existing tests in ansible/tests pass unchanged in a ne\n"
                "Invalid test case: - Every branch of every function in ansible/filter_plugins a\n"
                "Invalid test case: - The floor ends at 100 with no unexplained surviving mutant",
            )
            self.assertEqual(
                run_hook(folder / REVIEW.name, REVIEW.read_text(), handoffs=folder),
                ("", ""),
            )

    def test_unrelated_path_passes_without_reading(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            missing = Path(directory) / "missing-template.md"
            self.assertEqual(
                run_hook(ROOT / "README.md", "{{unfilled}}", template=missing), ("", "")
            )

    def test_unreadable_template_warns_and_allows(self):
        with handoff_folder() as folder:
            missing = folder.parent / "missing-template.md"
            reason, warning = run_hook(
                folder / BUILD.name, self.complete, template=missing, handoffs=folder
            )
            self.assertEqual(reason, "")
            self.assertEqual(warning, f"Warning: cannot read template {missing}")

    def test_new_template_section_is_required(self):
        with handoff_folder() as folder:
            template = folder.parent / "template.md"
            template.write_text(
                TEMPLATE.read_text().replace("THE ITEM\n", "NEW SECTION\nTHE ITEM\n", 1)
            )
            self.assertEqual(
                run_hook(
                    folder / BUILD.name,
                    self.complete,
                    template=template,
                    handoffs=folder,
                )[0],
                "Missing section: NEW SECTION",
            )

    def test_section_boundary_excludes_later_bullets(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            template = Path(directory) / "template.md"
            template.write_text(
                TEMPLATE.read_text().replace(
                    "\n```\n\n## Response",
                    "\nLATER SECTION\n- An ordinary instruction.\n```\n\n## Response",
                    1,
                )
            )
            content = self.complete.replace(
                "\n```\n\n## Response",
                "\nLATER SECTION\n- An ordinary instruction.\n```\n\n## Response",
                1,
            )
            self.assertEqual(run_hook(BUILD, content, template=template), ("", ""))

    def test_branch_empty_prose_and_section_independent(self):
        line = "- Branch: stay on feature/handoff-check."
        for replacement in ("- Branch: stay on .", "- Branch: stay on . More text"):
            self.assertEqual(
                run_hook(BUILD, self.complete.replace(line, replacement, 1))[0],
                "Branch line is missing or unfilled",
            )
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            template = Path(directory) / "template.md"
            template.write_text(
                TEMPLATE.read_text().replace("WORKING TREE", "BRANCH DETAILS")
            )
            changed = self.complete.replace("WORKING TREE", "BRANCH DETAILS")
            self.assertEqual(run_hook(BUILD, changed, template=template), ("", ""))
            self.assertEqual(
                run_hook(BUILD, changed.replace(line, "", 1), template=template)[0],
                "Branch line is missing or unfilled",
            )

    def test_wrapped_bullet_and_actions_expression(self):
        case = "- WHEN the content contains an unfilled double-brace placeholder, such as the template's branch placeholder, THEN"
        changed = self.complete.replace(
            case, case.replace(", THEN", "\n  continued, THEN"), 1
        )
        self.assertEqual(run_hook(BUILD, changed), ("", ""))
        with handoff_folder() as folder:
            self.assertEqual(
                run_hook(
                    folder / BUILD.name,
                    self.complete + "\n${{ matrix.python }}\n",
                    handoffs=folder,
                ),
                ("", ""),
            )

    def test_quoted_frontmatter_and_crlf(self):
        broken = self.complete.replace("CI GATE, before Claude's review", "CI work", 1)
        quoted = broken.replace(
            "template: handoff-codex-build", "template: 'handoff-codex-build'"
        )
        self.assertEqual(
            run_hook(BUILD, quoted)[0],
            "Missing section: CI GATE, before Claude's review",
        )
        self.assertEqual(
            run_hook(BUILD, broken.replace("\n", "\r\n"))[0],
            "Missing section: CI GATE, before Claude's review",
        )

    def test_placeholder_order_with_section_problems(self):
        changed = self.complete.replace(
            "- Branch: stay on feature/handoff-check.", "", 1
        )
        changed = changed.replace("THE ITEM\n", "THE ITEM\n{{early}}\n", 1)
        changed = changed.replace("CI GATE, before Claude's review", "CI work", 1)
        changed = changed.replace("TEST CASES\n", "TEST CASES\n{{late}}\n", 1)
        self.assertEqual(
            run_hook(BUILD, changed)[0],
            "Missing section: CI GATE, before Claude's review\nBranch line is missing or unfilled\nUnfilled placeholder: {{early}}\nUnfilled placeholder: {{late}}",
        )

    def test_grouped_problems_with_crlf_and_adjacent_invalid_case(self):
        changed = self.complete.replace("WORKING TREE\n", "BRANCH DETAILS\n", 1)
        changed = changed.replace("CI GATE, before Claude's review", "CI work", 1)
        changed = changed.replace("- Branch: stay on feature/handoff-check.", "", 1)
        changed = changed.replace(
            "- WHEN Claude's Write", "{{before}}\n- IF Claude's Write", 1
        )
        changed = changed.replace("TEST CASES\n", "TEST CASES\n{{after}}\n", 1)
        self.assertEqual(
            run_hook(BUILD, changed.replace("\n", "\r\n"))[0],
            "Missing section: WORKING TREE\n"
            "Missing section: CI GATE, before Claude's review\n"
            "Branch line is missing or unfilled\n"
            "Unfilled placeholder: {{after}}\n"
            "Unfilled placeholder: {{before}}\n"
            "Invalid test case: - IF Claude's Write tool writes a file under 05_Agents/hando",
        )

    def test_branch_name_ends_at_sentence_period(self):
        line = "- Branch: stay on feature/handoff-check."
        self.assertEqual(
            run_hook(
                BUILD,
                self.complete.replace(line, "- Branch: stay on my branch name.", 1),
            ),
            ("Branch line is missing or unfilled", ""),
        )
        self.assertEqual(
            run_hook(
                BUILD,
                self.complete.replace(
                    line,
                    "- Branch: stay on chore/ci-and-coverage. Create or switch to no other branch.",
                    1,
                ),
            ),
            ("", ""),
        )
        self.assertEqual(
            run_hook(
                BUILD, self.complete.replace(line, "- Branch: stay on release/1.2.", 1)
            ),
            ("", ""),
        )

    def test_unrelated_edit_does_not_read(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            unreadable = Path(directory) / "a-directory.md"
            unreadable.mkdir()
            self.assertEqual(
                run_hook(unreadable, tool="Edit", old="a", new="b"), ("", "")
            )
            event = {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(unreadable),
                    "old_string": "a",
                    "new_string": "b",
                },
            }
            with (
                patch.dict(os.environ, {"HANDOFF_CHECK_ROOT": str(HANDOFFS)}),
                patch.object(sys, "stdin", io.StringIO(json.dumps(event))),
                patch.object(
                    Path, "read_text", side_effect=AssertionError("file was read")
                ),
            ):
                hook = runpy.run_path(str(HOOK), run_name="handoff_check_test")
                self.assertEqual(hook["main"](), 0)

    def test_replace_all_decides_the_edit_result(self):
        repeated = "then CI GATE, then CLAUDE REVIEW"
        placeholder = "Unfilled placeholder: {{next steps}}"
        self.assertEqual(
            run_hook(BUILD, tool="Edit", old=repeated, new="{{next steps}}"),
            (placeholder, ""),
        )
        self.assertEqual(
            run_hook(BUILD, tool="Edit", old=repeated, new="{{next steps}}", all=True),
            (f"{placeholder}\n{placeholder}", ""),
        )

    def test_deny_and_warning_print_the_hook_schema(self):
        broken = self.complete.replace("CI GATE, before Claude's review", "CI work", 1)
        self.assertEqual(
            call_hook(json.dumps(write_event(BUILD, broken))),
            (
                0,
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": "Missing section: CI GATE, before Claude's review",
                        }
                    }
                )
                + "\n",
                "",
            ),
        )
        with handoff_folder() as folder:
            missing = folder.parent / "missing-template.md"
            event = write_event(folder / BUILD.name, self.complete)
            self.assertEqual(
                call_hook(json.dumps(event), template=missing, handoffs=folder),
                (
                    0,
                    json.dumps(
                        {
                            "hookSpecificOutput": {
                                "hookEventName": "PreToolUse",
                                "additionalContext": f"Warning: cannot read template {missing}",
                            }
                        }
                    )
                    + "\n",
                    "",
                ),
            )

    def test_malformed_and_other_tool_events_are_allowed_silently(self):
        heading_edit = {
            "file_path": str(BUILD),
            "old_string": "CI GATE, before Claude's review",
            "new_string": "CI work",
        }
        events = {
            "not JSON": "not json",
            "tool input is a list": json.dumps(
                {"tool_name": "Write", "tool_input": [str(BUILD)]}
            ),
            "another tool": json.dumps(
                {"tool_name": "MultiEdit", "tool_input": heading_edit}
            ),
            "file path is a number": json.dumps(
                {"tool_name": "Write", "tool_input": {"file_path": 7}}
            ),
        }
        for name, stdin_text in events.items():
            with self.subTest(name):
                self.assertEqual(call_hook(stdin_text), (0, "", ""))

    def test_edit_without_new_string_or_target_is_allowed(self):
        self.assertEqual(
            run_hook(BUILD, tool="Edit", old="CI GATE, before Claude's review"),
            ("", ""),
        )
        with handoff_folder() as folder:
            self.assertEqual(
                run_hook(
                    folder / BUILD.name,
                    tool="Edit",
                    old="CI GATE, before Claude's review",
                    new="CI work",
                    handoffs=folder,
                ),
                ("", ""),
            )

    def test_new_build_handoff_without_request_is_checked_in_full(self):
        heading = self.complete[: self.complete.index("## Request")]
        with handoff_folder() as folder:
            self.assertEqual(
                run_hook(folder / BUILD.name, heading, handoffs=folder),
                (
                    "Missing section: WHICH SESSION THIS IS\n"
                    "Missing section: WORKING TREE\n"
                    "Missing section: THE ITEM\n"
                    "Missing section: CI GATE, before Claude's review\n"
                    "Missing section: CLAUDE REVIEW\n"
                    "Missing section: EFFICIENCY\n"
                    "Missing section: VAULT BOUNDARY\n"
                    "Missing section: DONE\n"
                    "Missing section: TEST CASES\n"
                    "Branch line is missing or unfilled",
                    "",
                ),
            )

    def test_multiline_placeholder_keeps_following_text_on_its_line(self):
        changed = self.complete.replace(
            "TEST CASES\n", "Notes: {{reviewer\nnotes}}TEST CASES\n", 1
        )
        self.assertEqual(
            run_hook(BUILD, changed),
            ("Unfilled placeholder: {{reviewer notes}}", ""),
        )

    def test_branch_name_with_capital_x_passes(self):
        line = "- Branch: stay on feature/handoff-check."
        self.assertEqual(
            run_hook(
                BUILD, self.complete.replace(line, "- Branch: stay on fix/XSS-gate.", 1)
            ),
            ("", ""),
        )

    def test_case_wrapped_straight_after_its_comma(self):
        case = "- WHEN the content contains an unfilled double-brace placeholder, such as the template's branch placeholder, THEN"
        changed = self.complete.replace(case, case.replace(", THEN", ",\n  THEN"), 1)
        self.assertEqual(run_hook(BUILD, changed), ("", ""))


class FactsAndChangedRequest(unittest.TestCase):
    """Decision 53: check a changed Request, and require evidence on facts."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name) / "handoffs"
        self.folder.mkdir()
        self.build = self.folder / BUILD.name
        shutil.copy(BUILD, self.build)
        self.text = BUILD.read_text()
        self.new = self.folder / "2026-11-07-claude-to-codex-new-handoff.md"
        self.template = Path(directory.name) / "facts-template.md"
        self.template.write_text(
            TEMPLATE.read_text().replace("\nTEST CASES\n", "\nFACTS\n\nTEST CASES\n", 1)
        )

    def run_check(self, path, content=None, *, template=None, **fields):
        return run_hook(
            path,
            content,
            template=template or self.template,
            handoffs=self.folder,
            **fields,
        )

    def with_facts(self, facts):
        return self.text.replace(
            "\nTEST CASES\n", f"\nFACTS\n{facts}\n\nTEST CASES\n", 1
        )

    def test_response_edit_is_allowed(self):
        self.assertEqual(
            self.run_check(
                self.build, tool="Edit", old="## Response", new="## Response\nDone"
            ),
            ("", ""),
        )

    def test_closing_state_edit_is_allowed(self):
        self.assertEqual(
            self.run_check(
                self.build, tool="Edit", old="state: open", new="state: done"
            ),
            ("", ""),
        )

    def test_request_edit_is_checked(self):
        self.assertEqual(
            self.run_check(
                self.build,
                tool="Edit",
                old="Goal: finish item W2",
                new="Goal: finish item W2 now",
            ),
            ("Missing section: FACTS", ""),
        )

    def test_write_outside_request_is_allowed(self):
        self.assertEqual(self.run_check(self.build, self.text + "\nDone.\n"), ("", ""))

    def test_write_changing_request_is_checked(self):
        changed = self.text.replace(
            "Goal: finish item W2", "Goal: finish item W2 now", 1
        )
        self.assertEqual(
            self.run_check(self.build, changed), ("Missing section: FACTS", "")
        )

    def test_write_to_new_path_is_checked(self):
        self.assertEqual(
            self.run_check(self.new, self.text), ("Missing section: FACTS", "")
        )

    def test_fact_without_evidence_is_named(self):
        facts = (
            f"{GOOD_FACT}\n- The hook reads required sections from the "
            "template's Request block on every call."
        )
        self.assertEqual(
            self.run_check(self.new, self.with_facts(facts)),
            (
                "Fact without evidence: - The hook reads required sections "
                "from the template's Reque",
                "",
            ),
        )

    def test_evidence_on_continuation_line_is_allowed(self):
        facts = (
            "- The hook reads the template on each call.\n"
            "  Evidence: hooks/handoff-check.py line 139."
        )
        self.assertEqual(self.run_check(self.new, self.with_facts(facts)), ("", ""))

    def test_empty_evidence_is_refused(self):
        facts = "- The hook reads the template on each call. Evidence:"
        self.assertEqual(
            self.run_check(self.new, self.with_facts(facts)),
            (
                "Fact without evidence: - The hook reads the template on each "
                "call. Evidence:",
                "",
            ),
        )

    def test_facts_paragraph_without_bullets_is_refused(self):
        facts = "These facts were checked on 2026-11-07."
        self.assertEqual(
            self.run_check(self.new, self.with_facts(facts)),
            ("Handoff has no facts", ""),
        )

    def test_template_without_facts_does_not_check_facts(self):
        facts = "- The template has a FACTS section."
        self.assertEqual(
            self.run_check(self.new, self.with_facts(facts), template=TEMPLATE),
            ("", ""),
        )

    def test_fact_and_case_problems_follow_template_order(self):
        content = self.with_facts("- The template has a FACTS section.").replace(
            "\nTEST CASES\n",
            "\nTEST CASES\n- IF something happens, THEN nothing.\n",
            1,
        )
        self.assertEqual(
            self.run_check(self.new, content),
            (
                "Fact without evidence: - The template has a FACTS section.\n"
                "Invalid test case: - IF something happens, THEN nothing.",
                "",
            ),
        )

    def test_unchanged_request_never_reads_template(self):
        missing = self.folder.parent / "missing-template.md"
        self.assertEqual(
            self.run_check(
                self.build,
                tool="Edit",
                old="## Response",
                new="## Response\nDone",
                template=missing,
            ),
            ("", ""),
        )

    def test_unreadable_target_is_checked_in_full(self):
        directory = self.folder / "2026-11-07-claude-to-codex-directory.md"
        directory.mkdir()
        self.assertEqual(
            self.run_check(directory, self.text), ("Missing section: FACTS", "")
        )


if __name__ == "__main__":
    unittest.main()
