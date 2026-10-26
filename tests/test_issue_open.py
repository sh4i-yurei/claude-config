import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/issue_open"
WORKFLOW = ROOT / "tools/workflow"
REPO = "sh4i-yurei/claude-config"


class IssueOpen(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workflow = self.root / "workflow"
        shutil.copytree(WORKFLOW, self.workflow)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "gh"
        shutil.copy(FIXTURES / "fake_gh.py", fake)
        fake.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            FAKE_GH_CALLS=str(self.root / "calls.jsonl"),
            FAKE_GH_STATE=str(self.root / "state.json"),
            FAKE_GH_FIXTURES=str(FIXTURES),
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

    def run_open(self, data, *options):
        path = self.root / "issue.toml"
        path.write_text(data)
        return subprocess.run(
            [sys.executable, self.workflow / "issue.py", "open", str(path), *options],
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
        )

    def valid(self, extra=""):
        return (
            f'repo = "{REPO}"\nkind = "feature"\ntitle = "A feature"\n'
            f'scope = "scope:ci"\n{extra}\n[body]\ndone = "It works"\n'
        )

    def test_unmapped_repo_refuses_without_writes_and_names_mapping(self):
        result = self.run_open(self.valid().replace(REPO, "sh4i-yurei/new-repo"))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(
            '"sh4i-yurei/new-repo" = { owner = "sh4i-yurei", number = 1 }',
            result.stdout,
        )
        self.assertFalse(self.calls())

    def test_every_active_nonexception_repository_has_a_board(self):
        configured = tomllib.loads((WORKFLOW / "workflow.toml").read_text())
        repos = json.loads((FIXTURES / "repos.json").read_text())
        active = {item["nameWithOwner"] for item in repos if not item["isArchived"]}
        self.assertEqual(
            set(configured["boards"]), active - set(configured["exceptions"])
        )
        self.assertEqual(
            set(
                (item["owner"], item["number"])
                for item in configured["boards"].values()
            ),
            {("sh4i-yurei", 1)},
        )

    def test_markdown_templates_refused_with_both_names(self):
        result = self.run_open(
            self.valid().replace(REPO, "sh4i-yurei/keepbreathing-infra")
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("bug.md", result.stdout)
        self.assertIn("task.md", result.stdout)
        self.assertFalse(any("--method" in call["args"] for call in self.calls()))

    def test_reports_all_input_errors_before_writing(self):
        data = (
            self.valid()
            .replace('kind = "feature"', 'kind = "missing"\nunknown = 7')
            .replace('done = "It works"', 'oops = "bad"')
        )
        result = self.run_open(data)
        self.assertEqual(result.returncode, 2)
        for problem in ("kind", "unknown"):
            self.assertIn(problem, result.stdout)
        self.assertNotIn("oops", result.stdout)
        self.assertFalse(any("--method" in call["args"] for call in self.calls()))

    def test_nontext_kind_names_other_file_errors(self):
        result = self.run_open(
            self.valid().replace('kind = "feature"', 'kind = ["feature"]\nunknown = 7')
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("kind", result.stdout)
        self.assertIn("unknown", result.stdout)
        self.assertFalse(any("--method" in call["args"] for call in self.calls()))

    def test_missing_repo_names_unknown_key(self):
        result = self.run_open(self.valid().replace(f'repo = "{REPO}"', "unknown = 7"))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("repo", result.stdout)
        self.assertIn("unknown", result.stdout)
        self.assertFalse(self.calls())

    def test_missing_repo_reports_only_independent_errors(self):
        data = self.valid('milestone = "absent"\nparent = 777\nblocked_by = [778]')
        data = data.replace(f'repo = "{REPO}"', "unknown = 7")
        data = data.replace('kind = "feature"', 'kind = ["feature"]')
        result = self.run_open(data)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "unknown file key unknown",
                "repo must be a nonempty string",
                "kind must be a nonempty string",
                "repo must be owner/name",
            ],
        )
        self.assertFalse(self.calls())

    def test_unmapped_repo_skips_dependent_checks(self):
        data = self.valid('milestone = "absent"\nparent = 777\nblocked_by = [778]')
        data = data.replace(REPO, "sh4i-yurei/new-repo").replace(
            'kind = "feature"', 'kind = ["feature"]'
        )
        result = self.run_open(data)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "kind must be a nonempty string",
                "no board mapping for sh4i-yurei/new-repo; add to workflow.toml [boards]:",
                '"sh4i-yurei/new-repo" = { owner = "sh4i-yurei", number = 1 }',
            ],
        )
        self.assertFalse(self.calls())

    def test_unknown_kind_reports_repository_checks_without_body_field_errors(self):
        data = self.valid('milestone = "absent"').replace(
            'kind = "feature"', 'kind = "missing"'
        )
        data = data.replace('done = "It works"', 'extra = "bad"')
        result = self.run_open(data)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("kind 'missing' matches no issue form", result.stdout)
        self.assertIn("milestone 'absent' does not exist", result.stdout)
        self.assertNotIn("extra", result.stdout)
        self.assertFalse(any("--method" in call["args"] for call in self.calls()))

    def test_missing_owner_shared_forms_names_missing_forms(self):
        other = "missing-owner/other-repo"
        with (self.workflow / "workflow.toml").open("a") as config:
            config.write(f'\n"{other}" = {{ owner = "sh4i-yurei", number = 1 }}\n')
        data = self.valid().replace(REPO, other).replace('scope = "scope:ci"\n', "")
        result = self.run_open(data)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("missing-owner/.github", result.stdout)
        self.assertIn("issue forms", result.stdout)
        self.assertNotIn("HTTP 404", result.stdout)
        self.assertFalse(any("--method" in call["args"] for call in self.calls()))

    def test_invalid_body_and_missing_milestone_are_both_named(self):
        result = self.run_open(
            self.valid('milestone = "absent"').replace(
                'done = "It works"', 'extra = "bad"'
            )
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("extra", result.stdout)
        self.assertIn("absent", result.stdout)
        self.assertFalse(any("--method" in call["args"] for call in self.calls()))

    def test_shared_forms_come_from_issue_repository_owner(self):
        other = "second-owner/other-repo"
        with (self.workflow / "workflow.toml").open("a") as config:
            config.write(f'\n"{other}" = {{ owner = "sh4i-yurei", number = 1 }}\n')
        data = self.valid().replace(REPO, other).replace('scope = "scope:ci"\n', "")
        result = self.run_open(data, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("### Done when", result.stdout)
        endpoints = [
            call["args"][1] for call in self.calls() if call["args"][:1] == ["api"]
        ]
        self.assertIn(
            "repos/second-owner/.github/contents/.github/ISSUE_TEMPLATE", endpoints
        )
        self.assertNotIn(
            "repos/sh4i-yurei/.github/contents/.github/ISSUE_TEMPLATE", endpoints
        )

    def test_scope_missing_or_wrong_names_valid_scope(self):
        for data in (
            self.valid().replace('scope = "scope:ci"\n', ""),
            self.valid().replace("scope:ci", "scope:bad"),
        ):
            result = self.run_open(data)
            self.assertEqual(result.returncode, 2)
            self.assertIn("scope:ci", result.stdout)
        self.assertFalse(any("--method" in call["args"] for call in self.calls()))

    def test_nonexistent_milestone_and_related_issues_refused(self):
        result = self.run_open(
            self.valid('milestone = "absent"\nparent = 777\nblocked_by = [778]')
        )
        self.assertEqual(result.returncode, 2)
        for problem in ("absent", "777", "778"):
            self.assertIn(problem, result.stdout)
        self.assertFalse(any("--method" in call["args"] for call in self.calls()))

    def test_dry_run_renders_form_and_lists_writes_without_making_them(self):
        result = self.run_open(
            self.valid("parent = 20\nblocked_by = [22]"), "--dry-run"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("### Done when\n\nIt works", result.stdout)
        for phrase in ("POST", "sub_issues", "blocked_by", "Backlog"):
            self.assertIn(phrase, result.stdout)
        self.assertFalse(
            any(
                call["args"][:2] in (["project", "item-add"], ["project", "item-edit"])
                or "--method" in call["args"]
                for call in self.calls()
            )
        )

    def test_open_creates_issue_links_and_board_item_then_backfills(self):
        result = self.run_open(self.valid("parent = 20\nblocked_by = [22]"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "https://github.com/sh4i-yurei/claude-config/issues/99", result.stdout
        )
        calls = self.calls()
        self.assertTrue(
            any(call["args"][:2] == ["project", "item-add"] for call in calls)
        )
        self.assertTrue(
            any(call["args"][:2] == ["project", "item-edit"] for call in calls)
        )
        self.assertTrue(any("/sub_issues" in " ".join(call["args"]) for call in calls))
        self.assertTrue(any("/blocked_by" in " ".join(call["args"]) for call in calls))
        self.assertIn("Backlog", result.stdout)

        additions = [
            call["args"]
            for call in calls
            if call["args"][:2] == ["project", "item-add"]
        ]
        for number in (18, 12):
            url = f"https://github.com/{REPO}/issues/{number}"
            self.assertTrue(
                any(
                    "--url" in args and args[args.index("--url") + 1] == url
                    for args in additions
                ),
                additions,
            )
            self.assertIn(f"added stray #{number} to board", result.stdout)
            self.assertIn(f"set stray #{number} Status Backlog", result.stdout)
        edits = [
            call["args"]
            for call in calls
            if call["args"][:2] == ["project", "item-edit"]
        ]
        self.assertEqual(len(edits), 3, edits)
        self.assertTrue(
            all("--single-select-option-id" in args for args in edits), edits
        )

        created = next(
            call
            for call in calls
            if call["args"][:2] == ["api", f"repos/{REPO}/issues"]
            and "--method" in call["args"]
        )
        payload = json.loads(created["input"])
        self.assertEqual(payload["labels"], ["type:feature", "scope:ci"])
        self.assertEqual(
            payload["body"],
            "### Project, step, and reason\n\n_No response_\n\n"
            "### What changes\n\n_No response_\n\n"
            "### Done when\n\nIt works\n",
        )
        parent = next(call for call in calls if "/sub_issues" in " ".join(call["args"]))
        blocked = next(
            call for call in calls if "/blocked_by" in " ".join(call["args"])
        )
        self.assertEqual(json.loads(parent["input"]), {"sub_issue_id": 123456789})
        self.assertEqual(
            json.loads(blocked["input"]),
            {"issue_id": json.loads((FIXTURES / "issue-22.json").read_text())["id"]},
        )
        self.assertFalse(
            any(
                "--field-id" in call["args"]
                and "--single-select-option-id" not in call["args"]
                for call in calls
            )
        )

    def test_required_field_empty_and_extra_field_both_named(self):
        result = self.run_open(
            self.valid().replace('done = "It works"', 'done = ""\nextra = "wrong"')
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("required body field done is missing or empty", result.stdout)
        self.assertIn("unknown body field extra", result.stdout)
        self.assertFalse(any("--method" in call["args"] for call in self.calls()))

    def test_missing_pyyaml_names_dependency(self):
        self.env["PYTHONNOUSERSITE"] = "1"
        result = self.run_open(self.valid())
        self.assertEqual(result.returncode, 2)
        self.assertIn("PyYAML is required", result.stdout)
        self.assertFalse(any("--method" in call["args"] for call in self.calls()))

    def test_whitespace_required_field_is_empty(self):
        result = self.run_open(
            self.valid().replace('done = "It works"', 'done = "   "')
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("required body field done is missing or empty", result.stdout)
        self.assertFalse(any("--method" in call["args"] for call in self.calls()))

    def test_milestone_title_resolves_to_number_in_create_request(self):
        milestone = json.loads((FIXTURES / "milestones.json").read_text())[0]
        result = self.run_open(self.valid(f'milestone = "{milestone["title"]}"'))
        self.assertEqual(result.returncode, 0, result.stdout)
        created = next(
            call
            for call in self.calls()
            if call["args"][:2] == ["api", f"repos/{REPO}/issues"]
            and "--method" in call["args"]
        )
        self.assertEqual(json.loads(created["input"])["milestone"], milestone["number"])

    def test_post_creation_failure_reports_completed_and_uncompleted_steps(self):
        self.state["failure"] = {
            "prefix": ["project", "item-add"],
            "message": "board unavailable",
        }
        self.save()
        result = self.run_open(self.valid())
        self.assertEqual(result.returncode, 2)
        for phrase in (
            "https://github.com/sh4i-yurei/claude-config/issues/99",
            "board unavailable",
            "completed",
            "not completed",
        ):
            self.assertIn(phrase, result.stdout)

    def test_status_failure_reports_board_add_as_completed(self):
        self.state["failure"] = {
            "prefix": ["project", "item-edit"],
            "message": "status unavailable",
        }
        self.save()
        result = self.run_open(self.valid())
        self.assertEqual(result.returncode, 2)
        self.assertIn("completed: created", result.stdout)
        self.assertIn("added new issue to board", result.stdout)
        self.assertIn("not completed: set new issue Status Backlog", result.stdout)
        self.assertIn("status unavailable", result.stdout)


if __name__ == "__main__":
    unittest.main()
