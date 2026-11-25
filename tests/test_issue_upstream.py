from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib
from unittest import TestCase
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "tools/workflow"
FIXTURES = ROOT / "tests/fixtures/issue_upstream"
sys.path.insert(0, str(WORKFLOW))
sys.path.insert(0, str(ROOT))
import tools.workflow.issue as issue_tool
import tools.workflow.config as package_config
import config as workflow_config


REPO = "mvschwarz/openrig"
TRACKING = "sh4i-yurei/workflow-engine"
APPROVAL = "qitem-approval"
TITLE = "Per-seat list of MCP servers to block, through deniedMcpServers in the seat's settings"
BODY = (FIXTURES / "draft.md").read_text()


class IssueUpstream(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workflow = self.root / "workflow"
        shutil.copytree(WORKFLOW, self.workflow)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for tool in ("gh", "rig"):
            fake = bin_dir / tool
            shutil.copy(FIXTURES / f"fake_{tool}.py", fake)
            fake.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            FAKE_GH_CALLS=str(self.root / "gh-calls.jsonl"),
            FAKE_GH_STATE=str(self.root / "gh-state.json"),
            FAKE_GH_WORKFLOW=str(self.workflow / "workflow.toml"),
            FAKE_GH_FIXTURES=str(FIXTURES),
            FAKE_RIG_CALLS=str(self.root / "rig-calls.jsonl"),
            FAKE_RIG_STATE=str(self.root / "rig-state.json"),
        )
        self.gh_state = {}
        self.rig_state = {
            "approval": {
                "sourceSession": "main-lead@hq",
                "destinationSession": "filing@tooling",
                "body": "File the upstream request in mvschwarz/openrig.",
            }
        }
        self.save()

    def save(self):
        Path(self.env["FAKE_GH_STATE"]).write_text(json.dumps(self.gh_state))
        Path(self.env["FAKE_RIG_STATE"]).write_text(json.dumps(self.rig_state))

    def calls(self, tool):
        path = Path(self.env[f"FAKE_{tool.upper()}_CALLS"])
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def run_upstream(self, **changes):
        values = dict(
            repo=REPO,
            title=TITLE,
            body=BODY,
            approval=APPROVAL,
            tracking=TRACKING,
            labels=["enhancement"],
        )
        options = changes.pop("options", ["--dry-run"])
        omitted = changes.pop("omit", ())
        values.update(changes)
        for key in omitted:
            values.pop(key)
        path = self.root / "issue.toml"

        def toml_value(value):
            if isinstance(value, list):
                return "[" + ", ".join(json.dumps(item) for item in value) + "]"
            return json.dumps(value)

        path.write_text(
            "".join(f"{key} = {toml_value(value)}\n" for key, value in values.items())
        )
        output = io.StringIO()
        with (
            patch.dict(os.environ, self.env),
            patch.object(workflow_config, "DIRECTORY", self.workflow),
            redirect_stdout(output),
        ):
            code = issue_tool.main(["upstream", str(path), *options])
        return code, output.getvalue()

    def run_open(self, content, *options):
        path = self.root / "open.toml"
        path.write_text(content)
        output = io.StringIO()
        with (
            patch.dict(os.environ, self.env),
            patch.object(workflow_config, "DIRECTORY", self.workflow),
            redirect_stdout(output),
        ):
            code = issue_tool.main(["open", str(path), *options])
        return code, output.getvalue()

    def open_file(self, extra="", repo="sh4i-yurei/claude-config"):
        return (
            f'repo = "{repo}"\nkind = "feature"\ntitle = "A feature"\n'
            f'scope = "scope:ci"\n{extra}\n[body]\ndone = "It works"\n'
        )

    def assert_no_writes(self):
        self.assertFalse(any("--method" in call["args"] for call in self.calls("gh")))
        self.assertFalse(
            any(call[:2] == ["queue", "update"] for call in self.calls("rig"))
        )

    def test_dry_run_reads_everything_without_writing(self):
        code, output = self.run_upstream()
        self.assertEqual(code, 0, output)
        prefix = f"Would call: POST repos/{REPO}/issues "
        self.assertEqual(
            json.loads(
                next(
                    line.removeprefix(prefix)
                    for line in output.splitlines()
                    if line.startswith(prefix)
                )
            ),
            {"title": TITLE, "body": BODY, "labels": ["enhancement"]},
        )
        self.assertIn(
            f"Filed upstream as <upstream link> with approval {APPROVAL}.", output
        )
        self.assertIn("Upstream: " + TITLE, output)
        self.assertIn(
            f"Would call: rig queue update {APPROVAL} --note Filed upstream: <upstream link>; tracking: <tracking link>\n",
            output,
        )
        self.assert_no_writes()

    def test_dry_run_preserves_non_ascii_and_optional_labels(self):
        code, output = self.run_upstream(title=TITLE + " é", omit=("labels",))
        self.assertEqual(code, 0, output)
        self.assertIn('"title": "' + TITLE + ' é"', output)
        self.assertNotIn("\\u00e9", output)
        self.assertIn('"labels": []', output)

    def test_dry_run_prints_complete_preview(self):
        body = "A short body."
        code, output = self.run_upstream(body=body)
        self.assertEqual(code, 0, output)
        tracking_body = (
            f"### Project, step, and reason\n\nFiled upstream as <upstream link> with approval {APPROVAL}.\n\n"
            f"### What changes\n\n> {TITLE}\n> {body}\n\n"
            f"### Done when\n\n{REPO} resolves or declines the request, and this issue closes with the outcome.\n"
        )
        expected = (
            f"Would call: POST repos/{REPO}/issues "
            + json.dumps(
                {"title": TITLE, "body": body, "labels": ["enhancement"]},
                ensure_ascii=False,
            )
            + "\nRendered body:\n"
            + tracking_body
            + "\nWould call: POST repos/"
            + TRACKING
            + "/issues "
            + json.dumps(
                {
                    "title": "Upstream: " + TITLE,
                    "body": tracking_body,
                    "labels": ["type:chore", "upstream"],
                },
                ensure_ascii=False,
            )
            + "\nWould call: project item-add 4 --owner sh4i-yurei --url NEW_ISSUE_URL\n"
            + "Would call: project item-edit Status Backlog on new issue; leave Priority, Size, Estimate and Iteration empty\n"
            + f"Would call: rig queue update {APPROVAL} --note Filed upstream: <upstream link>; tracking: <tracking link>\n"
        )
        self.assertEqual(output, expected)

    def test_files_upstream_then_tracking_then_notes_approval(self):
        code, output = self.run_upstream(options=[])
        self.assertEqual(code, 0, output)
        posts = [
            call
            for call in self.calls("gh")
            if "--method" in call["args"]
            and call["args"][call["args"].index("--method") + 1] == "POST"
            and call["args"][1].endswith("/issues")
        ]
        self.assertEqual(
            [call["args"][1] for call in posts],
            [f"repos/{REPO}/issues", f"repos/{TRACKING}/issues"],
        )
        first, second = [json.loads(call["input"]) for call in posts]
        self.assertEqual(
            first, {"title": TITLE, "body": BODY, "labels": ["enhancement"]}
        )
        self.assertEqual(second["title"], "Upstream: " + TITLE)
        self.assertEqual(second["labels"], ["type:chore", "upstream"])
        self.assertIn(
            f"### Project, step, and reason\n\nFiled upstream as https://github.com/{REPO}/issues/99 with approval {APPROVAL}.",
            second["body"],
        )
        self.assertIn(
            "### What changes\n\n"
            + "\n".join("> " + line for line in (TITLE + "\n" + BODY).splitlines()),
            second["body"],
        )
        self.assertIn(
            f"### Done when\n\n{REPO} resolves or declines the request, and this issue closes with the outcome.",
            second["body"],
        )
        self.assertIn(f"filed upstream: https://github.com/{REPO}/issues/99\n", output)
        self.assertIn(f"tracking: https://github.com/{TRACKING}/issues/99\n", output)
        self.assertIn(
            [
                "queue",
                "update",
                APPROVAL,
                "--note",
                f"Filed upstream: https://github.com/{REPO}/issues/99; tracking: https://github.com/{TRACKING}/issues/99",
            ],
            self.calls("rig"),
        )

    def test_approval_rules(self):
        cases = [
            (
                {
                    "body": "Yes to all three on the plan. (3) File the upstream request for a per-seat field that stops an MCP server outright, with no secrets, private paths or names."
                },
                f"approval {APPROVAL} doesn't name {REPO}",
            ),
            (
                {"body": "File in mvschwarz/openrig"},
                f"approval {APPROVAL} doesn't say upstream",
            ),
            (
                {"sourceSession": "openrig-team-owner@workflow-engine"},
                f"approval {APPROVAL} comes from openrig-team-owner@workflow-engine, not main-lead@hq",
            ),
            (
                {"destinationSession": "other@tooling"},
                f"approval {APPROVAL} is addressed to other@tooling, not filing@tooling",
            ),
        ]
        for change, problem in cases:
            with self.subTest(change=change):
                self.rig_state["approval"] = {
                    "sourceSession": "main-lead@hq",
                    "destinationSession": "filing@tooling",
                    "body": "File the upstream request in mvschwarz/openrig.",
                    **change,
                }
                self.save()
                code, output = self.run_upstream()
                self.assertEqual((code, output), (2, problem + "\n"))
        self.rig_state["missing"] = True
        self.save()
        code, output = self.run_upstream()
        self.assertEqual((code, output), (2, f"approval {APPROVAL} not found\n"))
        self.assert_no_writes()

    def test_existing_approval_and_title_are_refused(self):
        url = "https://github.com/mvschwarz/openrig/issues/44"
        self.gh_state["approval_hits"] = [
            {"html_url": url, "body": f"Filed with {APPROVAL}"}
        ]
        self.save()
        self.assertEqual(
            self.run_upstream(), (2, f"approval {APPROVAL} already filed {url}\n")
        )
        self.gh_state = {"title_hits": [{"html_url": url, "title": TITLE}]}
        self.save()
        self.assertEqual(
            self.run_upstream(), (2, f"{REPO} already has {url} with this title\n")
        )
        self.gh_state["title_hits"][0]["title"] += " changed"
        self.save()
        self.assertEqual(self.run_upstream()[0], 0)

    def test_approval_search_reads_first_middle_and_later_pages(self):
        url = "https://github.com/sh4i-yurei/workflow-engine/issues/44"
        hit = {"html_url": url, "body": f"Approval {APPROVAL}"}
        for position, count in ((0, 1), (34, 40), (100, 101)):
            with self.subTest(position=position):
                self.gh_state = {"approval_hits": [{} for _ in range(count)]}
                self.gh_state["approval_hits"][position] = hit
                self.save()
                self.assertEqual(
                    self.run_upstream(),
                    (2, f"approval {APPROVAL} already filed {url}\n"),
                )

    def test_title_search_requires_exact_title_by_authenticated_author(self):
        url = f"https://github.com/{REPO}/issues/44"
        self.gh_state["title_hits"] = [{"html_url": url, "title": TITLE}]
        self.save()
        self.assertEqual(
            self.run_upstream(),
            (2, f"{REPO} already has {url} with this title\n"),
        )
        searches = [
            call["args"][1]
            for call in self.calls("gh")
            if call["args"][1].startswith("search/issues")
        ]
        self.assertTrue(any("author%3A%40me" in endpoint for endpoint in searches))

    def test_label_with_slash_is_encoded(self):
        self.assertEqual(self.run_upstream(labels=["area/cli"])[0], 0)
        self.assertTrue(
            any(
                call["args"][1] == f"repos/{REPO}/labels/area%2Fcli"
                for call in self.calls("gh")
            )
        )

    def test_approval_requires_full_json_row_for_requested_id(self):
        self.rig_state["approval"]["body"] = (
            "File the upstream request in mvschwarz/openrig."
        )
        self.save()
        code, output = self.run_upstream()
        self.assertEqual(code, 0, output)
        self.assertIn(
            ["queue", "show", APPROVAL, "--full", "--json"], self.calls("rig")
        )

    def test_repo_and_tracking_boundaries(self):
        for repo in (
            "SH4I-YUREI/some-new-repo",
            "sh4i-yurei/claude-config",
            "sh4i-yurei/some-new-repo",
        ):
            with self.subTest(repo=repo):
                self.rig_state["approval"]["body"] = (
                    f"File the upstream request in {repo}."
                )
                self.save()
                code, output = self.run_upstream(repo=repo)
                self.assertEqual(
                    (code, output), (2, f"{repo} is one of ours; use issue.py open\n")
                )
        for repo in ("mvschwarz", "mvschwarz/", "/openrig"):
            with self.subTest(repo=repo):
                self.assertEqual(
                    self.run_upstream(repo=repo), (2, "repo must be owner/name\n")
                )
        self.rig_state["approval"]["body"] = f"File the upstream request in {REPO}."
        self.save()
        self.assertEqual(
            self.run_upstream(tracking=REPO),
            (2, f"tracking {REPO} has no board mapping\n"),
        )
        self.assert_no_writes()

    def test_approval_name_problem_survives_ours_refusal(self):
        self.rig_state["approval"]["body"] = "File upstream elsewhere."
        self.save()
        code, output = self.run_upstream(repo="sh4i-yurei/claude-config")
        self.assertEqual(code, 2)
        self.assertEqual(
            output.splitlines(),
            [
                "sh4i-yurei/claude-config is one of ours; use issue.py open",
                f"approval {APPROVAL} doesn't name sh4i-yurei/claude-config",
            ],
        )

    def test_whoami_failure_joins_other_problems(self):
        self.rig_state["whoami_failure"] = "seat unavailable"
        self.rig_state["approval"]["sourceSession"] = "other@hq"
        self.save()
        code, output = self.run_upstream(body=BODY + "Mark asked.")
        self.assertEqual(
            (code, output),
            (
                2,
                "seat unavailable\n"
                f"approval {APPROVAL} comes from other@hq, not main-lead@hq\n"
                'body has a personal name: "Mark"\n',
            ),
        )

    def test_missing_sender_is_named_without_traceback(self):
        self.rig_state["missing_sender"] = True
        self.save()
        code, output = self.run_upstream()
        self.assertEqual((code, output), (2, "rig whoami returned no seat address\n"))

    def test_labels_and_text_rules(self):
        self.gh_state["missing_labels"] = ["nosuchlabel-xyz"]
        self.save()
        self.assertEqual(
            self.run_upstream(labels=["enhancement", "nosuchlabel-xyz"]),
            (2, f"label nosuchlabel-xyz doesn't exist in {REPO}\n"),
        )
        self.gh_state = {}
        self.save()
        cases = [
            ("Mark asked for this.", 'a personal name: "Mark"'),
            (
                "See workflow-upkeep-rules@tooling.",
                'a seat address: "workflow-upkeep-rules@tooling"',
            ),
            ("Ask main-lead.", 'a seat address: "main-lead"'),
            ("Co-authored-by: someone", 'an attribution line: "Co-authored-by"'),
            ("Token ghp_" + "a" * 36, 'a secret: "ghp_' + "a" * 36 + '"'),
            ("It lives in /var/home/someone/notes.", 'a private path: "/home/"'),
            ("The hub is hub.tail4cf2f3.ts.net.", 'a hostname: ".ts.net"'),
            ("Reach it at 100.101.102.103.", 'a private address: "100.101.102.103"'),
            (
                "See WORKFLOW-UPKEEP-RULES@TOOLING.",
                'a seat address: "WORKFLOW-UPKEEP-RULES@TOOLING"',
            ),
            ("Ask Main-Lead.", 'a seat address: "Main-Lead"'),
            ("co-authored-by: someone", 'an attribution line: "co-authored-by"'),
            ("The hub is HUB.TAIL4CF2F3.TS.NET.", 'a hostname: ".TS.NET"'),
            (
                "Version 999.999.999.999 is invalid. Reach it at 10.0.0.1.",
                'a private address: "10.0.0.1"',
            ),
        ]
        for addition, problem in cases:
            with self.subTest(addition=addition):
                code, output = self.run_upstream(body=BODY + addition)
                self.assertEqual((code, output), (2, f"body has {problem}\n"))
        self.assertEqual(
            self.run_upstream(
                body=BODY
                + "Use Markdown, not mail; set it in ~/.claude.json for Claude Code and Codex, and reach 140.82.112.6."
            )[0],
            0,
        )

    def test_all_problems_are_reported_together(self):
        self.rig_state["approval"]["body"] = "File upstream elsewhere"
        self.save()
        code, output = self.run_upstream(
            title="Mark asked", body=BODY + "Mark asked. Ask main-lead."
        )
        self.assertEqual(code, 2)
        self.assertEqual(len(output.splitlines()), 4, output)
        self.assert_no_writes()

    def test_missing_fields_and_unknown_key(self):
        for key in ("title", "body", "approval", "tracking"):
            with self.subTest(key=key):
                values = {key: ""}
                self.assertIn(
                    f"{key} must be a nonempty string", self.run_upstream(**values)[1]
                )
                self.assertIn(
                    f"{key} must be a nonempty string",
                    self.run_upstream(omit=(key,))[1],
                )
        self.assertEqual(
            self.run_upstream(labels="enhancement"),
            (2, "labels must be a list of label names\n"),
        )
        for labels in ([""], [1]):
            with self.subTest(labels=labels):
                self.assertEqual(
                    self.run_upstream(labels=labels),
                    (2, "labels must be a list of label names\n"),
                )
        self.assertEqual(
            self.run_upstream(milestone=12), (2, "unknown file key milestone\n")
        )

    def test_tracking_scope_is_checked_by_open(self):
        code, output = self.run_upstream(tracking="sh4i-yurei/claude-config")
        self.assertEqual(code, 2)
        self.assertIn("scope must be one of:", output)
        code, output = self.run_upstream(
            tracking="sh4i-yurei/claude-config", tracking_scope="scope:ci"
        )
        self.assertEqual(code, 0, output)
        self.assertIn('"labels": ["type:chore", "scope:ci", "upstream"]', output)

    def test_case_varied_tracking_repository_dry_run_uses_board_mapping(self):
        code, output = self.run_upstream(tracking="SH4I-YUREI/workflow-engine")
        self.assertEqual(code, 0, output)
        self.assertIn(f"Would call: POST repos/{TRACKING}/issues", output)
        self.assert_no_writes()

    def test_case_varied_tracking_repository_files_under_board_mapping(self):
        code, output = self.run_upstream(
            tracking="SH4I-YUREI/workflow-engine", options=[]
        )
        self.assertEqual(code, 0, output)
        posts = [
            call["args"][1]
            for call in self.calls("gh")
            if "--method" in call["args"]
            and call["args"][call["args"].index("--method") + 1] == "POST"
            and call["args"][1].endswith("/issues")
        ]
        self.assertEqual(posts, [f"repos/{REPO}/issues", f"repos/{TRACKING}/issues"])

    def test_dry_run_reports_tracking_form_failure_on_second_read(self):
        self.gh_state["tracking_form_failure_on_second_read"] = True
        self.save()
        code, output = self.run_upstream()
        self.assertEqual(code, 2, output)
        self.assertIn("HTTP 503: form unavailable", output)
        self.assert_no_writes()

    def test_partial_failure_prints_links_and_stops(self):
        self.gh_state["failure"] = {
            "prefix": ["project", "item-add"],
            "message": "board failed",
        }
        self.save()
        code, output = self.run_upstream(options=[])
        self.assertEqual(
            (code, output),
            (
                1,
                f"filed upstream: https://github.com/{REPO}/issues/99\n"
                f"tracking issue failed: https://github.com/{TRACKING}/issues/99: added new issue to board failed: board failed\n",
            ),
        )
        self.assertEqual(
            sum(
                call["args"][1] == f"repos/{REPO}/issues"
                for call in self.calls("gh")
                if call["args"][0] == "api"
            ),
            1,
        )
        self.assertEqual(
            sum(
                call["args"][:2] == ["api", f"repos/{TRACKING}/issues"]
                and "--method" in call["args"]
                for call in self.calls("gh")
            ),
            1,
        )

    def test_tracking_post_failure_keeps_upstream_link(self):
        self.gh_state["tracking_post_failure"] = "tracking POST failed"
        self.save()
        code, output = self.run_upstream(options=[])
        self.assertEqual(
            (code, output),
            (
                1,
                f"filed upstream: https://github.com/{REPO}/issues/99\ntracking issue failed: tracking POST failed\n",
            ),
        )
        posts = [
            call
            for call in self.calls("gh")
            if call["args"][:2] == ["api", f"repos/{REPO}/issues"]
            and "--method" in call["args"]
        ]
        self.assertEqual(len(posts), 1)

    def test_tracking_create_without_link_names_step(self):
        self.gh_state["tracking_missing_link"] = True
        self.save()
        code, output = self.run_upstream(options=[])
        self.assertEqual(
            (code, output),
            (
                1,
                f"filed upstream: https://github.com/{REPO}/issues/99\n"
                "tracking issue failed: created issue response has no link\n",
            ),
        )

    def test_upstream_create_without_link_names_step(self):
        self.gh_state["upstream_missing_link"] = True
        self.save()
        self.assertEqual(
            self.run_upstream(options=[]),
            (1, "upstream issue creation failed: created issue response has no link\n"),
        )
        self.assertEqual(
            [
                call["args"][1]
                for call in self.calls("gh")
                if call["args"][0] == "api" and "--method" in call["args"]
            ],
            [f"repos/{REPO}/issues"],
        )

    def test_tracking_second_form_reports_each_problem_after_upstream_filing(self):
        self.gh_state["tracking_form_changes_on_second_read"] = True
        self.save()
        self.assertEqual(
            self.run_upstream(options=[]),
            (
                1,
                f"filed upstream: https://github.com/{REPO}/issues/99\n"
                "tracking issue failed: unknown body field changes\n"
                "unknown body field context\n",
            ),
        )

    def test_approval_note_failure_keeps_both_links(self):
        self.rig_state["update_failure"] = "queue update failed"
        self.save()
        code, output = self.run_upstream(options=[])
        self.assertEqual(code, 1, output)
        self.assertIn(f"https://github.com/{REPO}/issues/99", output)
        self.assertIn(f"https://github.com/{TRACKING}/issues/99", output)
        self.assertEqual(
            output.splitlines()[-1], "approval note failed: queue update failed"
        )
        self.rig_state["update_on_stdout"] = True
        self.save()
        code, output = self.run_upstream(options=[])
        self.assertEqual(
            (code, output.splitlines()[-1]),
            (1, "approval note failed: queue update failed"),
        )

    def test_other_owner_mapped_and_exception_are_ours(self):
        self.rig_state["approval"]["body"] = (
            "File the upstream request in other-owner/mapped-repo."
        )
        self.save()
        path = self.workflow / "workflow.toml"
        original = path.read_text()
        path.write_text(
            original.replace(
                "[boards]\n", '[boards]\n"other-owner/mapped-repo" = "Tooling"\n'
            )
        )
        self.assertEqual(
            self.run_upstream(repo="other-owner/mapped-repo"),
            (2, "other-owner/mapped-repo is one of ours; use issue.py open\n"),
        )
        path.write_text(
            original.replace(
                'exceptions = ["sh4i-yurei/second-brain"]',
                'exceptions = ["sh4i-yurei/second-brain", "other-owner/mapped-repo"]',
            )
        )
        self.assertEqual(
            self.run_upstream(repo="other-owner/mapped-repo"),
            (2, "other-owner/mapped-repo is one of ours; use issue.py open\n"),
        )

    def test_title_and_body_each_report_matching_rules(self):
        code, output = self.run_upstream(
            title="Mark asked", body=BODY + "Ask main-lead."
        )
        self.assertEqual(code, 2)
        self.assertIn('title has a personal name: "Mark"', output.splitlines())
        self.assertIn('body has a seat address: "main-lead"', output.splitlines())

    def test_invalid_upstream_configuration_is_refused(self):
        path = self.workflow / "workflow.toml"
        original = path.read_text()
        variants = [
            ("[upstream]", "[not_upstream]", "missing or invalid upstream table"),
            ('approver = "main-lead@hq"', 'approver = ""', "invalid upstream approver"),
            (
                'personal_names = ["Mark"]',
                'personal_names = "Mark"',
                "invalid upstream personal_names",
            ),
            ("'gh[pousr]_[A-Za-z0-9]{36,}'", "'['", "invalid upstream secret pattern"),
        ]
        for old, new, problem in variants:
            with self.subTest(problem=problem):
                path.write_text(original.replace(old, new))
                code, output = self.run_upstream()
                self.assertEqual(code, 2)
                self.assertIn(problem, output)
                self.assert_no_writes()

    def test_invalid_rig_json_is_named(self):
        self.rig_state["invalid_whoami"] = True
        self.save()
        code, output = self.run_upstream()
        self.assertEqual(
            (code, output), (2, "rig returned invalid JSON for whoami --json\n")
        )
        self.assert_no_writes()

    def test_search_refuses_malformed_response_and_reads_next_page(self):
        self.gh_state["search_response"] = {"unexpected": []}
        self.save()
        self.assertEqual(
            self.run_upstream(), (2, "GitHub issue search returned no items list\n")
        )
        self.gh_state = {"approval_pages": [[{} for _ in range(100)], []]}
        self.save()
        code, output = self.run_upstream()
        self.assertEqual(code, 0, output)
        searches = [
            call
            for call in self.calls("gh")
            if call["args"][1].startswith("search/issues")
            and "label%3Aupstream" in call["args"][1]
        ]
        self.assertTrue(any("page=2" in call["args"][1] for call in searches))

    def test_unrelated_search_hit_does_not_consume_approval(self):
        self.gh_state["approval_hits"] = [
            {
                "html_url": "https://github.com/example/other/issues/1",
                "body": "Another approval",
            }
        ]
        self.save()
        self.assertEqual(self.run_upstream()[0], 0)

    def test_non_404_label_failure_is_reported(self):
        self.gh_state["label_failure"] = "HTTP 503: labels unavailable"
        self.save()
        self.assertEqual(self.run_upstream(), (2, "HTTP 503: labels unavailable\n"))
        self.assert_no_writes()

    def test_invalid_ipv4_literal_is_not_a_private_address(self):
        code, output = self.run_upstream(
            body=BODY + "Version 999.999.999.999 is invalid."
        )
        self.assertEqual(code, 0, output)

    def test_upstream_post_failure_never_starts_tracking(self):
        self.gh_state["upstream_post_failure"] = "HTTP 503: upstream unavailable"
        self.save()
        code, output = self.run_upstream(options=[])
        self.assertEqual(
            (code, output),
            (1, "upstream issue creation failed: HTTP 503: upstream unavailable\n"),
        )
        self.assertFalse(
            any(
                call["args"][:2] == ["api", f"repos/{TRACKING}/issues"]
                for call in self.calls("gh")
            )
        )

    def test_tracking_validation_failure_after_upstream_prints_link(self):
        self.gh_state["tracking_form_failure_after_post"] = True
        self.save()
        code, output = self.run_upstream(options=[])
        self.assertEqual(code, 1, output)
        self.assertIn(f"filed upstream: https://github.com/{REPO}/issues/99", output)
        self.assertIn("tracking issue failed:", output)
        self.assertIn("HTTP 503: form unavailable", output)

    def test_open_repo_and_exception_refusals_keep_exact_lines(self):
        for repo in ("a/b/c", "x/"):
            with self.subTest(repo=repo):
                code, output = self.run_open(self.open_file(repo=repo))
                self.assertEqual((code, output), (2, "repo must be owner/name\n"))
        code, output = self.run_open(self.open_file(repo="sh4i-yurei/second-brain"))
        self.assertEqual(
            (code, output), (2, "sh4i-yurei/second-brain: workflow exception\n")
        )

    def test_open_form_read_error_and_unknown_kind_are_named(self):
        self.gh_state["form_read_failure"] = True
        self.save()
        code, output = self.run_open(self.open_file())
        self.assertEqual((code, output), (2, "HTTP 503: form read failed\n"))
        self.gh_state = {}
        self.save()
        code, output = self.run_open(
            self.open_file().replace('kind = "feature"', 'kind = "missing"')
        )
        self.assertEqual(
            (code, output),
            (
                2,
                "kind 'missing' matches no issue form; valid kinds: bug, chore, docs, feature\n",
            ),
        )

    def test_open_dry_run_exact_payload_and_status(self):
        content = self.open_file().replace(
            'title = "A feature"', 'title = "A feature é"'
        )
        code, output = self.run_open(content, "--dry-run")
        self.assertEqual(code, 0, output)
        prefix = "Would call: POST repos/sh4i-yurei/claude-config/issues "
        payload = json.loads(
            next(
                line.removeprefix(prefix)
                for line in output.splitlines()
                if line.startswith(prefix)
            )
        )
        self.assertEqual(
            payload,
            {
                "title": "A feature é",
                "body": "### Project, step, and reason\n\n_No response_\n\n### What changes\n\n_No response_\n\n### Done when\n\nIt works\n",
                "labels": ["type:feature", "scope:ci"],
            },
        )
        self.assertIn('"title": "A feature é"', output)
        self.assertIn(
            "Would call: project item-edit Status Backlog on new issue; leave Priority, Size, Estimate and Iteration empty",
            output.splitlines(),
        )
        self.assertEqual(
            output,
            "Rendered body:\n"
            + payload["body"]
            + "\nWould call: POST repos/sh4i-yurei/claude-config/issues "
            + json.dumps(payload, ensure_ascii=False)
            + "\nWould call: project item-add 2 --owner sh4i-yurei --url NEW_ISSUE_URL\n"
            + "Would call: project item-edit Status Backlog on new issue; leave Priority, Size, Estimate and Iteration empty\n",
        )

    def test_open_parent_zero_and_blockers_read_only_valid_issues(self):
        code, output = self.run_open(self.open_file(extra="parent = 0"))
        self.assertEqual(
            (code, output), (2, "parent must be a positive issue number\n")
        )
        self.assertFalse(
            any(
                "/issues/0" in call["args"][1]
                for call in self.calls("gh")
                if call["args"][0] == "api"
            )
        )
        code, output = self.run_open(
            self.open_file(extra="blocked_by = [0, 20]"), "--dry-run"
        )
        self.assertEqual((code, output), (2, "invalid blocked_by issue 0\n"))
        self.assertEqual(
            [
                call["args"][1]
                for call in self.calls("gh")
                if call["args"][:2]
                == ["api", "repos/sh4i-yurei/claude-config/issues/20"]
            ],
            ["repos/sh4i-yurei/claude-config/issues/20"],
        )

    def test_open_valid_parent_is_linked_on_dry_run(self):
        code, output = self.run_open(self.open_file(extra="parent = 20"), "--dry-run")
        self.assertEqual(code, 0, output)
        self.assertIn(
            "Would call: POST repos/sh4i-yurei/claude-config/issues/20/sub_issues with sub_issue_id NEW_ISSUE_ID",
            output.splitlines(),
        )

    def test_open_blocker_one_is_checked_on_dry_run(self):
        self.assertEqual(
            self.run_open(self.open_file(extra="blocked_by = [1]"), "--dry-run"),
            (2, "sh4i-yurei/claude-config issue #1 does not exist\n"),
        )

    def test_open_created_output_includes_link_and_milestone(self):
        code, output = self.run_open(self.open_file(extra="milestone = 1"))
        self.assertEqual(code, 0, output)
        url = "https://github.com/sh4i-yurei/claude-config/issues/99"
        self.assertEqual(
            output,
            f"{url}\ncreated {url} with labels type:feature, scope:ci and milestone 1\n"
            "added new issue to board\nset new issue Status Backlog\n",
        )


class LoadUpstreamConfig(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        shutil.copytree(WORKFLOW, self.directory, dirs_exist_ok=True)
        self.path = self.directory / "workflow.toml"
        self.original = self.path.read_text()

    def load(self):
        with patch.object(package_config, "DIRECTORY", self.directory):
            return package_config.load_upstream()

    def replace(self, old, new):
        self.assertIn(old, self.original)
        self.path.write_text(self.original.replace(old, new, 1))

    def refused(self, message):
        with self.assertRaises(package_config.ConfigError) as caught:
            self.load()
        self.assertEqual(str(caught.exception), message)

    def test_valid_table_is_returned_exactly(self):
        self.assertEqual(self.load(), tomllib.loads(self.original)["upstream"])

    def test_missing_table_is_refused(self):
        start = self.original.index("[upstream]")
        end = self.original.index("[products]")
        self.path.write_text(self.original[:start] + self.original[end:])
        self.refused("workflow.toml: missing or invalid upstream table")

    def test_non_table_value_is_refused(self):
        start = self.original.index("[upstream]")
        end = self.original.index("[products]")
        self.path.write_text(
            'upstream = "x"\n' + self.original[:start] + self.original[end:]
        )
        self.refused("workflow.toml: missing or invalid upstream table")

    def test_missing_and_extra_keys_are_refused(self):
        self.replace('words = ["main-lead"]\n', "")
        self.refused("workflow.toml: missing or invalid upstream table")
        self.path.write_text(self.original)
        self.replace(
            'words = ["main-lead"]\n', 'words = ["main-lead"]\nextra = ["x"]\n'
        )
        self.refused("workflow.toml: missing or invalid upstream table")

    def test_approver_must_be_nonempty_string(self):
        for bad in ('approver = ""', "approver = 7"):
            with self.subTest(bad=bad):
                self.replace('approver = "main-lead@hq"', bad)
                self.refused("workflow.toml: invalid upstream approver")
                self.path.write_text(self.original)

    def test_lists_must_hold_nonempty_strings(self):
        for key, line in (
            ("personal_names", 'personal_names = ["Mark"]'),
            ("words", 'words = ["main-lead"]'),
            ("hostnames", 'hostnames = ["keepbreath.ing", ".ts.net", "vaultserv"]'),
        ):
            for bad in (f'{key} = "x"', f'{key} = ["x", ""]', f"{key} = [1]"):
                with self.subTest(key=key, bad=bad):
                    self.replace(line, bad)
                    self.refused(f"workflow.toml: invalid upstream {key}")
                    self.path.write_text(self.original)

    def test_bad_secret_pattern_is_refused(self):
        self.replace("'AKIA[0-9A-Z]{16}'", "'AKIA[0-9A-Z'")
        with self.assertRaises(package_config.ConfigError) as caught:
            self.load()
        self.assertTrue(
            str(caught.exception).startswith(
                "workflow.toml: invalid upstream secret pattern: "
            )
        )
