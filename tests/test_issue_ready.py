from contextlib import redirect_stdout
import base64
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import yaml


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/issue_open"
REPO = "sh4i-yurei/claude-config"
sys.path.insert(0, str(ROOT / "tools/workflow"))
sys.path.insert(0, str(ROOT))
import tools.workflow.issue as issue_tool
import config as workflow_config


class IssueReady(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "gh"
        shutil.copy(FIXTURES / "fake_ready_gh.py", fake)
        fake.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            FAKE_GH_FIXTURES=str(FIXTURES),
            FAKE_GH_CALLS=str(self.root / "calls.jsonl"),
            FAKE_GH_STATE=str(self.root / "state.json"),
            PYTHONDONTWRITEBYTECODE="1",
        )
        self.state = {"number": "23"}
        self.save()

    def save(self):
        Path(self.env["FAKE_GH_STATE"]).write_text(json.dumps(self.state))

    def run_ready(self, number="23", *options, repo=REPO):
        self.state["number"] = number
        self.save()
        output = io.StringIO()
        with patch.dict(os.environ, self.env), redirect_stdout(output):
            code = issue_tool.main(["ready", f"{repo}#{number}", *options])
        return SimpleNamespace(returncode=code, stdout=output.getvalue(), stderr="")

    def calls(self):
        path = Path(self.env["FAKE_GH_CALLS"])
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def test_ready_uses_tooling_board_for_every_project_call(self):
        result = self.run_ready()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        project_calls = [
            call["args"] for call in self.calls() if call["args"][:1] == ["project"]
        ]
        self.assertTrue(project_calls)
        self.assertTrue(
            all(args[2:5] == ["2", "--owner", "sh4i-yurei"] for args in project_calls),
            project_calls,
        )

    def test_ready_sets_status_and_reports_every_met_item(self):
        self.state["board_fields"] = {
            "priority": "P1",
            "size": "Feature",
            "estimate": 2,
        }
        result = self.run_ready()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "met: Priority",
                "met: Size",
                "met: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
                "set Status Ready on sh4i-yurei/claude-config#23",
            ],
        )
        edits = [
            call
            for call in self.calls()
            if call["args"][:2] == ["project", "item-edit"]
        ]
        self.assertEqual(len(edits), 1)
        self.assertEqual(
            edits[0]["args"],
            [
                "project",
                "item-edit",
                "--id",
                "PVTI_lAHODeM_nM4BnbqbzhDfKR0",
                "--project-id",
                "PVT_kwHODeM_nM4Bnbqb",
                "--field-id",
                "PVTSSF_lAHODeM_nM4BnbqbzhmAVQk",
                "--single-select-option-id",
                "3f5349bd",
                "--format",
                "json",
            ],
        )

    def test_check_reports_same_result_without_edit(self):
        self.state["board_fields"] = {
            "priority": "P1",
            "size": "Feature",
            "estimate": 2,
        }
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "met: Priority",
                "met: Size",
                "met: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
                "ready: sh4i-yurei/claude-config#23",
            ],
        )
        self.assertFalse(
            any(c["args"][:2] == ["project", "item-edit"] for c in self.calls())
        )

    def test_missing_fields_and_sections_are_all_named(self):
        result = self.run_ready()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "unmet: Priority",
                "unmet: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )
        self.assertFalse(
            any(c["args"][:2] == ["project", "item-edit"] for c in self.calls())
        )

    def test_preform_issue_names_scope_and_required_section(self):
        result = self.run_ready("22", "--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "unmet: a scope: label",
                "unmet: Done when",
                "met: Priority",
                "met: Size",
                "met: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_open_blocker_refuses(self):
        # #23 is real input; this scenario changes only its blocked_by list.
        blocker = json.loads((FIXTURES / "ready-issue-22.json").read_text())
        blocker["repository"] = {"full_name": REPO}
        self.state["blocked_by"] = [blocker]
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "unmet: Priority",
                "unmet: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "unmet: open blocker sh4i-yurei/claude-config#22",
                "met: Architecture design link not required",
            ],
        )

    def test_open_blocker_uses_its_own_repository(self):
        # #23 is real input; this scenario changes only its blocked_by list.
        blocker = json.loads((FIXTURES / "ready-infra-60-blocked.json").read_text())[0]
        blocker["state"] = "open"
        self.state["blocked_by"] = [blocker]
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "unmet: Priority",
                "unmet: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "unmet: open blocker sh4i-yurei/ci-workflows#4",
                "met: Architecture design link not required",
            ],
        )

    def test_malformed_blockers_response_is_a_github_error(self):
        self.state["blocked_by"] = {}
        result = self.run_ready("23", "--check")
        self.assertEqual(
            (result.returncode, result.stdout),
            (2, "sh4i-yurei/claude-config#23: blocked_by response is not a list\n"),
        )
        self.assertFalse(
            any(c["args"][:2] == ["project", "item-edit"] for c in self.calls())
        )

    def test_architecture_requires_design_line(self):
        # #23 is real input; this scenario changes only its Size.
        self.state["board_fields"] = {"size": "Architecture"}
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "unmet: Priority",
                "met: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "unmet: Design: line",
            ],
        )

    def test_unmapped_and_absent_board_item_are_configuration_errors(self):
        result = self.run_ready("23", "--check", repo="sh4i-yurei/unmapped")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "no board mapping for sh4i-yurei/unmapped\n")
        self.state["missing_board_item"] = True
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout,
            "sh4i-yurei/claude-config#23 is not on its repository's board\n",
        )

    def test_labels_sections_and_rollup_accumulate(self):
        issue = json.loads((FIXTURES / "ready-issue-23.json").read_text())
        issue["labels"] = []
        issue["body"] = "### Done when\n\n_No response_\n"
        issue["milestone"] = None
        self.state["issue_fields"] = issue
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "unmet: one type: label",
                "unmet: a scope: label",
                "unmet: Done when",
                "unmet: Priority",
                "unmet: Size",
                "unmet: Estimate",
                "unmet: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_two_type_labels_and_empty_required_section(self):
        issue = json.loads((FIXTURES / "ready-issue-23.json").read_text())
        issue["labels"].append({"name": "type:bug"})
        issue["body"] = issue["body"].split("### Done when")[0] + "### Done when\n\n"
        self.state["issue_fields"] = issue
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "unmet: one type: label (type:feature, type:bug)",
                "met: a scope: label",
                "unmet: Done when",
                "unmet: Priority",
                "unmet: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_architecture_design_line_allows_ready(self):
        issue = json.loads((FIXTURES / "ready-issue-23.json").read_text())
        issue["body"] += "\nDesign: Global development workflow, decisions 31 to 33\n"
        self.state["issue_fields"] = issue
        self.state["board_fields"] = {
            "priority": "P1",
            "size": "Architecture",
            "estimate": 2,
        }
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "met: Priority",
                "met: Size",
                "met: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link",
                "ready: sh4i-yurei/claude-config#23",
            ],
        )

    def test_invalid_issue_references_name_the_expected_format(self):
        for reference in (
            "bad",
            "sh4i-yurei/claude-config#0",
            "sh4i-yurei/#23",
            "sh4i-yurei/claude-config#one",
            "sh4i-yurei/claude-config#1#2",
        ):
            with self.subTest(reference=reference):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = issue_tool.main(["ready", reference, "--check"])
                self.assertEqual(
                    (code, output.getvalue()), (2, "issue must be owner/repo#number\n")
                )

    def test_empty_board_fields_and_closed_blocker(self):
        blocker = json.loads((FIXTURES / "ready-issue-22.json").read_text())
        blocker["state"] = "closed"
        self.state["blocked_by"] = [blocker]
        self.state["board_fields"] = {"priority": "", "size": "", "estimate": ""}
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "unmet: Priority",
                "unmet: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_parent_satisfies_rollup_without_milestone(self):
        self.state["issue_fields"] = {"milestone": None}
        self.state["parent_response"] = json.loads(
            (FIXTURES / "ready-infra-60-parent.json").read_text()
        )
        self.state["board_fields"] = {
            "priority": "P1",
            "size": "Feature",
            "estimate": 2,
        }
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("met: milestone or parent\n", result.stdout)

    def test_unexpected_parent_error_is_a_github_error(self):
        self.state["parent_error"] = "gh: Not Found (HTTP 404)"
        result = self.run_ready("23", "--check")
        self.assertEqual(
            (result.returncode, result.stdout), (2, "gh: Not Found (HTTP 404)\n")
        )

    def test_issue_one_is_a_valid_reference(self):
        result = self.run_ready("1", "--check")
        self.assertEqual(
            (result.returncode, result.stdout),
            (2, "sh4i-yurei/claude-config#1 is not on its repository's board\n"),
        )

    def test_missing_workflow_configuration_names_the_file(self):
        config_dir = self.root / "config"
        config_dir.mkdir()
        shutil.copy(ROOT / "tools/workflow/workflow.toml", config_dir)
        with patch.object(workflow_config, "DIRECTORY", config_dir):
            result = self.run_ready("23", "--check")
        self.assertEqual(
            (result.returncode, result.stdout), (2, "labels.toml: missing\n")
        )

    def test_repository_without_scope_labels_does_not_require_one(self):
        config_dir = self.root / "config"
        config_dir.mkdir()
        shutil.copy(ROOT / "tools/workflow/workflow.toml", config_dir)
        labels = (ROOT / "tools/workflow/labels.toml").read_text()
        labels = labels.split('[repository."sh4i-yurei/claude-config"', 1)[0]
        (config_dir / "labels.toml").write_text(labels)
        issue = json.loads((FIXTURES / "ready-issue-23.json").read_text())
        issue["labels"] = [
            label for label in issue["labels"] if not label["name"].startswith("scope:")
        ]
        self.state["issue_fields"] = issue
        with patch.object(workflow_config, "DIRECTORY", config_dir):
            result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: scope: label not required",
                "met: required form sections",
                "unmet: Priority",
                "unmet: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_board_item_without_content_is_not_on_board(self):
        self.state["board_item_without_content"] = True
        result = self.run_ready("23", "--check")
        self.assertEqual(
            (result.returncode, result.stdout),
            (2, "sh4i-yurei/claude-config#23 is not on its repository's board\n"),
        )

    def test_missing_issue_labels_reports_type_and_scope(self):
        self.state["issue_without_labels"] = True
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "unmet: one type: label",
                "unmet: a scope: label",
                "met: required form sections",
                "unmet: Priority",
                "unmet: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_unknown_and_multiple_scope_labels_are_named(self):
        for names, expected in (
            (["scope:unknown"], "unmet: a scope: label (scope:unknown)"),
            (
                ["scope:ci", "scope:unknown"],
                "unmet: a scope: label (scope:ci, scope:unknown)",
            ),
        ):
            with self.subTest(names=names):
                issue = json.loads((FIXTURES / "ready-issue-23.json").read_text())
                issue["labels"] = [
                    label
                    for label in issue["labels"]
                    if not label["name"].startswith("scope:")
                ]
                issue["labels"].extend({"name": name} for name in names)
                self.state["issue_fields"] = issue
                result = self.run_ready("23", "--check")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        "met: one type: label",
                        expected,
                        "met: required form sections",
                        "unmet: Priority",
                        "unmet: Size",
                        "unmet: Estimate",
                        "met: milestone or parent",
                        "met: no open blocking issues",
                        "met: Architecture design link not required",
                    ],
                )

    def test_ambiguous_type_uses_only_sections_all_forms_require(self):
        issue = json.loads((FIXTURES / "ready-issue-23.json").read_text())
        issue["labels"] = [
            {"name": "type:fix"},
            {"name": "type:unknown"},
            {"name": "scope:ci"},
        ]
        self.state["issue_fields"] = issue
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "unmet: one type: label (type:fix, type:unknown)",
                "met: a scope: label",
                "met: required form sections",
                "unmet: Priority",
                "unmet: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_bug_form_requires_its_own_section_and_ignores_markdown(self):
        issue = json.loads((FIXTURES / "ready-issue-23.json").read_text())
        issue["labels"][0]["name"] = "type:fix"
        self.state["issue_fields"] = issue
        response = json.loads((FIXTURES / "form-bug.yml.json").read_text())
        form = yaml.safe_load(base64.b64decode(response["content"]))
        form["body"].append(
            {
                "type": "markdown",
                "attributes": {"label": "Instructions"},
                "validations": {"required": True},
            }
        )
        response["content"] = base64.b64encode(yaml.safe_dump(form).encode()).decode()
        self.state["form_responses"] = {"bug.yml": response}
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "unmet: What happened",
                "unmet: Priority",
                "unmet: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_form_without_labels_reports_unmatched_type(self):
        response = json.loads((FIXTURES / "form-feature.yml.json").read_text())
        form = yaml.safe_load(base64.b64decode(response["content"]))
        form.pop("labels")
        response["content"] = base64.b64encode(yaml.safe_dump(form).encode()).decode()
        self.state["form_responses"] = {"feature.yml": response}
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "unmet: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "unmet: Priority",
                "unmet: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_ready_command_help_describes_its_interface(self):
        for args, expected in (
            (
                ["--help"],
                "usage: issue.py [-h] {open,ready} ...\n\n"
                "Open a checked GitHub issue and place open repository issues on its board.\n\n"
                "positional arguments:\n"
                "  {open,ready}\n"
                "    open        create a checked issue from a TOML file\n"
                "    ready       check an issue's Definition of Ready\n\n"
                "options:\n"
                "  -h, --help    show this help message and exit\n",
            ),
            (
                ["ready", "--help"],
                "usage: issue.py ready [-h] [--check] issue\n\n"
                "positional arguments:\n"
                "  issue\n\n"
                "options:\n"
                "  -h, --help  show this help message and exit\n"
                "  --check\n",
            ),
        ):
            with self.subTest(args=args):
                output = io.StringIO()
                with (
                    patch.object(sys, "argv", ["issue.py", *args]),
                    redirect_stdout(output),
                    self.assertRaises(SystemExit) as raised,
                ):
                    issue_tool.main(args)
                help_text = output.getvalue()
                command_name = help_text.split(" [-h]", 1)[0].removeprefix("usage: ")
                expected_name = "issue.py ready" if args[0] == "ready" else "issue.py"
                help_text = help_text.replace(
                    f"usage: {command_name}", f"usage: {expected_name}", 1
                )
                self.assertEqual((raised.exception.code, help_text), (0, expected))


if __name__ == "__main__":
    unittest.main()
