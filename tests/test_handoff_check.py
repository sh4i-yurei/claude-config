import json
import io
import os
from pathlib import Path
import runpy
import subprocess
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
    env = dict(os.environ)
    env["HANDOFF_CHECK_ROOT"] = str(handoffs or HANDOFFS)
    env["HANDOFF_BUILD_TEMPLATE"] = str(template or TEMPLATE)
    result = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout else {}
    return output.get("permissionDecisionReason", ""), output.get(
        "additionalContext", result.stderr
    )


class HandoffCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.complete = BUILD.read_text()

    def test_complete_real_handoff_and_json_schema_pass(self):
        self.assertEqual(run_hook(BUILD, self.complete), ("", ""))

    def test_missing_section_is_named(self):
        changed = self.complete.replace("CI GATE, before Claude's review", "CI work", 1)
        reason, warning = run_hook(BUILD, changed)
        self.assertEqual(reason, "Missing section: CI GATE, before Claude's review")
        self.assertEqual(warning, "")

    def test_placeholders_are_quoted_and_template_is_denied(self):
        reason, _ = run_hook(
            BUILD,
            self.complete.replace(
                "# Global development workflow", "# {{Project}} and {{item}}", 1
            ),
        )
        self.assertEqual(
            reason, "Unfilled placeholder: {{Project}}\nUnfilled placeholder: {{item}}"
        )
        reason, _ = run_hook(BUILD, TEMPLATE.read_text())
        self.assertEqual(
            reason,
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
        reason, _ = run_hook(OLD, OLD.read_text())
        self.assertEqual(
            reason,
            "Invalid test case: - The existing tests in ansible/tests pass unchanged in a ne\n"
            "Invalid test case: - Every branch of every function in ansible/filter_plugins a\n"
            "Invalid test case: - The floor ends at 100 with no unexplained surviving mutant",
        )
        self.assertEqual(run_hook(REVIEW, REVIEW.read_text()), ("", ""))

    def test_unrelated_path_passes_without_reading(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            missing = Path(directory) / "missing-template.md"
            self.assertEqual(
                run_hook(ROOT / "README.md", "{{unfilled}}", template=missing), ("", "")
            )

    def test_unreadable_template_warns_and_allows(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            missing = Path(directory) / "missing-template.md"
            reason, warning = run_hook(BUILD, self.complete, template=missing)
            self.assertEqual(reason, "")
            self.assertEqual(warning, f"Warning: cannot read template {missing}")

    def test_new_template_section_is_required(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            template = Path(directory) / "template.md"
            template.write_text(
                TEMPLATE.read_text().replace("THE ITEM\n", "NEW SECTION\nTHE ITEM\n", 1)
            )
            self.assertEqual(
                run_hook(BUILD, self.complete, template=template)[0],
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
        self.assertEqual(
            run_hook(BUILD, self.complete + "\n${{ matrix.python }}\n"), ("", "")
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


if __name__ == "__main__":
    unittest.main()
