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

    def assert_no_writes(self):
        self.assertFalse(any("--method" in call["args"] for call in self.calls("gh")))
        self.assertFalse(
            any(call[:2] == ["queue", "update"] for call in self.calls("rig"))
        )

    def test_dry_run_reads_everything_without_writing(self):
        code, output = self.run_upstream()
        self.assertEqual(code, 0, output)
        self.assertIn(TITLE, output)
        self.assertIn("Upstream: " + TITLE, output)
        self.assert_no_writes()

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
        self.assertIn(APPROVAL, second["body"])
        self.assertIn(f"https://github.com/{REPO}/issues/99", second["body"])
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
                {"body": "File the upstream request"},
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

    def test_repo_and_tracking_boundaries(self):
        for repo in (
            "SH4I-YUREI/some-new-repo",
            "sh4i-yurei/claude-config",
            "sh4i-yurei/some-new-repo",
        ):
            with self.subTest(repo=repo):
                code, output = self.run_upstream(repo=repo)
                self.assertEqual(
                    (code, output), (2, f"{repo} is one of ours; use issue.py open\n")
                )
        self.assertIn("repo must be owner/name", self.run_upstream(repo="mvschwarz")[1])
        self.assertEqual(
            self.run_upstream(tracking=REPO),
            (2, f"tracking {REPO} has no board mapping\n"),
        )
        self.assert_no_writes()

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
        self.assertEqual(
            self.run_upstream(milestone=12), (2, "unknown file key milestone\n")
        )

    def test_tracking_scope_is_checked_by_open(self):
        code, output = self.run_upstream(tracking="sh4i-yurei/claude-config")
        self.assertEqual(code, 2)
        self.assertIn("scope must be one of:", output)
        self.assertNotIn(
            "scope must be one of:",
            self.run_upstream(
                tracking="sh4i-yurei/claude-config", tracking_scope="scope:ci"
            )[1],
        )

    def test_partial_failure_prints_links_and_stops(self):
        self.gh_state["failure"] = {
            "prefix": ["project", "item-add"],
            "message": "board failed",
        }
        self.save()
        code, output = self.run_upstream(options=[])
        self.assertEqual(code, 1, output)
        self.assertIn(f"https://github.com/{REPO}/issues/99", output)
        self.assertIn(f"https://github.com/{TRACKING}/issues/99", output)
        self.assertIn("board failed", output)
        self.assertEqual(
            sum(
                call["args"][1] == f"repos/{REPO}/issues"
                for call in self.calls("gh")
                if call["args"][0] == "api"
            ),
            1,
        )

    def test_tracking_post_failure_keeps_upstream_link(self):
        self.gh_state["tracking_post_failure"] = "tracking POST failed"
        self.save()
        code, output = self.run_upstream(options=[])
        self.assertEqual(code, 1, output)
        self.assertIn(f"filed upstream: https://github.com/{REPO}/issues/99", output)
        self.assertIn("tracking POST failed", output)
        posts = [
            call
            for call in self.calls("gh")
            if call["args"][:2] == ["api", f"repos/{REPO}/issues"]
            and "--method" in call["args"]
        ]
        self.assertEqual(len(posts), 1)

    def test_approval_note_failure_keeps_both_links(self):
        self.rig_state["update_failure"] = "queue update failed"
        self.save()
        code, output = self.run_upstream(options=[])
        self.assertEqual(code, 1, output)
        self.assertIn(f"https://github.com/{REPO}/issues/99", output)
        self.assertIn(f"https://github.com/{TRACKING}/issues/99", output)
        self.assertIn("queue update failed", output)

    def test_other_owner_mapped_and_exception_are_ours(self):
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
