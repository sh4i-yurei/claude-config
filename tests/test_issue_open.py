from contextlib import redirect_stdout
import base64
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/issue_open"
WORKFLOW = ROOT / "tools/workflow"
REPO = "sh4i-yurei/claude-config"
sys.path.insert(0, str(WORKFLOW))
sys.path.insert(0, str(ROOT))
import tools.workflow.issue as issue_tool
import config as workflow_config
from tools.workflow.config import load_boards


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
        output = io.StringIO()
        with (
            patch.dict(os.environ, self.env),
            patch.object(workflow_config, "DIRECTORY", self.workflow),
            redirect_stdout(output),
        ):
            code = issue_tool.main(["open", str(path), *options])
        return SimpleNamespace(returncode=code, stdout=output.getvalue(), stderr="")

    def valid(self, extra=""):
        return (
            f'repo = "{REPO}"\nkind = "feature"\ntitle = "A feature"\n'
            f'scope = "scope:ci"\n{extra}\n[body]\ndone = "It works"\n'
        )

    def create_request(self, output):
        prefix = f"Would call: POST repos/{REPO}/issues "
        line = next(line for line in output.splitlines() if line.startswith(prefix))
        return json.loads(line.removeprefix(prefix))

    def issue_creates(self):
        return [
            call
            for call in self.calls()
            if call["args"][:2] == ["api", f"repos/{REPO}/issues"]
            and "--method" in call["args"]
        ]

    def fail_board_add(self, message, board=2, url=None):
        prefix = ["project", "item-add"]
        if url is not None:
            prefix += ["2", "--owner", "sh4i-yurei", "--url", url]
        self.state["failure"] = {"prefix": prefix, "message": message}
        self.state["lookup_board"] = board
        self.save()

    def board_lookups(self):
        return [call for call in self.calls() if call["args"][:2] == ["api", "graphql"]]

    def assert_no_writes(self):
        self.assertFalse(
            any(
                "--method" in call["args"]
                or call["args"][:2]
                in (["project", "item-add"], ["project", "item-edit"])
                for call in self.calls()
            )
        )

    def test_dry_run_adds_global_labels_in_input_order(self):
        result = self.run_open(
            self.valid('labels = ["tech-debt", "debt:code", "debt:accidental"]'),
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.create_request(result.stdout)["labels"],
            ["type:feature", "scope:ci", "tech-debt", "debt:code", "debt:accidental"],
        )
        self.assert_no_writes()

    def test_open_adds_global_labels_and_prints_them(self):
        result = self.run_open(
            self.valid('labels = ["tech-debt", "debt:code", "debt:accidental"]')
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        created = self.issue_creates()
        self.assertEqual(len(created), 1)
        expected = [
            "type:feature",
            "scope:ci",
            "tech-debt",
            "debt:code",
            "debt:accidental",
        ]
        self.assertEqual(json.loads(created[0]["input"])["labels"], expected)
        self.assertIn(
            f"created https://github.com/{REPO}/issues/99 with labels {', '.join(expected)}",
            result.stdout,
        )

    def test_dry_run_drops_duplicate_global_labels(self):
        result = self.run_open(
            self.valid('labels = ["tech-debt", "tech-debt"]'), "--dry-run"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.create_request(result.stdout)["labels"],
            ["type:feature", "scope:ci", "tech-debt"],
        )
        self.assert_no_writes()

    def test_reserved_and_unknown_labels_are_refused(self):
        cases = {
            'labels = ["type:fix"]': "labels: type:fix is set by the issue form, not the labels list",
            'labels = ["scope:ci"]': "labels: scope:ci is set by the scope key, not the labels list",
            'labels = ["good first issue"]': "labels: good first issue is not a global label in labels.toml",
        }
        for value, message in cases.items():
            with self.subTest(value=value):
                result = self.run_open(self.valid(value), "--dry-run")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(message, result.stdout.splitlines())
                self.assert_no_writes()

    def test_invalid_labels_shape_is_refused(self):
        for value in (
            'labels = "tech-debt"',
            'labels = ["tech-debt", 3]',
            'labels = [""]',
        ):
            with self.subTest(value=value):
                result = self.run_open(self.valid(value), "--dry-run")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(
                    "labels must be a list of label names", result.stdout.splitlines()
                )
                self.assert_no_writes()

    def test_label_and_unknown_key_problems_are_reported_together(self):
        result = self.run_open(
            self.valid('labels = ["type:fix"]\nunknown = 1'), "--dry-run"
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(
            "labels: type:fix is set by the issue form, not the labels list",
            result.stdout.splitlines(),
        )
        self.assertIn("unknown file key unknown", result.stdout.splitlines())
        self.assert_no_writes()

    def test_no_labels_key_keeps_form_and_scope_labels(self):
        result = self.run_open(self.valid(), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.create_request(result.stdout)["labels"], ["type:feature", "scope:ci"]
        )
        self.assert_no_writes()

    def test_scope_refused_when_repository_has_no_scope_labels(self):
        path = self.workflow / "labels.toml"
        lines = path.read_text().splitlines(keepends=True)
        prefix = '[repository."sh4i-yurei/claude-config".'
        self.assertTrue(any(line.startswith(prefix) for line in lines))
        kept = []
        removing = False
        for line in lines:
            if line.startswith("["):
                removing = line.startswith(prefix)
            if not removing:
                kept.append(line)
        path.write_text("".join(kept))
        result = self.run_open(self.valid(), "--dry-run")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(
            "scope is not defined for this repository", result.stdout.splitlines()
        )
        self.assert_no_writes()

    def test_invalid_scope_names_repository_choices_without_writes(self):
        choices = {
            REPO: "scope:ci, scope:hooks, scope:rules, scope:skills, scope:tools, scope:vale, scope:workflow",
            "sh4i-yurei/codex-config": "scope:ci, scope:config, scope:hooks, scope:rules, scope:setup, scope:skills",
            "sh4i-yurei/keepbreathing": "scope:ci, scope:deploy, scope:site",
        }
        for repo, names in choices.items():
            for scope in (
                ("scope:bad", "scope:workflow") if repo != REPO else ("scope:bad",)
            ):
                with self.subTest(repo=repo, scope=scope):
                    data = self.valid().replace(REPO, repo).replace("scope:ci", scope)
                    result = self.run_open(data, "--dry-run")
                    self.assertEqual(result.returncode, 2, result.stdout)
                    self.assertIn(f"scope must be one of: {names}", result.stdout)
                    self.assert_no_writes()

    def test_each_repository_scope_plans_its_exact_issue_labels(self):
        scopes = {
            REPO: ("ci", "hooks", "rules", "skills", "tools", "vale", "workflow"),
            "sh4i-yurei/codex-config": (
                "ci",
                "config",
                "hooks",
                "rules",
                "setup",
                "skills",
            ),
            "sh4i-yurei/keepbreathing": ("ci", "deploy", "site"),
        }
        for repo, names in scopes.items():
            for name in names:
                scope = f"scope:{name}"
                with self.subTest(repo=repo, scope=scope):
                    data = self.valid().replace(REPO, repo).replace("scope:ci", scope)
                    result = self.run_open(data, "--dry-run")
                    self.assertEqual(result.returncode, 0, result.stdout)
                    prefix = f"Would call: POST repos/{repo}/issues "
                    request = next(
                        json.loads(line.removeprefix(prefix))
                        for line in result.stdout.splitlines()
                        if line.startswith(prefix)
                    )
                    self.assertEqual(request["labels"], ["type:feature", scope])
                    self.assert_no_writes()

    def test_form_without_labels_uses_scope_and_extra_labels(self):
        fixtures = self.root / "fixtures"
        shutil.copytree(FIXTURES, fixtures)
        form_path = fixtures / "form-feature.yml.json"
        form = json.loads(form_path.read_text())
        body = base64.b64decode(form["content"]).decode()
        self.assertIn('labels: ["type:feature"]\n', body)
        form["content"] = base64.b64encode(
            body.replace('labels: ["type:feature"]\n', "", 1).encode()
        ).decode()
        form_path.write_text(json.dumps(form))
        self.env["FAKE_GH_FIXTURES"] = str(fixtures)
        result = self.run_open(self.valid('labels = ["tech-debt"]'), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.create_request(result.stdout)["labels"], ["scope:ci", "tech-debt"]
        )
        self.assert_no_writes()

    def change_workflow(self, old, new):
        path = self.workflow / "workflow.toml"
        content = path.read_text()
        self.assertIn(old, content)
        path.write_text(content.replace(old, new, 1))

    def assert_bad_workflow(self, message):
        result = self.run_open(self.valid(), "--dry-run")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, message + "\n")
        self.assertFalse(self.calls())

    def test_unmapped_repo_refuses_without_writes_and_names_mapping(self):
        result = self.run_open(
            self.valid().replace(REPO, "sh4i-yurei/new-repo"), "--dry-run"
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "no board mapping for sh4i-yurei/new-repo; add to workflow.toml [boards], naming its product:",
                '"sh4i-yurei/new-repo" = "<product>"',
                "products: keepbreath.ing, Tooling, Platform",
            ],
        )
        self.assertFalse(self.calls())

    def test_unmapped_repo_advice_lists_new_product_in_order(self):
        self.change_workflow(
            "[boards]",
            '"Pong" = { owner = "sh4i-yurei", number = 99 }\n\n[boards]',
        )
        result = self.run_open(
            self.valid().replace(REPO, "sh4i-yurei/new-repo"), "--dry-run"
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines()[-1],
            "products: keepbreath.ing, Tooling, Platform, Pong",
        )
        self.assertFalse(self.calls())

    def test_unknown_product_refused_before_gh(self):
        self.change_workflow(
            '"sh4i-yurei/keepbreathing" = "keepbreath.ing"',
            '"sh4i-yurei/keepbreathing" = "Pong"',
        )
        self.assert_bad_workflow(
            "workflow.toml: board mapping for sh4i-yurei/keepbreathing names unknown product Pong"
        )

    def test_old_board_shape_refused_before_gh(self):
        self.change_workflow(
            '"sh4i-yurei/keepbreathing" = "keepbreath.ing"',
            '"sh4i-yurei/keepbreathing" = { owner = "sh4i-yurei", number = 1 }',
        )
        self.assert_bad_workflow(
            "workflow.toml: invalid board mapping for sh4i-yurei/keepbreathing"
        )

    def test_invalid_product_refused_before_gh(self):
        original = '"Tooling" = { owner = "sh4i-yurei", number = 2 }'
        for replacement in (
            '"Tooling" = { owner = "sh4i-yurei", number = 0 }',
            '"Tooling" = { number = 2 }',
            '"Tooling" = { owner = "sh4i-yurei", number = 2, title = "Tooling" }',
        ):
            with self.subTest(replacement=replacement):
                self.change_workflow(original, replacement)
                try:
                    self.assert_bad_workflow("workflow.toml: invalid product Tooling")
                finally:
                    self.change_workflow(replacement, original)

    def test_missing_products_table_refused_before_gh(self):
        path = self.workflow / "workflow.toml"
        content = path.read_text()
        start = content.index("[products]")
        end = content.index("[boards]")
        path.write_text(content[:start] + content[end:])
        self.assert_bad_workflow("workflow.toml: missing or invalid products table")

    def test_products_cannot_share_a_board(self):
        self.change_workflow(
            '"Tooling" = { owner = "sh4i-yurei", number = 2 }',
            '"Tooling" = { owner = "sh4i-yurei", number = 1 }',
        )
        self.assert_bad_workflow(
            "workflow.toml: products keepbreath.ing and Tooling share board sh4i-yurei 1"
        )

    def test_every_active_nonexception_repository_has_a_board(self):
        configured = tomllib.loads((WORKFLOW / "workflow.toml").read_text())
        repos = json.loads((FIXTURES / "repos.json").read_text())
        active = {item["nameWithOwner"] for item in repos if not item["isArchived"]}
        self.assertEqual(
            set(configured["boards"]), active - set(configured["exceptions"])
        )
        self.assertEqual(
            load_boards(),
            {
                repo: {"owner": "sh4i-yurei", "number": number}
                for repo, number in {
                    "sh4i-yurei/.github": 2,
                    "sh4i-yurei/ci-workflows": 2,
                    "sh4i-yurei/claude-config": 2,
                    "sh4i-yurei/codex-config": 2,
                    "sh4i-yurei/keepbreath-contact-api": 1,
                    "sh4i-yurei/keepbreathing": 1,
                    "sh4i-yurei/keepbreathing-infra": 3,
                }.items()
            },
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
                "no board mapping for sh4i-yurei/new-repo; add to workflow.toml [boards], naming its product:",
                '"sh4i-yurei/new-repo" = "<product>"',
                "products: keepbreath.ing, Tooling, Platform",
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
            config.write(f'\n"{other}" = "keepbreath.ing"\n')
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
            config.write(f'\n"{other}" = "keepbreath.ing"\n')
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
        self.assertTrue(
            all(args[2:5] == ["2", "--owner", "sh4i-yurei"] for args in additions),
            additions,
        )
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

    def test_dry_run_uses_tooling_board_for_every_project_call(self):
        result = self.run_open(self.valid(), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "Would call: project item-add 2 --owner sh4i-yurei --url NEW_ISSUE_URL",
            result.stdout,
        )
        project_calls = [
            call["args"] for call in self.calls() if call["args"][:1] == ["project"]
        ]
        self.assertTrue(project_calls)
        self.assertTrue(
            all(
                args[2:5] == ["2", "--owner", "sh4i-yurei"]
                for args in project_calls
                if args[1] != "item-edit"
            ),
            project_calls,
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
        path = self.root / "issue.toml"
        path.write_text(self.valid())
        source_root = ROOT.parent if ROOT.name == "mutants" else ROOT
        result = subprocess.run(
            [
                sys.executable,
                source_root / "tools/workflow/issue.py",
                "open",
                str(path),
            ],
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
        )
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

    def test_new_issue_found_on_board_after_add_failure(self):
        self.fail_board_add(
            "GraphQL: Content already exists in this project (addProjectV2ItemById)",
            url=f"https://github.com/{REPO}/issues/99",
        )
        result = self.run_open(self.valid())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("found new issue already on board\n", result.stdout)
        self.assertIn("set new issue Status Backlog\n", result.stdout)
        lookup = self.board_lookups()
        self.assertEqual(len(lookup), 1)
        self.assertEqual(
            lookup[0]["args"][2:4],
            [
                "-f",
                "query=query($url: URI!){ resource(url: $url){ ... on Issue { projectItems(first: 20){ nodes{ id project{ number owner{ ... on User { login } ... on Organization { login } } } } } } } }",
            ],
        )
        self.assertEqual(
            lookup[0]["args"][4:], ["-f", f"url=https://github.com/{REPO}/issues/99"]
        )
        edit = next(
            call
            for call in self.calls()
            if call["args"][:2] == ["project", "item-edit"]
        )
        self.assertEqual(
            edit["args"][edit["args"].index("--id") + 1], "PVTI_lAHODeM_nM4Bo2B8zhDt9uk"
        )

    def test_stray_found_on_board_after_add_failure(self):
        self.fail_board_add(
            "GraphQL: Content already exists in this project (addProjectV2ItemById)"
        )
        result = self.run_open(self.valid())
        self.assertEqual(result.returncode, 0, result.stdout)
        for number in (18, 12):
            self.assertIn(f"found stray #{number} already on board\n", result.stdout)
            self.assertIn(f"set stray #{number} Status Backlog\n", result.stdout)
        self.assertEqual(len(self.board_lookups()), 3)

    def test_other_add_error_with_card_found_succeeds(self):
        self.fail_board_add("HTTP 502")
        result = self.run_open(self.valid())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("found new issue already on board\n", result.stdout)

    def test_add_failure_without_card_on_configured_board_preserves_error(self):
        message = (
            "GraphQL: Content already exists in this project (addProjectV2ItemById)"
        )
        for board in (3, None):
            with self.subTest(board=board):
                self.fail_board_add(message, board)
                result = self.run_open(self.valid())
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(
                    result.stdout.splitlines()[:4],
                    [
                        f"https://github.com/{REPO}/issues/99",
                        "completed: created https://github.com/sh4i-yurei/claude-config/issues/99 with labels type:feature, scope:ci",
                        "not completed: added new issue to board; set new issue Status Backlog; added stray #18 to board; set stray #18 Status Backlog; added stray #12 to board; set stray #12 Status Backlog",
                        f"failed: {message}",
                    ],
                )

    def test_lookup_failure_reports_both_errors(self):
        self.fail_board_add(
            "GraphQL: Content already exists in this project (addProjectV2ItemById)"
        )
        self.state["lookup_failure"] = "HTTP 504"
        self.save()
        result = self.run_open(self.valid())
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(
            "not completed: added new issue to board; set new issue Status Backlog",
            result.stdout,
        )
        self.assertIn(
            "failed: GraphQL: Content already exists in this project (addProjectV2ItemById); checking the board also failed: HTTP 504",
            result.stdout,
        )

    def test_successful_add_makes_no_board_lookup_and_keeps_calls(self):
        result = self.run_open(self.valid())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.board_lookups(), [])
        self.assertEqual(
            [call["args"] for call in self.calls()],
            [
                ["api", f"repos/{REPO}/contents/.github/ISSUE_TEMPLATE"],
                ["api", "repos/sh4i-yurei/.github/contents/.github/ISSUE_TEMPLATE"],
                [
                    "api",
                    "repos/sh4i-yurei/.github/contents/.github/ISSUE_TEMPLATE/feature.yml",
                ],
                ["project", "view", "2", "--owner", "sh4i-yurei", "--format", "json"],
                [
                    "project",
                    "field-list",
                    "2",
                    "--owner",
                    "sh4i-yurei",
                    "--format",
                    "json",
                    "--limit",
                    "100",
                ],
                [
                    "project",
                    "item-list",
                    "2",
                    "--owner",
                    "sh4i-yurei",
                    "--format",
                    "json",
                    "--limit",
                    "10000",
                ],
                [
                    "issue",
                    "list",
                    "--repo",
                    REPO,
                    "--state",
                    "open",
                    "--limit",
                    "10000",
                    "--json",
                    "number,url",
                ],
                ["api", f"repos/{REPO}/issues", "--method", "POST", "--input", "-"],
                [
                    "project",
                    "item-add",
                    "2",
                    "--owner",
                    "sh4i-yurei",
                    "--url",
                    f"https://github.com/{REPO}/issues/99",
                    "--format",
                    "json",
                ],
                [
                    "project",
                    "item-edit",
                    "--id",
                    "PVTI_NEW",
                    "--project-id",
                    "PVT_kwHODeM_nM4Bnbqb",
                    "--field-id",
                    "PVTSSF_lAHODeM_nM4BnbqbzhmAVQk",
                    "--single-select-option-id",
                    "f75ad846",
                    "--format",
                    "json",
                ],
                [
                    "project",
                    "item-add",
                    "2",
                    "--owner",
                    "sh4i-yurei",
                    "--url",
                    f"https://github.com/{REPO}/issues/18",
                    "--format",
                    "json",
                ],
                [
                    "project",
                    "item-edit",
                    "--id",
                    "PVTI_NEW",
                    "--project-id",
                    "PVT_kwHODeM_nM4Bnbqb",
                    "--field-id",
                    "PVTSSF_lAHODeM_nM4BnbqbzhmAVQk",
                    "--single-select-option-id",
                    "f75ad846",
                    "--format",
                    "json",
                ],
                [
                    "project",
                    "item-add",
                    "2",
                    "--owner",
                    "sh4i-yurei",
                    "--url",
                    f"https://github.com/{REPO}/issues/12",
                    "--format",
                    "json",
                ],
                [
                    "project",
                    "item-edit",
                    "--id",
                    "PVTI_NEW",
                    "--project-id",
                    "PVT_kwHODeM_nM4Bnbqb",
                    "--field-id",
                    "PVTSSF_lAHODeM_nM4BnbqbzhmAVQk",
                    "--single-select-option-id",
                    "f75ad846",
                    "--format",
                    "json",
                ],
            ],
        )

    def test_link_responses_keep_completed_text_when_status_fails(self):
        self.state["failure"] = {
            "prefix": ["project", "item-edit"],
            "message": "HTTP 502",
        }
        self.save()
        result = self.run_open(self.valid("parent = 20\nblocked_by = [22]"))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                f"https://github.com/{REPO}/issues/99",
                f"completed: created https://github.com/{REPO}/issues/99 with labels type:feature, scope:ci; linked parent #20; linked blocked-by #22; added new issue to board",
                "not completed: set new issue Status Backlog; added stray #18 to board; set stray #18 Status Backlog; added stray #12 to board; set stray #12 Status Backlog",
                "failed: HTTP 502",
            ],
        )

    def test_malformed_board_lookup_preserves_both_errors(self):
        for shape, detail in (
            ("not_mapping", "resource is not an issue"),
            ("bad_data", "resource is not an issue"),
            ("null_resource", "resource is not an issue"),
            ("missing_project_items", "projectItems is missing"),
            ("missing_nodes", "board cards are missing"),
            ("bad_card", "board card is incomplete"),
            ("bad_project", "board card is incomplete"),
            ("bad_number", "board card is incomplete"),
            ("bad_owner", "board card is incomplete"),
            ("bad_login", "board card is incomplete"),
            ("bad_id", "board card is incomplete"),
        ):
            with self.subTest(shape=shape):
                self.fail_board_add("HTTP 502")
                self.state["lookup_response"] = shape
                self.save()
                result = self.run_open(self.valid())
                self.assertEqual(result.returncode, 2)
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        f"https://github.com/{REPO}/issues/99",
                        f"completed: created https://github.com/{REPO}/issues/99 with labels type:feature, scope:ci",
                        "not completed: added new issue to board; set new issue Status Backlog; added stray #18 to board; set stray #18 Status Backlog; added stray #12 to board; set stray #12 Status Backlog",
                        f"failed: HTTP 502; checking the board also failed: {detail}",
                    ],
                )

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
