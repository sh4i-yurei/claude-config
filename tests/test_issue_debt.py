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
VAULT1 = "2026-10-29-codex-to-claude-ansible-vault-lookup-review-1.md"
VAULT2 = "2026-10-29-codex-to-claude-ansible-vault-lookup-review-2.md"
G6D = "2026-10-28-codex-to-claude-workflow-g6d-platform-board-review-1.md"
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
            FAKE_GH_WORKFLOW=str(self.workflow / "workflow.toml"),
            FAKE_GH_FIXTURES=str(OPEN_FIXTURES),
            FAKE_GH_DEBT_FIXTURES=str(FIXTURES),
            PYTHONDONTWRITEBYTECODE="1",
        )
        self.state = {"debt_current_infra_forms": True}
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

    def rounds(self, case, *names):
        folder = self.root / case
        folder.mkdir()
        for name in names:
            shutil.copy(FIXTURES / name, folder / name)
        return folder

    def renamed_rounds(self, case, given, *copies):
        folder = self.rounds(case, *({given, ROUND1} if given == G6C else {given}))
        for source, name in copies:
            shutil.copy(FIXTURES / source, folder / name)
        return folder / given

    def assert_refused_without_gh(self, path, message):
        code, output = self.run_command("debt", path)
        self.assertEqual((code, output), (2, f"{path.name}: {message}\n"))
        self.assertEqual(self.calls(), [])

    def test_duplicate_final_round_is_refused(self):
        duplicate = "2026-10-28-codex-to-claude-workflow-g6c-board-add-race-review-2.md"
        path = self.renamed_rounds("duplicate-final", G6C, (G6C, duplicate))
        self.assert_refused_without_gh(
            path, f"round 2 appears in more than one file: {G6C} and {duplicate}"
        )

    def test_duplicate_earlier_round_is_refused(self):
        duplicate = "2026-10-25-codex-to-claude-workflow-g6c-board-add-race-review-1.md"
        path = self.renamed_rounds("duplicate-earlier", G6C, (ROUND1, duplicate))
        self.assert_refused_without_gh(
            path, f"round 1 appears in more than one file: {duplicate} and {ROUND1}"
        )

    def test_zero_padded_round_is_duplicate(self):
        duplicate = (
            "2026-10-27-codex-to-claude-workflow-g6c-board-add-race-review-02.md"
        )
        path = self.renamed_rounds("duplicate-padded", G6C, (G6C, duplicate))
        self.assert_refused_without_gh(
            path, f"round 2 appears in more than one file: {duplicate} and {G6C}"
        )

    def test_lowest_duplicate_round_is_named(self):
        first = "2026-10-25-codex-to-claude-workflow-g6c-board-add-race-review-1.md"
        second = "2026-10-28-codex-to-claude-workflow-g6c-board-add-race-review-2.md"
        third = "2026-10-29-codex-to-claude-workflow-g6c-board-add-race-review-2.md"
        path = self.renamed_rounds(
            "duplicate-lowest", G6C, (ROUND1, first), (G6C, second), (G6C, third)
        )
        self.assert_refused_without_gh(
            path, f"round 1 appears in more than one file: {first} and {ROUND1}"
        )

    def test_three_duplicate_files_are_all_named(self):
        second = "2026-10-28-codex-to-claude-workflow-g6c-board-add-race-review-2.md"
        third = "2026-10-29-codex-to-claude-workflow-g6c-board-add-race-review-2.md"
        path = self.renamed_rounds("duplicate-three", G6C, (G6C, second), (G6C, third))
        self.assert_refused_without_gh(
            path,
            f"round 2 appears in more than one file: {G6C}, {second} and {third}",
        )

    def test_duplicate_later_round_precedes_nonfinal_refusal(self):
        duplicate = "2026-10-28-codex-to-claude-workflow-g6c-board-add-race-review-2.md"
        path = self.renamed_rounds(
            "duplicate-later", ROUND1, (G6C, G6C), (G6C, duplicate)
        )
        self.assert_refused_without_gh(
            path, f"round 2 appears in more than one file: {G6C} and {duplicate}"
        )

    def test_round_zero_candidate_is_refused(self):
        zero = "2026-10-25-codex-to-claude-workflow-g6c-board-add-race-review-0.md"
        path = self.renamed_rounds("zero-candidate", G6C, (ROUND1, zero))
        self.assert_refused_without_gh(path, f"{zero} is round 0; rounds start at 1")

    def test_round_zero_given_file_is_refused(self):
        zero = "2026-10-27-codex-to-claude-workflow-g6c-board-add-race-review-0.md"
        folder = self.rounds("zero-given")
        shutil.copy(FIXTURES / G6C, folder / zero)
        self.assert_refused_without_gh(
            folder / zero, f"{zero} is round 0; rounds start at 1"
        )

    def test_round_zero_precedes_duplicate_refusal(self):
        zero = "2026-10-25-codex-to-claude-workflow-g6c-board-add-race-review-0.md"
        duplicate = "2026-10-28-codex-to-claude-workflow-g6c-board-add-race-review-2.md"
        path = self.renamed_rounds(
            "zero-and-duplicate", G6C, (ROUND1, zero), (G6C, duplicate)
        )
        self.assert_refused_without_gh(path, f"{zero} is round 0; rounds start at 1")

    def test_other_build_rounds_do_not_duplicate_g6c(self):
        path = self.renamed_rounds(
            "other-build",
            G6C,
            (G9A, G9A),
            (
                "2026-10-26-codex-to-claude-workflow-g9a-issue-labels-review-1.md",
                "2026-10-26-codex-to-claude-workflow-g9a-issue-labels-review-1.md",
            ),
        )
        self.state["empty_sub_issues"] = True
        self.save()
        code, output = self.run_command("debt", path, "--dry-run")
        self.assertEqual(code, 0, output)
        create = self.planned(output)
        expected = []
        for number, name in ((1, ROUND1), (2, G6C)):
            for finding in self.result(name)["findings"]:
                if (
                    finding["severity"] == "non_blocking"
                    and finding["breaks_test_case"] == "none"
                ):
                    expected.append(
                        f"- Round {number}: {finding['file']}:{finding['line']}: {finding['summary']}"
                    )
        self.assertEqual(
            self.changes(create),
            expected,
        )

    def test_dated_and_undated_names_identify_the_same_build(self):
        folder = self.rounds("mixed-date-names", G6C)
        undated = ROUND1.removeprefix("2026-10-26-")
        shutil.copy(FIXTURES / ROUND1, folder / undated)
        self.state["empty_sub_issues"] = True
        self.save()
        code, output = self.run_command("debt", folder / G6C, "--dry-run")
        self.assertEqual(code, 0, output)
        create = self.planned(output)
        self.assertIn(f"05_Agents/handoffs/{undated}", create["body"])
        self.assertEqual(len(self.changes(create)), 4)

    def test_directory_entry_does_not_hide_later_round_files(self):
        folder = self.root / "directory-before-reviews"
        folder.mkdir()
        (folder / "unrelated-directory").mkdir()
        for name in (ROUND1, G6C):
            shutil.copy(FIXTURES / name, folder / name)
        self.state["empty_sub_issues"] = True
        self.save()
        original_iterdir = Path.iterdir

        def directory_first(path):
            entries = list(original_iterdir(path))
            if path == folder:
                entries.sort(key=lambda entry: entry.is_file())
            return iter(entries)

        with patch.object(Path, "iterdir", directory_first):
            code, output = self.run_command("debt", folder / G6C, "--dry-run")
        self.assertEqual(code, 0, output)
        self.assertEqual(len(self.changes(self.planned(output))), 4)

    def derived(self, name, case, transform):
        folder = self.rounds(case, ROUND1)
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

    def planned(self, output, repo=REPO):
        prefix = f"Would call: POST repos/{repo}/issues "
        line = next(line for line in output.splitlines() if line.startswith(prefix))
        return json.loads(line.removeprefix(prefix))

    def changes(self, create):
        return (
            create["body"]
            .split("### What changes\n\n", 1)[1]
            .split("\n\n### Done when", 1)[0]
            .splitlines()
        )

    def result(self, name):
        return json.loads(
            (FIXTURES / name)
            .read_text()
            .split("## Response\n", 1)[1]
            .split("```json\n", 1)[1]
            .split("\n```", 1)[0]
        )

    def replace_result(self, path, change):
        text = path.read_text()
        before, rest = text.split("## Response\n", 1)
        block = rest.split("```json\n", 1)[1].split("\n```", 1)[0]
        result = json.loads(block)
        change(result)
        path.write_text(
            before + "## Response\n" + rest.replace(block, json.dumps(result), 1)
        )

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
            "### Project, step, and reason\n\nNon-blocking findings from G6c's review rounds 1 to 2 of #28, in 05_Agents/handoffs/"
            + ROUND1
            + " and 05_Agents/handoffs/"
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
        self.assertEqual(len(changes), 4)
        self.assertTrue(
            changes[0].startswith("- Round 1: tools/workflow/issue.py:262: ")
        )
        self.assertTrue(
            changes[1].startswith("- Round 1: tests/test_issue_open.py:761: ")
        )
        self.assertTrue(
            changes[2].startswith("- Round 2: tools/workflow/issue.py:491: ")
        )
        self.assertTrue(
            changes[3].startswith("- Round 2: tools/workflow/issue.py:272: ")
        )
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
                f"{ROUND1}: round 2 exists in {G6C}; run debt on the final round",
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
        self.assertEqual(len(changes), 3)
        self.assertTrue(
            changes[0].startswith("- Round 1: tools/workflow/issue.py:262: ")
        )
        self.assertTrue(
            changes[1].startswith("- Round 1: tests/test_issue_open.py:761: ")
        )
        self.assertTrue(
            changes[2].startswith("- Round 2: tools/workflow/issue.py:272: ")
        )

    def test_no_findings_opens_nothing(self):
        path = self.changed_result(
            "empty-findings", lambda result: result.update(findings=[])
        )
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
        self.assertEqual(len(changes), 2)
        self.assertTrue(
            changes[0].startswith("- Round 1: tools/workflow/issue.py:262: ")
        )
        self.assertTrue(
            changes[1].startswith("- Round 1: tests/test_issue_open.py:761: ")
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
        self.replace_result(path.parent / ROUND1, lambda result: result.update(issue=1))
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
        self.assertEqual(changes[2], "- Round 2: " + summary)

    def test_vault_rounds_plan_six_findings(self):
        folder = self.rounds("vault-plan", VAULT1, VAULT2)
        self.state["empty_sub_issues"] = True
        self.save()
        code, output = self.run_command("debt", folder / VAULT2, "--dry-run")
        self.assertEqual(code, 0, output)
        create = self.planned(output, "sh4i-yurei/keepbreathing-infra")
        self.assertEqual(
            create["title"],
            "Tech debt from the review of Agents can run the playbooks again",
        )
        self.assertEqual(create["labels"], ["type:chore", "scope:hub", "tech-debt"])
        self.assertIn("issues/74/sub_issues with sub_issue_id NEW_ISSUE_ID", output)
        prefixes = [
            "- Round 1: ansible/playbooks/become-password.yml:20: ",
            "- Round 1: ansible/tests/test_vault_secret.py:198: ",
            "- Round 1: ansible/tests/test_vault_secret.py:519: ",
            "- Round 1: ansible/tests/test_vault_secret.py:89: ",
            "- Round 1: ARCHITECTURE.md:82: ",
            "- Round 2: ansible/tests/test_vault_secret.py:221: ",
        ]
        changes = self.changes(create)
        self.assertEqual(len(changes), 6)
        self.assertEqual(
            [line[: len(prefix)] for line, prefix in zip(changes, prefixes)], prefixes
        )
        self.assertNotIn(".mutation-survivors.yml:111", create["body"])
        self.no_writes()

    def test_vault_existing_final_round_refuses_before_writes(self):
        folder = self.rounds("vault-existing", VAULT1, VAULT2)
        code, output = self.run_command("debt", folder / VAULT2)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{VAULT2}: #76 already files this review's leftovers"),
        )
        self.no_writes()

    def test_vault_earlier_round_refuses_before_gh(self):
        folder = self.rounds("vault-earlier", VAULT1, VAULT2)
        code, output = self.run_command("debt", folder / VAULT1)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{VAULT1}: round 2 exists in {VAULT2}; run debt on the final round"),
        )
        self.assertEqual(self.calls(), [])

    def test_earlier_round_already_filed_refuses(self):
        folder = self.rounds("earlier-filed", ROUND1, G6C)
        children = json.loads((FIXTURES / "issue-28-sub-issues.json").read_text())
        self.state["sub_issues_response"] = [
            dict(child, body=child["body"].replace(G6C, ROUND1)) for child in children
        ]
        self.save()
        code, output = self.run_command("debt", folder / G6C)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{G6C}: #29 already files leftovers from {ROUND1}"),
        )
        self.no_writes()

    def test_missing_middle_round_refuses_before_gh(self):
        folder = self.rounds("missing-middle", ROUND1)
        name = G6C.replace("-review-2.md", "-review-3.md")
        shutil.copy(FIXTURES / G6C, folder / name)
        code, output = self.run_command("debt", folder / name)
        self.assertEqual((code, output.strip()), (2, f"{name}: round 2 is missing"))
        self.assertEqual(self.calls(), [])

    def test_missing_first_round_refuses_before_gh(self):
        folder = self.rounds("missing-first", G6C)
        code, output = self.run_command("debt", folder / G6C)
        self.assertEqual((code, output.strip()), (2, f"{G6C}: round 1 is missing"))
        self.assertEqual(self.calls(), [])

    def test_final_round_must_pass_before_gh(self):
        folder = self.rounds("final-unpassed", ROUND1, G6C)
        self.replace_result(
            folder / G6C, lambda result: result.update(verdict="changes_required")
        )
        code, output = self.run_command("debt", folder / G6C)
        self.assertEqual(
            (code, output.strip()),
            (
                2,
                f"{G6C}: the final round's verdict is changes_required; leftovers are filed once the build passes",
            ),
        )
        self.assertEqual(self.calls(), [])

    def test_round_metadata_must_agree_before_gh(self):
        folder = self.rounds("different-issue", ROUND1, G6C)
        self.replace_result(folder / ROUND1, lambda result: result.update(issue=23))
        code, output = self.run_command("debt", folder / G6C)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{G6C}: {ROUND1} names a different repository, issue or item"),
        )
        self.assertEqual(self.calls(), [])

    def test_repeated_finding_is_listed_in_each_round(self):
        folder = self.rounds("repeated-finding", ROUND1, G6C)
        repeated = self.result(ROUND1)["findings"][1]
        self.replace_result(
            folder / G6C, lambda result: result["findings"].__setitem__(0, repeated)
        )
        self.state["empty_sub_issues"] = True
        self.save()
        code, output = self.run_command("debt", folder / G6C, "--dry-run")
        self.assertEqual(code, 0, output)
        changes = self.changes(self.planned(output))
        self.assertEqual(len(changes), 4)
        self.assertEqual(
            changes[0], f"- Round 1: tools/workflow/issue.py:262: {repeated['summary']}"
        )
        self.assertEqual(
            changes[2], f"- Round 2: tools/workflow/issue.py:262: {repeated['summary']}"
        )

    def test_no_qualifying_findings_in_any_round_opens_nothing(self):
        folder = self.rounds("no-leftovers", ROUND1, G6C)
        self.replace_result(
            folder / ROUND1,
            lambda result: result.update(findings=[result["findings"][0]]),
        )
        self.replace_result(folder / G6C, lambda result: result.update(findings=[]))
        code, output = self.run_command("debt", folder / G6C)
        self.assertEqual(
            (code, output.strip()), (0, f"{G6C}: no leftover findings; nothing opened")
        )
        self.no_writes()

    def test_single_round_keeps_existing_issue_shape(self):
        folder = self.rounds("one-round", G6D)
        code, output = self.run_command("debt", folder / G6D, "--dry-run")
        self.assertEqual(code, 0, output)
        create = self.planned(output)
        self.assertIn(
            f"Non-blocking findings from G6d's round 1 review of #36, in 05_Agents/handoffs/{G6D}.",
            create["body"],
        )
        changes = self.changes(create)
        self.assertEqual(len(changes), 2)
        self.assertTrue(
            changes[0].startswith(
                "- /var/home/sh4i_yurei/Documents/Second_Brain/20_Buildlogs/global-development-workflow/global-development-workflow-log.md:3588: "
            )
        )
        self.assertTrue(changes[1].startswith("- tools/workflow/workflow.toml:7: "))

    def test_three_rounds_name_each_source_and_check_middle_duplicate(self):
        folder = self.rounds("three-rounds", ROUND1, G6C)
        third = G6C.replace("-review-2.md", "-review-3.md")
        shutil.copy(FIXTURES / G6C, folder / third)
        self.state["empty_sub_issues"] = True
        self.save()
        code, output = self.run_command("debt", folder / third, "--dry-run")
        self.assertEqual(code, 0, output)
        create = self.planned(output)
        self.assertIn(
            f"Non-blocking findings from G6c's review rounds 1 to 3 of #28, in 05_Agents/handoffs/{ROUND1}, 05_Agents/handoffs/{G6C} and 05_Agents/handoffs/{third}.",
            create["body"],
        )
        self.assertEqual(len(self.changes(create)), 6)
        self.state["empty_sub_issues"] = False
        self.state["sub_issues_response"] = [{"number": 29, "body": f"Review: {G6C}"}]
        self.save()
        code, output = self.run_command("debt", folder / third)
        self.assertEqual(
            (code, output.strip()),
            (2, f"{third}: #29 already files leftovers from {G6C}"),
        )
        self.no_writes()

    def test_single_round_finding_without_file_has_no_round_prefix(self):
        folder = self.rounds("one-round-no-file", G6D)
        summary = self.result(G6D)["findings"][0]["summary"]
        self.replace_result(
            folder / G6D,
            lambda result: (
                result["findings"][0].pop("file"),
                result["findings"][0].pop("line"),
            ),
        )
        code, output = self.run_command("debt", folder / G6D, "--dry-run")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.changes(self.planned(output))[0], f"- {summary}")

    def test_single_round_invalid_metadata_has_exact_refusal(self):
        cases = (
            ("bad-repo", {"repo": "broken"}),
            ("null-repo", {"repo": None}),
            ("zero-issue", {"issue": 0}),
            ("text-issue", {"issue": "36"}),
            ("nontext-item", {"item": 23}),
            ("empty-item", {"item": ""}),
        )
        for case, changes in cases:
            with self.subTest(case=case):
                folder = self.rounds(f"metadata-{case}", G6D)
                self.replace_result(folder / G6D, lambda result: result.update(changes))
                code, output = self.run_command("debt", folder / G6D)
                self.assertEqual(
                    (code, output.strip()),
                    (2, f"{G6D}: review result has invalid repo, issue or item"),
                )
                self.assertEqual(self.calls(), [])

    def test_help_describes_final_round(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            issue_tool.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn(
            "file a build's review leftovers from its final round", stdout.getvalue()
        )

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
