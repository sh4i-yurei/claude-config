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
        self.workflow = self.root / "workflow"
        shutil.copytree(ROOT / "tools/workflow", self.workflow)
        directory = patch.object(workflow_config, "DIRECTORY", self.workflow)
        directory.start()
        self.addCleanup(directory.stop)
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
            FAKE_GH_WORKFLOW=str(self.workflow / "workflow.toml"),
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
        with (
            patch.dict(os.environ, self.env),
            redirect_stdout(output),
        ):
            code = issue_tool.main(["ready", f"{repo}#{number}", *options])
        return SimpleNamespace(returncode=code, stdout=output.getvalue(), stderr="")

    def calls(self):
        path = Path(self.env["FAKE_GH_CALLS"])
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def stacked_blocker(self, number=22, repo=REPO, state="open"):
        name = "issue-20.json" if number == 20 else f"ready-issue-{number}.json"
        blocker = json.loads((FIXTURES / name).read_text())
        blocker["repository"] = {"full_name": repo}
        blocker["state"] = state
        return blocker

    def linked(self, number=22, branch="agent/22-ready-check"):
        response = json.loads((FIXTURES / "linked-branches-64.json").read_text())
        response["data"]["repository"]["issue"]["linkedBranches"]["nodes"][0]["ref"][
            "name"
        ] = branch
        self.state.setdefault("linked_branches", {})[str(number)] = response

    def open_pull(self, branch="agent/22-ready-check"):
        pull = json.loads((FIXTURES / "pulls-chore-shell-ci.json").read_text())[0]
        pull["state"] = "open"
        pull["head"]["ref"] = branch
        pull["head"]["label"] = f"sh4i-yurei:{branch}"
        self.state.setdefault("pulls_by_head", {})[f"sh4i-yurei:{branch}"] = [pull]

    def ready_fields(self):
        self.state["board_fields"] = {
            "priority": "P2",
            "size": "Feature",
            "estimate": 2,
        }

    def test_stacked_on_requires_check_before_any_github_call(self):
        result = self.run_ready("23", "--stacked-on", f"{REPO}#22")
        self.assertEqual(
            (result.returncode, result.stdout), (2, "--stacked-on needs --check\n")
        )
        self.assertEqual(self.calls(), [])

    def test_stacked_on_requires_full_issue_reference_before_any_github_call(self):
        result = self.run_ready("23", "--check", "--stacked-on", "claude-config#22")
        self.assertEqual(
            (result.returncode, result.stdout),
            (2, "--stacked-on must be owner/repo#number\n"),
        )
        self.assertEqual(self.calls(), [])

    def test_stacked_open_blocker_is_ready_with_linked_agent_pull(self):
        self.state["blocked_by"] = [self.stacked_blocker()]
        self.ready_fields()
        self.linked()
        self.open_pull()
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(
            (result.returncode, result.stdout.splitlines()),
            (
                0,
                [
                    "met: one type: label",
                    "met: a scope: label",
                    "met: required form sections",
                    "met: Priority",
                    "met: Size",
                    "met: Estimate",
                    "met: milestone or parent",
                    f"met: open blocker {REPO}#22 sits lower in this stack on agent/22-ready-check",
                    "met: Architecture design link not required",
                    f"ready: {REPO}#23",
                ],
            ),
        )
        self.assertEqual(
            [
                call["args"][1]
                for call in self.calls()
                if call["args"][:1] == ["api"] and "/pulls?" in call["args"][1]
            ],
            [
                "repos/sh4i-yurei/claude-config/pulls?state=open&head=sh4i-yurei%3Aagent%2F22-ready-check"
            ],
        )
        self.assertFalse(
            any(call["args"][:2] == ["project", "item-edit"] for call in self.calls())
        )

    def test_stacked_non_agent_branch_does_not_read_pulls(self):
        self.state["blocked_by"] = [self.stacked_blocker()]
        self.ready_fields()
        self.state["linked_branches"] = {
            "22": json.loads((FIXTURES / "linked-branches-64.json").read_text())
        }
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"unmet: open blocker {REPO}#22 has no open pull request from a linked agent/ branch\n",
            result.stdout,
        )
        self.assertFalse(
            any(
                "/pulls?" in call["args"][1]
                for call in self.calls()
                if call["args"][:1] == ["api"]
            )
        )

    def test_stacked_agent_branch_without_open_pull_is_unmet(self):
        self.state["blocked_by"] = [self.stacked_blocker()]
        self.ready_fields()
        self.linked()
        self.state["pulls_by_head"] = {
            "sh4i-yurei:agent/22-ready-check": json.loads(
                (FIXTURES / "pulls-open-none.json").read_text()
            )
        }
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"unmet: open blocker {REPO}#22 has no open pull request from a linked agent/ branch\n",
            result.stdout,
        )

    def test_stacked_no_linked_branches_is_unmet_without_pull_read(self):
        self.state["blocked_by"] = [self.stacked_blocker()]
        self.ready_fields()
        self.state["linked_branches"] = {
            "22": json.loads((FIXTURES / "linked-branches-63.json").read_text())
        }
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"unmet: open blocker {REPO}#22 has no open pull request from a linked agent/ branch\n",
            result.stdout,
        )
        self.assertFalse(
            any(
                "/pulls?" in call["args"][1]
                for call in self.calls()
                if call["args"][:1] == ["api"]
            )
        )

    def test_stacked_null_ref_is_skipped(self):
        self.state["blocked_by"] = [self.stacked_blocker()]
        self.ready_fields()
        self.linked()
        nodes = self.state["linked_branches"]["22"]["data"]["repository"]["issue"][
            "linkedBranches"
        ]["nodes"]
        nodes.insert(0, {"ref": None})
        self.open_pull()
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            f"met: open blocker {REPO}#22 sits lower in this stack on agent/22-ready-check\n",
            result.stdout,
        )

    def test_stacked_null_linked_branch_node_is_skipped(self):
        self.state["blocked_by"] = [self.stacked_blocker()]
        self.ready_fields()
        self.linked()
        nodes = self.state["linked_branches"]["22"]["data"]["repository"]["issue"][
            "linkedBranches"
        ]["nodes"]
        nodes.insert(0, None)
        self.open_pull()
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            f"met: open blocker {REPO}#22 sits lower in this stack on agent/22-ready-check\n",
            result.stdout,
        )

    def test_stacked_uses_first_linked_agent_branch_with_open_pull(self):
        self.state["blocked_by"] = [self.stacked_blocker()]
        self.ready_fields()
        self.linked()
        nodes = self.state["linked_branches"]["22"]["data"]["repository"]["issue"][
            "linkedBranches"
        ]["nodes"]
        nodes.insert(0, {"ref": {"name": "agent/22-no-pull"}})
        self.open_pull()
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            f"met: open blocker {REPO}#22 sits lower in this stack on agent/22-ready-check\n",
            result.stdout,
        )
        self.assertEqual(
            [
                call["args"][1]
                for call in self.calls()
                if call["args"][:1] == ["api"] and "/pulls?" in call["args"][1]
            ],
            [
                "repos/sh4i-yurei/claude-config/pulls?state=open&head=sh4i-yurei%3Aagent%2F22-no-pull",
                "repos/sh4i-yurei/claude-config/pulls?state=open&head=sh4i-yurei%3Aagent%2F22-ready-check",
            ],
        )

    def test_stacked_paginates_linked_branches(self):
        self.state["blocked_by"] = [self.stacked_blocker()]
        self.ready_fields()
        self.linked()
        nodes = self.state["linked_branches"]["22"]["data"]["repository"]["issue"][
            "linkedBranches"
        ]["nodes"]
        nodes[:] = [{"ref": {"name": f"feat/other-{n}"}} for n in range(100)] + nodes
        self.open_pull()
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            f"met: open blocker {REPO}#22 sits lower in this stack on agent/22-ready-check\n",
            result.stdout,
        )
        calls = [
            call["args"]
            for call in self.calls()
            if call["args"][:2] == ["api", "graphql"]
            and "linkedBranches" in " ".join(call["args"])
        ]
        self.assertEqual(len(calls), 2)
        self.assertIn("cursor=100", calls[1])
        self.assertEqual(calls[1][calls[1].index("cursor=100") - 1], "-f")

    def test_stacked_name_without_open_blocker_is_unmet(self):
        self.ready_fields()
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"met: no open blocking issues\nunmet: stacked-on {REPO}#22 is not an open blocker of this issue\n",
            result.stdout,
        )
        self.assertFalse(
            any("linkedBranches" in " ".join(call["args"]) for call in self.calls())
        )

    def test_stacked_closed_blocker_is_unmet(self):
        self.state["blocked_by"] = [self.stacked_blocker(state="closed")]
        self.ready_fields()
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"unmet: stacked-on {REPO}#22 is not an open blocker of this issue\n",
            result.stdout,
        )
        self.assertFalse(
            any("linkedBranches" in " ".join(call["args"]) for call in self.calls())
        )

    def test_stacked_blocker_in_other_repository_is_unmet(self):
        blocker = json.loads((FIXTURES / "ready-infra-60-blocked.json").read_text())[0]
        blocker["state"] = "open"
        self.state["blocked_by"] = [blocker]
        self.ready_fields()
        result = self.run_ready(
            "23", "--check", "--stacked-on", "sh4i-yurei/ci-workflows#4"
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "unmet: open blocker sh4i-yurei/ci-workflows#4 is in another repository\n",
            result.stdout,
        )
        self.assertFalse(
            any("linkedBranches" in " ".join(call["args"]) for call in self.calls())
        )

    def test_stacked_unlisted_open_blocker_still_fails(self):
        other = json.loads((FIXTURES / "ready-infra-60-blocked.json").read_text())[0]
        other["state"] = "open"
        self.state["blocked_by"] = [self.stacked_blocker(), other]
        self.ready_fields()
        self.linked()
        self.open_pull()
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"met: open blocker {REPO}#22 sits lower in this stack on agent/22-ready-check\nunmet: open blocker sh4i-yurei/ci-workflows#4\n",
            result.stdout,
        )

    def test_stacked_named_blocker_after_unlisted_blocker_is_checked(self):
        self.state["blocked_by"] = [self.stacked_blocker(), self.stacked_blocker(20)]
        self.linked(20, "agent/20-open")
        self.open_pull("agent/20-open")
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#20")
        self.assertIn(
            f"unmet: open blocker {REPO}#22\nmet: open blocker {REPO}#20 sits lower in this stack on agent/20-open\n",
            result.stdout,
        )

    def test_stacked_named_blocker_after_cross_repository_blocker_is_checked(self):
        other = json.loads((FIXTURES / "ready-infra-60-blocked.json").read_text())[0]
        other["state"] = "open"
        self.state["blocked_by"] = [other, self.stacked_blocker()]
        self.linked()
        self.open_pull()
        result = self.run_ready(
            "23",
            "--check",
            "--stacked-on",
            "sh4i-yurei/ci-workflows#4",
            "--stacked-on",
            f"{REPO}#22",
        )
        self.assertIn(
            f"unmet: open blocker sh4i-yurei/ci-workflows#4 is in another repository\nmet: open blocker {REPO}#22 sits lower in this stack on agent/22-ready-check\n",
            result.stdout,
        )

    def test_stacked_multiple_blockers_preserve_github_order(self):
        self.state["blocked_by"] = [self.stacked_blocker(), self.stacked_blocker(20)]
        self.ready_fields()
        self.linked()
        self.linked(20, "agent/20-open")
        self.open_pull()
        self.open_pull("agent/20-open")
        result = self.run_ready(
            "23", "--check", "--stacked-on", f"{REPO}#22", "--stacked-on", f"{REPO}#20"
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(
            f"met: open blocker {REPO}#22 sits lower in this stack on agent/22-ready-check\nmet: open blocker {REPO}#20 sits lower in this stack on agent/20-open\n",
            result.stdout,
        )

    def test_stacked_linked_branches_graphql_error_is_reported(self):
        self.state["blocked_by"] = [self.stacked_blocker()]
        self.state["linked_graphql_error"] = (
            "API rate limit already exceeded for user ID 232996764."
        )
        result = self.run_ready("23", "--check", "--stacked-on", f"{REPO}#22")
        self.assertEqual(
            (result.returncode, result.stdout),
            (2, "API rate limit already exceeded for user ID 232996764.\n"),
        )
        self.assertFalse(
            any(call["args"][:2] == ["project", "item-edit"] for call in self.calls())
        )

    def test_board_read_uses_one_graphql_request_with_mapped_variables(self):
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout)
        reads = [
            call["args"]
            for call in self.calls()
            if call["args"][:2] == ["api", "graphql"]
        ]
        self.assertEqual(len(reads), 1)
        self.assertIn("owner=sh4i-yurei", reads[0])
        self.assertIn("number=2", reads[0])
        self.assertIn(f"url=https://github.com/{REPO}/issues/23", reads[0])
        self.assertFalse(
            any(
                call["args"][:2]
                in (
                    ["project", "view"],
                    ["project", "field-list"],
                    ["project", "item-list"],
                )
                for call in self.calls()
            )
        )

    def test_infrastructure_board_read_uses_its_mapping(self):
        self.run_ready("60", "--check", repo="sh4i-yurei/keepbreathing-infra")
        reads = [
            call["args"]
            for call in self.calls()
            if call["args"][:2] == ["api", "graphql"]
        ]
        self.assertEqual(len(reads), 1)
        self.assertIn("owner=sh4i-yurei", reads[0])
        self.assertIn("number=3", reads[0])

    def test_graphql_rate_limit_is_reported_without_edit(self):
        self.state["graphql_error"] = (
            "API rate limit already exceeded for user ID 232996764."
        )
        result = self.run_ready("23", "--check")
        self.assertEqual(
            (result.returncode, result.stdout),
            (2, "API rate limit already exceeded for user ID 232996764.\n"),
        )
        self.assertFalse(
            any(call["args"][:2] == ["project", "item-edit"] for call in self.calls())
        )

    def test_graphql_reports_each_error_message_in_order(self):
        self.state["graphql_error"] = ["first GitHub message", "second GitHub message"]
        result = self.run_ready("23", "--check")
        self.assertEqual(
            (result.returncode, result.stdout),
            (2, "first GitHub message\nsecond GitHub message\n"),
        )

    def test_card_fields_are_read_by_field_name(self):
        self.state["board_fields"] = {"priority": "P2", "size": "Feature"}
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("met: Priority\nmet: Size\nunmet: Estimate\n", result.stdout)
        self.state["board_fields"] = {}
        result = self.run_ready("23", "--check")
        self.assertIn("unmet: Priority\nunmet: Size\nunmet: Estimate\n", result.stdout)

    def test_null_named_fields_are_unset(self):
        answer = json.loads((FIXTURES / "card-query.json").read_text())
        card = answer["data"]["resource"]["projectItems"]["nodes"][0]
        card.update(priority=None, size=None, estimate=None)
        self.state["card_response"] = answer
        self.state["preserve_nodes"] = True
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout)
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

    def test_null_estimate_keeps_priority_and_size_met(self):
        self.state["board_fields"] = {
            "priority": "P1",
            "size": "Feature",
            "estimate": None,
        }
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "met: Priority",
                "met: Size",
                "unmet: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_untyped_named_field_is_unset(self):
        answer = json.loads((FIXTURES / "card-query.json").read_text())
        answer["data"]["resource"]["projectItems"]["nodes"][0]["priority"] = {}
        self.state["card_response"] = answer
        self.state["preserve_nodes"] = True
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "unmet: Priority",
                "met: Size",
                "met: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_empty_named_field_is_unset(self):
        answer = json.loads((FIXTURES / "card-query.json").read_text())
        answer["data"]["resource"]["projectItems"]["nodes"][0]["priority"] = {
            "name": ""
        }
        self.state["card_response"] = answer
        self.state["preserve_nodes"] = True
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "met: one type: label",
                "met: a scope: label",
                "met: required form sections",
                "unmet: Priority",
                "met: Size",
                "met: Estimate",
                "met: milestone or parent",
                "met: no open blocking issues",
                "met: Architecture design link not required",
            ],
        )

    def test_card_must_match_mapped_project_and_owner(self):
        base = json.loads((FIXTURES / "card-query.json").read_text())
        for change in ("number", "owner", "empty"):
            with self.subTest(change=change):
                answer = json.loads(json.dumps(base))
                nodes = answer["data"]["resource"]["projectItems"]["nodes"]
                if change == "number":
                    nodes[0]["project"]["number"] = 1
                elif change == "owner":
                    nodes[0]["project"]["owner"]["login"] = "someone-else"
                else:
                    nodes.clear()
                self.state["card_response"] = answer
                result = self.run_ready("23", "--check")
                self.assertEqual(
                    (result.returncode, result.stdout),
                    (2, f"{REPO}#23 is not on its repository's board\n"),
                )
                self.assertFalse(
                    any(
                        call["args"][:2] == ["project", "item-edit"]
                        for call in self.calls()
                    )
                )

    def test_other_board_cards_do_not_block_ready_check(self):
        base = json.loads((FIXTURES / "card-query.json").read_text())
        for other_card in (
            {"id": "PVTI_other", "project": None},
            {"project": {"number": 1, "owner": {"login": "sh4i-yurei"}}},
        ):
            with self.subTest(other_card=other_card):
                answer = json.loads(json.dumps(base))
                answer["data"]["resource"]["projectItems"]["nodes"].insert(
                    0, other_card
                )
                self.state["card_response"] = answer
                self.state["preserve_nodes"] = True
                result = self.run_ready("23", "--check")
                self.assertEqual(
                    (result.returncode, result.stdout.splitlines()),
                    (
                        0,
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
                            f"ready: {REPO}#23",
                        ],
                    ),
                )

    def test_mapped_card_without_id_refuses_before_write(self):
        answer = json.loads((FIXTURES / "card-query.json").read_text())
        answer["data"]["resource"]["projectItems"]["nodes"][0].pop("id")
        self.state["card_response"] = answer
        result = self.run_ready("23")
        self.assertEqual(
            (result.returncode, result.stdout), (2, "board card is incomplete\n")
        )
        self.assertFalse(
            any(call["args"][:2] == ["project", "item-edit"] for call in self.calls())
        )

    def test_missing_ready_option_refuses_before_write(self):
        answer = json.loads((FIXTURES / "card-query.json").read_text())
        options = answer["data"]["repositoryOwner"]["projectV2"]["field"]["options"]
        options[:] = [option for option in options if option["name"] != "Ready"]
        self.state["card_response"] = answer
        result = self.run_ready("23", "--check")
        self.assertEqual(
            (result.returncode, result.stdout),
            (2, "project sh4i-yurei/2: no Status Ready option\n"),
        )
        self.assertFalse(
            any(call["args"][:2] == ["project", "item-edit"] for call in self.calls())
        )

    def test_ready_uses_tooling_board_for_every_project_call(self):
        result = self.run_ready()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        reads = [
            call["args"]
            for call in self.calls()
            if call["args"][:2] == ["api", "graphql"]
        ]
        self.assertEqual(len(reads), 1)
        self.assertIn("number=2", reads[0])
        self.assertIn("owner=sh4i-yurei", reads[0])

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
                "PVTI_lAHODeM_nM4Bo2B8zhE6DaM",
                "--project-id",
                "PVT_kwHODeM_nM4Bo2B8",
                "--field-id",
                "PVTSSF_lAHODeM_nM4Bo2B8zhnUO3k",
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

    def test_ready_uses_board_owner_from_mapping(self):
        path = self.workflow / "workflow.toml"
        path.write_text(
            path.read_text().replace(
                '"Tooling" = { owner = "sh4i-yurei", number = 2 }',
                '"Tooling" = { owner = "other-owner", number = 2 }',
            )
        )
        answer = json.loads((FIXTURES / "card-query.json").read_text())
        answer["data"]["resource"]["projectItems"]["nodes"][0]["project"]["owner"][
            "login"
        ] = "other-owner"
        self.state["card_response"] = answer
        self.state["preserve_nodes"] = True
        result = self.run_ready("23", "--check")
        self.assertEqual(result.returncode, 0, result.stdout)
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
                f"ready: {REPO}#23",
            ],
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
                "usage: issue.py [-h] {open,debt,ready} ...\n\n"
                "Open checked GitHub issues, file review debt, and check readiness.\n\n"
                "positional arguments:\n"
                "  {open,debt,ready}\n"
                "    open             create a checked issue from a TOML file\n"
                "    debt             file a build's review leftovers from its final round\n"
                "    ready            check an issue's Definition of Ready\n\n"
                "options:\n"
                "  -h, --help         show this help message and exit\n",
            ),
            (
                ["ready", "--help"],
                "usage: issue.py ready [-h] [--check] [--stacked-on STACKED_ON] issue\n\n"
                "positional arguments:\n"
                "  issue\n\n"
                "options:\n"
                "  -h, --help            show this help message and exit\n"
                "  --check\n"
                "  --stacked-on STACKED_ON\n"
                "                        an open blocker that sits lower in this stack; needs\n"
                "                        --check\n",
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
