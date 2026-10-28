from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/issue_debt"
OPEN_FIXTURES = ROOT / "tests/fixtures/issue_open"
sys.path.insert(0, str(ROOT / "tools/workflow"))
sys.path.insert(0, str(ROOT))
import tools.workflow.issue as issue_tool
import config as workflow_config

G6C = "2026-10-27-codex-to-claude-workflow-g6c-board-add-race-review-2.md"
G9A = "2026-10-26-codex-to-claude-workflow-g9a-issue-labels-review-2.md"
ROUND1 = "2026-10-26-codex-to-claude-workflow-g6c-board-add-race-review-1.md"
OLD = "2026-10-17-codex-to-claude-dev-workflow-review-a-1.md"
REPO = "sh4i-yurei/claude-config"


class IssueDebt(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workflow = self.root / "workflow"
        shutil.copytree(ROOT / "tools/workflow", self.workflow)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "gh"
        shutil.copy(OPEN_FIXTURES / "fake_gh.py", fake)
        fake.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            FAKE_GH_CALLS=str(self.root / "calls.jsonl"),
            FAKE_GH_STATE=str(self.root / "state.json"),
            FAKE_GH_FIXTURES=str(OPEN_FIXTURES),
            FAKE_GH_DEBT_FIXTURES=str(FIXTURES),
            PYTHONDONTWRITEBYTECODE="1",
        )
        self.state = {}
        self.save()

    def save(self):
        Path(self.env["FAKE_GH_STATE"]).write_text(json.dumps(self.state))

    def calls(self):
        path = Path(self.env["FAKE_GH_CALLS"])
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def run_command(self, command, path, *options):
        output = io.StringIO()
        with (
            patch.dict(os.environ, self.env),
            patch.object(workflow_config, "DIRECTORY", self.workflow),
            redirect_stdout(output),
        ):
            code = issue_tool.main([command, str(path), *options])
        return code, output.getvalue()

    def run_debt(self, name, *options):
        return self.run_command("debt", FIXTURES / name, *options)

    def derived(self, name, case, transform):
        folder = self.root / case
        folder.mkdir()
        target = folder / name
        text = (FIXTURES / G6C).read_text()
        target.write_text(transform(text))
        return target

    def changed_result(self, case, change):
        def transform(text):
            before, response = text.split("## Response\n", 1)
            block = response.split("```json\n", 1)[1].split("\n```", 1)[0]
            result = json.loads(block)
            change(result)
            return (
                before
                + "## Response\n"
                + response.replace(block, json.dumps(result), 1)
            )

        return self.derived(G6C, case, transform)

    def no_writes(self):
        self.assertFalse(
            any(
                "--method" in call["args"]
                or call["args"][:2]
                in (["project", "item-add"], ["project", "item-edit"])
                for call in self.calls()
            )
        )

    def planned(self, output):
        prefix = f"Would call: POST repos/{REPO}/issues "
        line = next(line for line in output.splitlines() if line.startswith(prefix))
        return json.loads(line.removeprefix(prefix))

    def test_g6c_dry_run_plans_two_findings(self):
        self.state["empty_sub_issues"] = True
        self.save()
        code, output = self.run_debt(G6C, "--dry-run")
        self.assertEqual(code, 0, output)
        create = self.planned(output)
        self.assertEqual(create["title"], "Tech debt from the review of G6c")
        self.assertEqual(create["labels"], ["type:chore", "scope:ci", "tech-debt"])
        self.assertEqual(
            create["body"].split("### Done when\n\n", 1)[1],
            "Each finding above is fixed with a test, or closed in triage with the reason it stays.\n",
        )
        self.assertIn(
            "### Project, step, and reason\n\nNon-blocking findings from G6c's round 2 review of #28, in 05_Agents/handoffs/"
            + G6C
            + ".",
            create["body"],
        )
        changes = (
            create["body"]
            .split("### What changes\n\n", 1)[1]
            .split("\n\n### Done when", 1)[0]
            .splitlines()
        )
        self.assertEqual(len(changes), 2)
        self.assertTrue(changes[0].startswith("- tools/workflow/issue.py:491: "))
        self.assertTrue(changes[1].startswith("- tools/workflow/issue.py:272: "))
        self.assertIn("/issues/28/sub_issues", output)
        self.no_writes()

    def test_debt_uses_the_same_opening_calls_as_a_file(self):
        self.state["empty_sub_issues"] = True
        self.save()
        dry_code, dry_output = self.run_debt(G6C, "--dry-run")
        self.assertEqual(dry_code, 0, dry_output)
        create = self.planned(dry_output)
        self.env["FAKE_GH_CALLS"] = str(self.root / "debt-calls.jsonl")
        code, output = self.run_debt(G6C)
        self.assertEqual(code, 0, output)
        debt_calls = self.calls()
        self.assertEqual(
            debt_calls[0]["args"], ["api", f"repos/{REPO}/issues/28/sub_issues"]
        )
        self.assertEqual(debt_calls[1]["args"], ["api", f"repos/{REPO}/issues/28"])
        self.env["FAKE_GH_CALLS"] = str(self.root / "open-calls.jsonl")
        issue_file = self.root / "same-issue.toml"
        sections = create["body"].strip().split("\n\n### ")
        fields = {}
        for section in sections:
            heading, value = section.removeprefix("### ").split("\n\n", 1)
            fields[
                {
                    "Project, step, and reason": "context",
                    "What changes": "changes",
                    "Done when": "done",
                }[heading]
            ] = value
        issue_file.write_text(
            f'repo = {json.dumps(REPO)}\nkind = "chore"\ntitle = {json.dumps(create["title"])}\n'
            'scope = "scope:ci"\nparent = 28\nlabels = ["tech-debt"]\n\n[body]\n'
            + "".join(f"{key} = {json.dumps(value)}\n" for key, value in fields.items())
        )
        open_code, open_output = self.run_command("open", issue_file)
        self.assertEqual(open_code, 0, open_output)
        self.assertEqual(debt_calls[2:], self.calls())

    def test_existing_g6c_sub_issue_refuses(self):
        code, output = self.run_debt(G6C)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{G6C}: #29 already files this review's leftovers"),
        )
        self.no_writes()

    def test_existing_g9a_sub_issue_refuses(self):
        code, output = self.run_debt(G9A)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{G9A}: #27 already files this review's leftovers"),
        )
        self.no_writes()

    def test_unpassed_review_refuses_without_gh(self):
        code, output = self.run_debt(ROUND1)
        self.assertEqual(
            (code, output.strip()),
            (
                2,
                f"{ROUND1}: the review's verdict is changes_required; only a passed review's leftovers are filed",
            ),
        )
        self.assertEqual(self.calls(), [])

    def test_no_review_result_refuses_without_gh(self):
        code, output = self.run_debt(OLD)
        self.assertEqual(
            (code, output.strip()),
            (
                2,
                f"{OLD}: expected exactly one review result block in Response, found 0",
            ),
        )
        self.assertEqual(self.calls(), [])

    def test_two_review_results_refuse_without_gh(self):
        def repeat(text):
            before, response = text.split("## Response\n", 1)
            block = response.split("```json\n", 1)[1].split("\n```", 1)[0]
            return (
                before
                + "## Response\n"
                + response.replace(
                    "\n```\n", "\n```\n\n```json\n" + block + "\n```\n", 1
                )
            )

        path = self.derived(G6C, "repeated-review-block", repeat)
        code, output = self.run_command("debt", path)
        self.assertEqual(
            (code, output.strip()),
            (
                2,
                f"{G6C}: expected exactly one review result block in Response, found 2",
            ),
        )
        self.assertEqual(self.calls(), [])

    def test_breaking_finding_is_excluded(self):
        def change(text):
            return text.replace(
                '"breaks_test_case":"none"',
                '"breaks_test_case":"- WHEN something breaks"',
                1,
            )

        path = self.derived(G6C, "breaking-first-finding", change)
        self.state["empty_sub_issues"] = True
        self.save()
        code, output = self.run_command("debt", path, "--dry-run")
        self.assertEqual(code, 0, output)
        changes = (
            self.planned(output)["body"]
            .split("### What changes\n\n", 1)[1]
            .split("\n\n### Done when", 1)[0]
            .splitlines()
        )
        self.assertEqual(len(changes), 1)
        self.assertTrue(changes[0].startswith("- tools/workflow/issue.py:272: "))

    def test_no_findings_opens_nothing(self):
        path = self.changed_result(
            "empty-findings", lambda result: result.update(findings=[])
        )
        code, output = self.run_command("debt", path)
        self.assertEqual(
            (code, output.strip()), (0, f"{G6C}: no leftover findings; nothing opened")
        )
        self.no_writes()

    def test_missing_path_exits_two(self):
        path = self.root / "missing.md"
        code, output = self.run_command("debt", path)
        self.assertEqual(code, 2)
        self.assertIn(str(path), output)
        self.assertEqual(self.calls(), [])

    def test_response_stops_at_next_section(self):
        def append_section(text):
            block = (
                text.split("## Response\n", 1)[1]
                .split("```json\n", 1)[1]
                .split("\n```", 1)[0]
            )
            return text + "\n## Another section\n\n```json\n" + block + "\n```\n"

        path = self.derived(G6C, "later-section", append_section)
        code, output = self.run_command("debt", path)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{G6C}: #29 already files this review's leftovers"),
        )

    def test_multiline_review_json_is_accepted(self):
        def multiline(text):
            before, response = text.split("## Response\n", 1)
            block = response.split("```json\n", 1)[1].split("\n```", 1)[0]
            return (
                before
                + "## Response\n"
                + response.replace(block, json.dumps(json.loads(block), indent=2), 1)
            )

        path = self.derived(G6C, "multiline-json", multiline)
        code, output = self.run_command("debt", path)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{G6C}: #29 already files this review's leftovers"),
        )

    def test_invalid_json_and_array_blocks_are_skipped(self):
        for case, block in (("invalid-json", "{oops"), ("array-json", "[]")):
            with self.subTest(case=case):

                def prepend(text):
                    return text.replace(
                        "## Response\n", f"## Response\n\n```json\n{block}\n```\n", 1
                    )

                path = self.derived(G6C, case, prepend)
                code, output = self.run_command("debt", path)
                self.assertEqual(
                    (code, output.strip()),
                    (2, f"{G6C}: #29 already files this review's leftovers"),
                )

    def test_only_json_info_string_counts(self):
        def prepend(text):
            before, response = text.split("## Response\n", 1)
            block = response.split("```json\n", 1)[1].split("\n```", 1)[0]
            return before + "## Response\n```text\n" + block + "\n```\n" + response

        path = self.derived(G6C, "non-json-code-fence", prepend)
        code, output = self.run_command("debt", path)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{G6C}: #29 already files this review's leftovers"),
        )

    def test_exact_required_review_keys_are_accepted(self):
        path = self.changed_result(
            "exact-review-keys", lambda result: result.pop("cost")
        )
        code, output = self.run_command("debt", path)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{G6C}: #29 already files this review's leftovers"),
        )

    def test_invalid_review_fields_refuse_before_gh(self):
        cases = (
            ("missing-item", {"item": ""}),
            ("nontext-item", {"item": None}),
            ("bad-repo", {"repo": "bad"}),
            ("null-repo", {"repo": None}),
            ("zero-issue", {"issue": 0}),
            ("text-issue", {"issue": "28"}),
            ("nonlist-findings", {"findings": {}}),
        )
        for case, changes in cases:
            with self.subTest(case=case):
                path = self.changed_result(case, lambda result: result.update(changes))
                code, output = self.run_command("debt", path)
                self.assertEqual(code, 2, output)
                self.assertTrue(output.startswith(f"{G6C}: "), output)
                self.assertEqual(self.calls(), [])

    def test_issue_one_is_a_valid_parent_number(self):
        path = self.changed_result("issue-one", lambda result: result.update(issue=1))
        code, output = self.run_command("debt", path, "--dry-run")
        self.assertEqual(code, 0, output)
        self.assertIn("issues/1/sub_issues", output)

    def test_malformed_sub_issues_refuse_before_writes(self):
        for case, response in (("object-response", {}), ("null-child", [None])):
            with self.subTest(case=case):
                self.state["sub_issues_response"] = response
                self.save()
                code, output = self.run_debt(G6C, "--dry-run")
                self.assertEqual(code, 2 if case == "object-response" else 0, output)
                if case == "object-response":
                    self.assertEqual(
                        output.strip(), f"{G6C}: GitHub returned invalid sub-issues"
                    )
                self.no_writes()

    def test_invalid_review_filename_refuses(self):
        path = self.root / "invalid-review-name.md"
        path.write_text((FIXTURES / G6C).read_text())
        code, output = self.run_command("debt", path)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{path.name}: expected a -review-<round>.md file name"),
        )
        self.assertEqual(self.calls(), [])

    def test_missing_scope_labels_refuses(self):
        self.state.update(empty_sub_issues=True, remove_issue_labels=True)
        self.save()
        code, output = self.run_debt(G6C, "--dry-run")
        self.assertEqual(
            (code, output.strip()), (2, f"{G6C}: #28 must have one scope label")
        )
        self.no_writes()

    def test_missing_finding_summary_refuses(self):
        path = self.changed_result(
            "missing-summary", lambda result: result["findings"][0].update(summary=None)
        )
        self.state["empty_sub_issues"] = True
        self.save()
        code, output = self.run_command("debt", path, "--dry-run")
        self.assertEqual(
            (code, output.strip()), (2, f"{G6C}: leftover finding has no summary")
        )
        self.no_writes()

    def test_nontext_finding_summary_refuses(self):
        path = self.changed_result(
            "nontext-summary", lambda result: result["findings"][0].update(summary=42)
        )
        self.state["empty_sub_issues"] = True
        self.save()
        code, output = self.run_command("debt", path, "--dry-run")
        self.assertEqual(
            (code, output.strip()), (2, f"{G6C}: leftover finding has no summary")
        )
        self.no_writes()

    def test_finding_without_file_uses_summary_only(self):
        summary = json.loads(
            (FIXTURES / G6C)
            .read_text()
            .split("## Response\n", 1)[1]
            .split("```json\n", 1)[1]
            .split("\n```", 1)[0]
        )["findings"][0]["summary"]

        def remove_file(result):
            result["findings"][0].pop("file")
            result["findings"][0].pop("line")

        path = self.changed_result("no-file", remove_file)
        self.state["empty_sub_issues"] = True
        self.save()
        code, output = self.run_command("debt", path, "--dry-run")
        self.assertEqual(code, 0, output)
        changes = (
            self.planned(output)["body"]
            .split("### What changes\n\n", 1)[1]
            .split("\n\n### Done when", 1)[0]
            .splitlines()
        )
        self.assertEqual(changes[0], "- " + summary)

    def test_missing_command_exits_two(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            issue_tool.main([])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn(
            "the following arguments are required: command", stderr.getvalue()
        )


if __name__ == "__main__":
    unittest.main()
