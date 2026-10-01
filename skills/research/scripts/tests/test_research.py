"""Offline checks for shared-log migration and verification."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lookup
import research


class ResearchLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gateway = self.root / "gateway.jsonl"
        self.fetches = self.root / "fetches.jsonl"
        self.lock = self.root / "gateway.lock"

    def write_envelope(
        self,
        path: Path,
        body: str = "{}",
        *,
        subject: str = "fixture",
        kind: str = "test",
    ):
        path.write_text(
            json.dumps(
                {
                    "url": "https://api.example.test/data",
                    "status": 200,
                    "body": body,
                    "sha256": hashlib.sha256(body.encode()).hexdigest(),
                    "lookup": {"kind": kind, "arguments": [subject]},
                }
            )
        )

    def log_archive(self, topic: str, path: Path):
        log = self.root / "70_Research" / "_log" / "test.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "ts": "2026-09-27T14:00:00Z",
                        "via": "research",
                        "host": "local",
                        "url": f"research://{topic}/fixture",
                        "status": "fixture",
                        "run": topic,
                        "archive": str(path.relative_to(self.root)),
                    }
                )
                + "\n"
            )

    def test_imports_both_logs_in_order_once_and_verifies(self):
        self.gateway.write_text(
            json.dumps(
                {
                    "ts": 200.0,
                    "host": "api.example.test",
                    "url": "https://api.example.test/?api_key=SECRET",
                    "code": "200",
                    "dur": 0.2,
                    "attempt": 1,
                }
            )
            + "\n"
        )
        self.fetches.write_text(
            json.dumps(
                {
                    "ts": 100.0,
                    "kind": "fetch",
                    "tool": "WebFetch",
                    "domain": "example.test",
                    "url": "https://docs.example.test/page",
                    "duration_ms": 500,
                    "session": "old-session",
                    "payload_keys": [],
                }
            )
            + "\n"
        )
        arguments = {
            "root": self.root,
            "gateway_path": self.gateway,
            "fetch_path": self.fetches,
            "hostname": "TESTHOST",
            "lock_path": self.lock,
        }
        self.assertEqual(research.import_logs(**arguments), 0)
        self.assertEqual(research.import_logs(**arguments), 0)
        path = next((self.root / "70_Research" / "_log").glob("*.jsonl"))
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([row["via"] for row in rows], ["webfetch", "gw"])
        self.assertEqual([row["ts"] for row in rows], [100.0, 200.0])
        self.assertIn("api_key=REDACTED", rows[1]["url"])
        self.assertIsNone(rows[0]["repo"])
        self.assertIsNone(rows[0]["archive"])
        self.assertEqual(research.verify_all(self.root), 0)

    def test_import_labels_firecrawl_connector(self):
        self.gateway.write_text("")
        self.fetches.write_text(
            json.dumps(
                {
                    "ts": 100.0,
                    "kind": "search",
                    "tool": "mcp__claude_ai_Firecrawl__firecrawl_search",
                    "domain": "",
                    "url": "",
                    "duration_ms": None,
                    "session": "old-session",
                    "payload_keys": [],
                }
            )
            + "\n"
        )
        records = research.legacy_records(self.gateway, self.fetches)
        self.assertEqual(records[0]["via"], "firecrawl-connector")
        self.assertIsNone(records[0]["status"])

    def test_import_refuses_to_rehash_a_broken_existing_chain(self):
        self.gateway.write_text(
            json.dumps(
                {
                    "ts": 200.0,
                    "host": "api.example.test",
                    "url": "https://api.example.test/",
                    "code": "200",
                    "dur": 0.2,
                }
            )
            + "\n"
        )
        self.fetches.write_text("")
        arguments = {
            "root": self.root,
            "gateway_path": self.gateway,
            "fetch_path": self.fetches,
            "hostname": "TESTHOST",
            "lock_path": self.lock,
        }
        self.assertEqual(research.import_logs(**arguments), 0)
        path = next((self.root / "70_Research" / "_log").glob("*.jsonl"))
        broken = path.read_text().replace('"via":"gw"', '"via":"tampered"')
        path.write_text(broken)
        with self.assertRaisesRegex(ValueError, "hash chain mismatch"):
            research.import_logs(**arguments)
        self.assertEqual(path.read_text(), broken)

    def test_verify_holds_gateway_lock_while_reading_log(self):
        log_root = self.root / "70_Research" / "_log"
        log_root.mkdir(parents=True)
        path = log_root / "TESTHOST-2026-09.jsonl"
        path.write_text("one record\n")
        state = {"locked": False}

        @contextmanager
        def checking_lock(lock_path):
            self.assertEqual(lock_path, self.lock)
            state["locked"] = True
            try:
                yield
            finally:
                state["locked"] = False

        def checking_verify(candidate, previous):
            self.assertTrue(state["locked"])
            self.assertEqual(candidate, path)
            self.assertEqual(previous, "")
            return "next-hash"

        with (
            mock.patch.object(research, "gateway_lock", checking_lock),
            mock.patch.object(research, "verify_log", checking_verify),
        ):
            self.assertEqual(research.verify_all(self.root, self.lock), 0)
        self.assertFalse(state["locked"])

    def test_new_topic_template_fails_until_plan_and_claim_are_filled(self):
        path = research.new_topic(
            "test-b11",
            "survey",
            "What should the test establish?",
            root=self.root,
            today="2026-09-26",
        )
        self.assertEqual(
            path,
            self.root / "70_Research" / "test-b11" / "sources" / "test-b11-sources.md",
        )
        self.assertTrue((path.parent / "raw").is_dir())
        text = path.read_text()
        sections = [
            "## Search plan",
            "## Required claims",
            "## Ledger",
            "## Rounds",
            "## Queries run",
            "## Sources",
        ]
        self.assertEqual(
            [text.index(section) for section in sections],
            sorted(text.index(section) for section in sections),
        )
        problems = research.plan_problems("test-b11", root=self.root)
        self.assertIn("unfilled plan field: Effort tier", problems)
        self.assertIn("at least one required claim must be filled", problems)

        empty = text.replace(research.PLACEHOLDER, "")
        empty = empty.replace("- **Limits:** \n", "- **Limits:** not documented\n")
        empty = empty.replace("1. \n", "1. The plan gate rejects empty fields.\n")
        path.write_text(empty)
        empty_problems = research.plan_problems("test-b11", root=self.root)
        self.assertIn("unfilled plan field: Effort tier", empty_problems)
        self.assertIn("unfilled plan field: Ideal source", empty_problems)

        filled = text.replace(research.PLACEHOLDER, "filled")
        path.write_text(filled)
        self.assertEqual(research.plan_problems("test-b11", root=self.root), [])

        nested = filled.replace(
            "- **Sub-questions:** filled",
            "- **Sub-questions:**\n  1. First nested question\n  2) Second nested question",
        )
        path.write_text(nested)
        self.assertEqual(research.plan_problems("test-b11", root=self.root), [])

        nested = filled.replace(
            "- **Sub-questions:** filled",
            "- **Sub-questions:**\n  - First nested question\n  * Second nested question",
        )
        path.write_text(nested)
        self.assertEqual(research.plan_problems("test-b11", root=self.root), [])

    def test_new_topic_refuses_existing_or_unsafe_folder(self):
        research.new_topic(
            "test-b11", "deep", "Question", root=self.root, today="2026-09-26"
        )
        with self.assertRaises(FileExistsError):
            research.new_topic(
                "test-b11", "deep", "Question", root=self.root, today="2026-09-26"
            )
        for topic in ("../escape", "Has Spaces", ""):
            with (
                self.subTest(topic=topic),
                self.assertRaisesRegex(ValueError, "lowercase hyphenated"),
            ):
                research.topic_paths(topic, self.root)

    def test_plan_check_cli_status_changes_after_fields_are_filled(self):
        research.new_topic(
            "test-b11", "survey", "Question", root=self.root, today="2026-09-26"
        )
        with mock.patch.dict(os.environ, {"SECOND_BRAIN": str(self.root)}):
            self.assertEqual(research.main(["plan-check", "test-b11"]), 1)
            path = research.topic_paths("test-b11", self.root)[1]
            path.write_text(path.read_text().replace(research.PLACEHOLDER, "filled"))
            self.assertEqual(research.main(["plan-check", "test-b11"]), 0)

    def test_check_generates_run_table_flags_edit_and_missing_archive(self):
        path = research.new_topic(
            "test-b12", "survey", "Question", root=self.root, today="2026-09-27"
        )
        archive = path.parent / "raw" / "answer.json"
        self.write_envelope(archive)
        text = path.read_text().replace(research.PLACEHOLDER, "filled")
        text = text.replace(
            "|---|---|---|---|\n",
            "|---|---|---|---|\n"
            "| 1 | SUPPORTED | `70_Research/test-b12/sources/raw/answer.json` | proved |\n",
            1,
        )
        path.write_text(text)
        log_root = self.root / "70_Research" / "_log"
        log_root.mkdir(parents=True)
        records = (
            {
                "ts": "2026-09-27T14:00:00Z",
                "via": "gw",
                "host": "api.example.test",
                "url": "https://api.example.test/data?api_key=secret&item=1",
                "status": 200,
                "run": "test-b12",
                "archive": "70_Research/test-b12/sources/raw/answer.json",
            },
            {
                "ts": "2026-09-27T14:01:00Z",
                "via": "gw",
                "host": "ignored.example.test",
                "url": "https://ignored.example.test/",
                "status": 200,
                "run": "another-run",
                "archive": None,
            },
        )
        (log_root / "test.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in records)
        )

        self.assertEqual(research.topic_problems("test-b12", root=self.root), [])
        generated = research.section(path.read_text(), "Queries run")
        self.assertIn(
            "| Date | Via | Host | URL | Status | Archive | Supports |", generated
        )
        self.assertIn("api_key=REDACTED&item=1", generated)
        self.assertIn(
            "| 200 | 70_Research/test-b12/sources/raw/answer.json | 1 |", generated
        )
        self.assertNotIn("ignored.example.test", generated)

        original_envelope = archive.read_text()
        log = log_root / "test.jsonl"
        original_log = log.read_text()
        log.write_text("")
        self.assertTrue(
            any(
                "supported claim 1 cites archive absent from run log" in problem
                for problem in research.topic_problems("test-b12", root=self.root)
            )
        )
        log.write_text(original_log)

        archive.write_text(
            original_envelope.replace('"body": "{}"', '"body": "changed"')
        )
        self.assertTrue(
            any(
                "supported claim 1 cites envelope with invalid body hash" in problem
                for problem in research.topic_problems("test-b12", root=self.root)
            )
        )
        archive.write_text(original_envelope)

        latin_body = "café"
        archive.write_text(
            json.dumps(
                {
                    "url": "https://api.example.test/data",
                    "status": 200,
                    "headers": {"content-type": "text/plain; charset=iso-8859-1"},
                    "body": latin_body,
                    "sha256": hashlib.sha256(
                        latin_body.encode("iso-8859-1")
                    ).hexdigest(),
                    "lookup": {"kind": "test", "arguments": ["fixture"]},
                }
            )
        )
        self.assertFalse(
            any(
                "invalid body hash" in problem
                for problem in research.topic_problems("test-b12", root=self.root)
            )
        )
        archive.write_text(original_envelope)

        path.write_text(
            path.read_text().replace("api.example.test", "edited.example.test")
        )
        self.assertEqual(
            research.topic_problems("test-b12", root=self.root),
            ["generated Queries run row was edited by hand"],
        )
        self.assertIn("api.example.test", path.read_text())
        self.assertNotIn("edited.example.test", path.read_text())

        marker = research.QUERIES_END
        path.write_text(path.read_text().replace(marker, marker + "\n| fake | row |"))
        self.assertEqual(
            research.topic_problems("test-b12", root=self.root),
            ["generated Queries run markers or rows were edited by hand"],
        )
        self.assertNotIn("| fake | row |", path.read_text())

        archive.unlink()
        self.assertEqual(
            research.topic_problems("test-b12", root=self.root),
            [
                (
                    "ledger cites missing archive: "
                    "70_Research/test-b12/sources/raw/answer.json"
                )
            ],
        )

    def test_check_holds_gateway_lock_through_log_snapshot(self):
        research.new_topic(
            "test-b12", "survey", "Question", root=self.root, today="2026-09-27"
        )
        state = {"locked": False}

        @contextmanager
        def held(_path):
            state["locked"] = True
            try:
                yield
            finally:
                state["locked"] = False

        def records(*_args, **_kwargs):
            self.assertTrue(state["locked"])
            return []

        with (
            mock.patch.object(research, "gateway_lock", held),
            mock.patch.object(research, "run_records", side_effect=records),
        ):
            self.assertEqual(research.topic_problems("test-b12", root=self.root), [])
        self.assertFalse(state["locked"])

    def test_write_uses_only_sources_and_sets_calls_and_stop(self):
        path = self.make_runnable_topic(self.root, "test-b16")
        path.write_text(
            path.read_text().replace(
                "|---|---:|---:|---|---:|---|\n",
                "|---|---:|---:|---|---:|---|\n"
                "| 1 | 1 | 1 | 1 | 0.100000 | saturation |\n",
            )
        )
        log_root = self.root / "70_Research" / "_log"
        log_root.mkdir(parents=True)
        (log_root / "test.jsonl").write_text(
            json.dumps(
                {
                    "ts": "2026-09-27T15:00:00Z",
                    "via": "gw",
                    "host": "api.example.test",
                    "url": "https://api.example.test/",
                    "status": 200,
                    "run": "test-b16",
                    "archive": None,
                }
            )
            + "\n"
            + json.dumps(
                {
                    "ts": "2026-09-27T15:01:00Z",
                    "via": "lookup",
                    "host": "cache",
                    "url": "",
                    "status": 200,
                    "run": "test-b16",
                    "archive": None,
                }
            )
            + "\n"
        )
        synthesis = self.root / "70_Research" / "test-b16" / "test-b16.md"

        def writer(prompt, tools, _cost, **kwargs):
            self.assertIn("Rewrite it from the sources", prompt)
            self.assertIn("do not preserve or copy", prompt)
            self.assertEqual(
                tools,
                [
                    f"Read({research.permission_path(path)})",
                    f"Edit({research.permission_path(synthesis)})",
                ],
            )
            self.assertTrue(kwargs["stream"])
            self.assertEqual(kwargs["enabled_tools"], ["Read", "Edit", "Write"])
            synthesis.write_text(
                """---
type: reference
created: 2026-09-27
---

# Result

I found the test result.

## How far this went
- **Calls:** pending
- **Why I stopped:** pending
- **Rungs used:** direct API
- **Single-sourced:** none
- **Disagreement:** none
"""
            )
            return {
                "error": True,
                "subtype": "error_max_budget_usd",
                "cost_usd": 0.1,
                "events": [
                    {
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Read",
                                    "input": {"file_path": str(path)},
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Write",
                                    "input": {"file_path": str(synthesis)},
                                },
                                {
                                    "type": "tool_use",
                                    "name": "Read",
                                    "input": {"file_path": str(synthesis)},
                                },
                            ]
                        }
                    }
                ],
            }

        config = {
            "agent": {
                "command": "claude",
                "disallowed_tools": [],
                "write_tools": ["Read", "Edit", "Write"],
            },
            "presets": {
                "survey": {
                    "calls": 15,
                    "cost_usd": 4,
                    "sources_per_claim": 1,
                    "source_floor": 0,
                }
            },
        }
        with (
            mock.patch.object(research, "run_agent", side_effect=writer) as run,
            mock.patch.object(research, "load_config", return_value=config),
            mock.patch.object(research, "LOCK_PATH", self.lock),
        ):
            research.write_topic(
                "test-b16", call_limit=1, cost_limit=0.25, root=self.root
            )
        self.assertEqual(run.call_args.args[2], 0.25)
        text = synthesis.read_text()
        self.assertIn("- **Calls:** 1 of 1", text)
        self.assertIn("- **Why I stopped:** saturation", text)

    def test_writer_tool_check_rejects_every_other_path_or_tool(self):
        sources = self.root / "sources.md"
        synthesis = self.root / "result.md"
        events = [
            {
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {"file_path": str(self.root / "outside.md")},
                        },
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "true"},
                        },
                    ]
                }
            }
        ]
        violations = research.check_writer_tools(events, sources, synthesis)
        self.assertEqual(len(violations), 3)

        synthesis_read = [
            {
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Read",
                            "input": {"file_path": str(synthesis)},
                        },
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {"file_path": str(synthesis)},
                        },
                    ]
                }
            }
        ]
        self.assertEqual(
            research.check_writer_tools(synthesis_read, sources, synthesis), []
        )

    def test_writer_restores_existing_synthesis_when_rewrite_fails(self):
        path = self.make_runnable_topic(self.root, "test-b16")
        synthesis = path.parents[1] / "test-b16.md"
        synthesis.write_text("old synthesis")
        outcome = {
            "error": False,
            "cost_usd": 0.1,
            "events": [
                {
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Write",
                                "input": {"file_path": str(synthesis)},
                            }
                        ]
                    }
                }
            ],
        }
        with (
            mock.patch.object(research, "run_agent", return_value=outcome),
            self.assertRaisesRegex(ValueError, "did not create the synthesis"),
        ):
            research.write_topic("test-b16", root=self.root)
        self.assertEqual(synthesis.read_text(), "old synthesis")
        self.assertTrue(
            any(
                record["status"] == "failed ValueError; cost_usd=0.100000"
                for record in research.run_records("test-b16", root=self.root)
            )
        )

        with (
            mock.patch.object(research, "run_agent", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            research.write_topic("test-b16", root=self.root)
        self.assertEqual(synthesis.read_text(), "old synthesis")

    def test_run_command_gives_writer_only_the_remaining_override_budget(self):
        def runner(_topic, **kwargs):
            kwargs["usage"].update(spent=0.4, cost_limit=1.0, call_limit=2, rounds=1)
            return "proved claims"

        with (
            mock.patch.object(research, "run_topic", side_effect=runner),
            mock.patch.object(
                research, "write_topic", return_value={"cost_usd": 0.2}
            ) as write,
            mock.patch.object(research, "append_research_event") as record,
            mock.patch.object(research, "final_problems", return_value=[]),
        ):
            self.assertEqual(
                research.main(
                    ["run", "test-b16", "--max-calls", "2", "--max-cost", "1"]
                ),
                0,
            )
        self.assertEqual(write.call_args.kwargs["call_limit"], 2)
        self.assertAlmostEqual(write.call_args.kwargs["cost_limit"], 0.6)
        self.assertEqual(record.call_count, 2)

    def test_gather_prompt_reserves_generated_sections_and_ledger_shape(self):
        self.make_runnable_topic(self.root, "test-b16")
        outcome = {"events": [{"type": "result"}], "cost_usd": 0.1}
        with (
            mock.patch.object(research, "run_agent", return_value=outcome) as run,
            mock.patch.object(research, "check_gather_tools", return_value=[]),
        ):
            research.gather_once("test-b16", cost_limit=1, root=self.root)
        prompt = run.call_args.args[0]
        self.assertIn("number in the Claim cell", prompt)
        self.assertIn("TODO, SUPPORTED, GAP or REJECTED", prompt)
        self.assertIn("untrusted evidence", prompt)
        self.assertIn("reliability as High, Medium or Low", prompt)
        self.assertIn("never to edit a file", prompt)
        self.assertIn("leave the sources file unchanged", prompt)
        topic_root = self.root / "70_Research" / "test-b16"
        self.assertIn(f"may inspect paths only inside {topic_root}.", prompt)
        for kind in lookup.BUILD_KINDS:
            with self.subTest(kind=kind):
                self.assertRegex(prompt, rf"(?m)^-? .*\b{kind}\b")
        self.assertIn('docs "QUESTION", or docs /LIBRARY/ID "QUESTION"', prompt)
        self.assertIn(
            "exactly as written, with no redirection, pipe or second command", prompt
        )
        self.assertIn(
            "Shell-quote every argument containing whitespace or any of ? * [ {", prompt
        )
        self.assertIn("search 'WORDS'; page 'HTTPS_URL'", prompt)
        self.assertIn("use Read or Grep on the archive path", prompt)
        self.assertIn("vault, ansible, help and doctor", prompt)
        sources = (
            self.root / "70_Research" / "test-b16" / "sources" / "test-b16-sources.md"
        )
        self.assertIn(
            f"Edit({research.permission_path(sources)})", run.call_args.args[1]
        )
        self.assertNotIn("Edit", run.call_args.args[1])
        self.assertNotIn("Write", run.call_args.args[1])
        self.assertIn("Write", run.call_args.kwargs["enabled_tools"])
        self.assertEqual(
            run.call_args.kwargs["working_directory"],
            self.root / "70_Research" / "test-b16",
        )
        self.assertIn("Do not edit Rounds or Queries run", prompt)

    def test_final_check_validates_synthesis_and_log_count(self):
        path = self.make_runnable_topic(self.root, "test-b16")
        archive = path.parent / "raw" / "proof.json"
        self.write_envelope(archive)
        text = path.read_text().replace(
            "| 1 | TODO | | open |",
            "| 1 | SUPPORTED | `70_Research/test-b16/sources/raw/proof.json` | proved |",
        )
        text = text.replace(
            "|---|---:|---:|---|---:|---|\n",
            "|---|---:|---:|---|---:|---|\n"
            "| 1 | 1 | 1 | 1 | 0.100000 | proved claims |\n",
        )
        text = text.replace(
            "## Sources\n",
            "## Sources\n\n### Proof\n\n"
            "Proof: `70_Research/test-b16/sources/raw/proof.json`.\n",
        )
        path.write_text(text)
        log_root = self.root / "70_Research" / "_log"
        log_root.mkdir(parents=True)
        (log_root / "test.jsonl").write_text(
            json.dumps(
                {
                    "ts": "2026-09-27T15:00:00Z",
                    "via": "gw",
                    "host": "api.example.test",
                    "url": "https://api.example.test/",
                    "status": 200,
                    "run": "test-b16",
                    "archive": "70_Research/test-b16/sources/raw/proof.json",
                }
            )
            + "\n"
        )
        synthesis = self.root / "70_Research" / "test-b16" / "test-b16.md"
        synthesis.write_text(
            """---
type: reference
created: 2026-09-27
---

# Result

I found the test result.

## How far this went
- **Calls:** 1 of 15
- **Why I stopped:** proved claims
- **Rungs used:** direct API
- **Single-sourced:** claim 1
- **Disagreement:** none
"""
        )
        config = {"presets": {"survey": {"sources_per_claim": 1, "source_floor": 1}}}
        with mock.patch.object(research, "load_config", return_value=config):
            self.assertEqual(
                research.final_problems(
                    "test-b16", root=self.root, run_vault_check=False
                ),
                [],
            )
            synthesis.write_text(
                synthesis.read_text().replace("Calls:** 1", "Calls:** 2")
            )
            self.assertIn(
                "Calls does not match the log (1)",
                research.final_problems(
                    "test-b16", root=self.root, run_vault_check=False
                ),
            )
            synthesis.write_text(
                synthesis.read_text()
                .replace("Calls:** 2", "Calls:** 1")
                .replace(
                    "Rungs used:** direct API",
                    "Rungs used:** fill from the sources file",
                )
            )
            self.assertIn(
                "How far this went retains template value for Rungs used",
                research.final_problems(
                    "test-b16", root=self.root, run_vault_check=False
                ),
            )

    def test_scriptable_checks_reject_bad_round_and_require_explicit_gap(self):
        path = self.make_runnable_topic(self.root, "test-b16")
        invalid = path.read_text().replace(
            "| 1 | TODO | | open |",
            "| 1 | SUPPORTED | | unsupported ledger row |",
        )
        config = {
            "presets": {
                "survey": {
                    "rounds": 1,
                    "calls": 1,
                    "cost_usd": 1,
                    "source_floor": 1,
                    "sources_per_claim": 1,
                }
            }
        }

        def gather(*_args, **_kwargs):
            path.write_text(invalid)
            return {"error": False, "cost_usd": 0.1}

        with (
            mock.patch.object(research, "gather_once", side_effect=gather),
            mock.patch.object(
                research,
                "isolated_check",
                return_value={
                    "cost_usd": 0.0,
                    "rejected": {},
                    "budget_exit": False,
                },
            ),
            mock.patch.object(research, "load_config", return_value=config),
            self.assertRaisesRegex(
                ValueError, "supported claim 1 cites too few sources"
            ),
        ):
            research.run_topic("test-b16", root=self.root)
        self.assertTrue(
            any(
                record["status"] == "failed post-round check; cost_usd=0.100000"
                for record in research.run_records("test-b16", root=self.root)
            )
        )

        gap_text = invalid.replace("SUPPORTED", "GAP")
        synthesis = """## How far this went
- **Single-sourced:** none; fixture version 1
"""
        problems = research.scriptable_problems(
            gap_text,
            synthesis,
            config["presets"]["survey"],
            require_source_floor=False,
        )
        self.assertIn("GAP claim 1 is not disclosed in the synthesis", problems)

    def test_stream_adapter_uses_observed_format_and_gather_boundaries(self):
        fixture = (
            Path(__file__).parent / "fixtures" / "claude-gather-stream.jsonl"
        ).read_text()
        events = research.stream_events(fixture)
        topic = Path("/tmp/test-root/70_Research/test-b13")
        lookup_script = Path("/opt/research/lookup.py")
        self.assertEqual(
            research.check_gather_tools(events, topic, lookup_script=lookup_script),
            [],
        )
        self.assertEqual(events[-1]["total_cost_usd"], 0.2624124)

    def test_gather_tool_check_stops_an_outside_edit(self):
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": str(self.root / "other.md")},
                        }
                    ]
                },
            },
            {"type": "result"},
        ]
        violations = research.check_gather_tools(
            events, self.root / "70_Research" / "test-b13"
        )
        self.assertIn("Edit outside sources file", violations[0])

        events[0]["message"]["content"][0] = {
            "type": "tool_use",
            "name": "Read",
            "input": {"file_path": str(self.root / "secret.txt")},
        }
        violations = research.check_gather_tools(
            events, self.root / "70_Research" / "test-b13"
        )
        self.assertIn("Read outside topic folder", violations[0])

        events[0]["message"]["content"][0] = {
            "type": "tool_use",
            "name": "Read",
            "input": {"file_path": "/tmp/a\0b"},
        }
        violations = research.check_gather_tools(
            events, self.root / "70_Research" / "test-b13"
        )
        self.assertIn("Read outside topic folder", violations[0])

        topic = self.root / "70_Research" / "test-b13"
        for tool_input in (
            {"pattern": str(self.root / "secret" / "*")},
            {"pattern": "../../secret/*"},
            {"pattern": "**/../*"},
            {"pattern": "{..,x}/*"},
            {"pattern": r"\.\./\.\./secret/*"},
            {"pattern": "~definitely-no-such-research-user/*"},
            {"pattern": "a\0b/*"},
            {"path": "~definitely-no-such-research-user", "pattern": "*"},
            {"path": str(topic), "pattern": "../../../secret/*"},
        ):
            with self.subTest(glob=tool_input):
                events[0]["message"]["content"][0] = {
                    "type": "tool_use",
                    "name": "Glob",
                    "input": tool_input,
                }
                violations = research.check_gather_tools(events, topic)
                self.assertIn("Glob outside topic folder", violations[0])

        events[0]["message"]["content"][0] = {
            "type": "tool_use",
            "name": "Glob",
            "input": {"pattern": "sources/**/*.md"},
        }
        self.assertEqual(research.check_gather_tools(events, topic), [])

        events[0]["message"]["content"][0] = {
            "type": "tool_use",
            "name": "Glob",
            "input": {"path": "sources", "pattern": "*.md"},
        }
        self.assertEqual(research.check_gather_tools(events, topic), [])

        events[0]["message"]["content"][0] = {
            "type": "tool_use",
            "name": "Write",
            "input": {
                "file_path": str(
                    self.root
                    / "70_Research"
                    / "test-b13"
                    / "sources"
                    / "raw"
                    / "fake.json"
                )
            },
        }
        violations = research.check_gather_tools(
            events, self.root / "70_Research" / "test-b13"
        )
        self.assertIn("Write outside sources file", violations[0])

        for name in ("Edit", "Write"):
            with self.subTest(name=name, unknown_user=True):
                events[0]["message"]["content"][0] = {
                    "type": "tool_use",
                    "name": name,
                    "input": {"file_path": "~definitely-no-such-research-user/file.md"},
                }
                violations = research.check_gather_tools(events, topic)
                self.assertIn(f"{name} outside sources file", violations[0])

        events[0]["message"]["content"][0] = {
            "type": "tool_use",
            "name": "Write",
            "input": {"file_path": "/tmp/a\0b"},
        }
        violations = research.check_gather_tools(events, topic)
        self.assertIn("Write outside sources file", violations[0])

    def test_unrelated_vault_change_does_not_affect_stream_check(self):
        topic = self.root / "70_Research" / "test-b13"
        topic.mkdir(parents=True)
        sources = topic / "sources" / "test-b13-sources.md"
        unrelated = self.root / "unrelated.md"
        unrelated.write_text("changed elsewhere")
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {"file_path": str(sources)},
                        }
                    ]
                },
            },
            {"type": "result"},
        ]
        self.assertEqual(research.check_gather_tools(events, topic), [])
        self.assertEqual(unrelated.read_text(), "changed elsewhere")

    def test_gather_tool_check_accepts_only_plain_lookup_shell_command(self):
        script = self.root / "lookup.py"
        good = f"python3 {script} eol almalinux 10"
        self.assertTrue(research.lookup_command(good, script))
        for command in (
            f"python3 {script} eol almalinux 10 && touch /tmp/bad",
            f"python3 {script} eol almalinux 10 & touch /tmp/bad",
            f"python3 {script} eol almalinux 10 | tee /tmp/bad",
            f"python3 {script} eol almalinux 10 > /dev/null",
            f"python3 {script} eol almalinux 10; echo done",
            f"python3 {script} --text eol almalinux 10",
            f"python3 {script} --t eol almalinux 10",
            f"python3 {script} --te eol almalinux 10",
            f"python3 {script} --tex eol almalinux 10",
            f"python3 {script} search foo {{--text,}}",
            f"python3 {script} search foo *",
            f"python3 {script} search foo ?-text",
            f"python3 {script} search foo [a-z]",
            f"python3 {script} page https://example.com/?a=1",
            "python3 other.py eol almalinux 10",
            f"python3 {script} search $BW_SESSION",
            f"python3 {script} vault private-note",
            f"python3 {script} --text vault private-note",
        ):
            with self.subTest(command=command):
                self.assertFalse(research.lookup_command(command, script))
        for flag in ("--t", "--te", "--tex"):
            with self.subTest(flag=flag), self.assertRaises(lookup.BadArguments):
                lookup.parser().parse_args([flag, "eol", "almalinux", "10"])
        direct_text = lookup.parser().parse_args(["--text", "eol", "almalinux", "10"])
        self.assertTrue(direct_text.text)
        self.assertTrue(
            research.lookup_command(
                f"python3 {script} page 'https://example.com/?a=1&b=2'", script
            )
        )
        self.assertTrue(
            research.lookup_command(
                f"python3 {script} search 'what is {{safe}}?'", script
            )
        )

    def test_run_agent_builds_stream_command_and_sets_research_run(self):
        fixture = (
            Path(__file__).parent / "fixtures" / "claude-gather-stream.jsonl"
        ).read_text()
        completed = subprocess.CompletedProcess([], 0, stdout=fixture, stderr="")
        config = {
            "agent": {
                "command": "claude",
                "disallowed_tools": ["WebFetch", "WebSearch", "Task"],
            }
        }
        with (
            mock.patch.object(research, "load_config", return_value=config),
            mock.patch.object(
                research.subprocess, "run", return_value=completed
            ) as run,
            mock.patch.dict(
                os.environ,
                {"BW_SESSION": "do-not-pass", "BW_CLIENTSECRET": "also-secret"},
            ),
        ):
            outcome = research.run_agent(
                "prompt",
                ["Read", "Edit"],
                1.5,
                stream=True,
                root=self.root,
                run="test-b13",
            )
        command = run.call_args.args[0]
        self.assertIn("--safe-mode", command)
        self.assertIn("--restricted", command)
        self.assertIn("stream-json", command)
        self.assertIn("--verbose", command)
        self.assertEqual(command[command.index("--tools") + 1], "Read,Edit")
        self.assertIn("--strict-mcp-config", command)
        self.assertEqual(
            command[command.index("--mcp-config") + 1], '{"mcpServers":{}}'
        )
        self.assertIn("--disable-slash-commands", command)
        self.assertIn(
            '"disableAllHooks":true', command[command.index("--settings") + 1]
        )
        self.assertEqual(run.call_args.kwargs["cwd"], self.root)
        self.assertEqual(run.call_args.kwargs["env"]["RESEARCH_RUN"], "test-b13")
        self.assertNotIn("BW_SESSION", run.call_args.kwargs["env"])
        self.assertNotIn("BW_CLIENTSECRET", run.call_args.kwargs["env"])
        self.assertEqual(outcome["subtype"], "success")

    def make_runnable_topic(self, root, topic="test-b14"):
        path = research.new_topic(
            topic, "survey", "Question", root=root, today="2026-09-27"
        )
        text = path.read_text().replace(research.PLACEHOLDER, "filled")
        text = text.replace(
            "|---|---|---|---|\n",
            "|---|---|---|---|\n| 1 | TODO | | open |\n",
            1,
        )
        path.write_text(text)
        return path

    def test_round_loop_stops_on_proved_claims(self):
        path = self.make_runnable_topic(self.root)
        archive = (
            self.root / "70_Research" / "test-b14" / "sources" / "raw" / "proof.json"
        )

        def gather(*_args, **_kwargs):
            self.write_envelope(archive)
            self.log_archive("test-b14", archive)
            text = path.read_text().replace(
                "| 1 | TODO | | open |",
                "| 1 | SUPPORTED | `70_Research/test-b14/sources/raw/proof.json` | proved |",
            )
            text = text.replace(
                "## Sources\n",
                "## Sources\n\nProof: `70_Research/test-b14/sources/raw/proof.json`.\n",
            )
            path.write_text(text)
            return {"error": False, "cost_usd": 0.2}

        config = {
            "presets": {
                "survey": {"rounds": 3, "calls": 5, "cost_usd": 2, "source_floor": 1}
            }
        }
        with (
            mock.patch.object(research, "gather_once", side_effect=gather),
            mock.patch.object(
                research,
                "isolated_check",
                return_value={"cost_usd": 0.0, "rejected": {}},
            ) as check,
            mock.patch.object(research, "load_config", return_value=config),
        ):
            self.assertEqual(
                research.run_topic("test-b14", root=self.root), "proved claims"
            )
        check.assert_called_once_with("test-b14", {1}, cost_limit=1.8, root=self.root)
        self.assertIn("| 1 | 0 | 1 | 1 | 0.200000 | proved claims |", path.read_text())

    def test_round_loop_rechecks_existing_supported_claim(self):
        path = self.make_runnable_topic(self.root)
        archive = path.parent / "raw" / "proof.json"
        self.write_envelope(archive)
        self.log_archive("test-b14", archive)
        text = path.read_text().replace(
            "| 1 | TODO | | open |",
            "| 1 | SUPPORTED | `70_Research/test-b14/sources/raw/proof.json` | asserted |",
        )
        text = text.replace(
            "## Sources\n",
            "## Sources\n\nProof: `70_Research/test-b14/sources/raw/proof.json`.\n",
        )
        path.write_text(text)
        config = {
            "presets": {
                "survey": {"rounds": 1, "calls": 5, "cost_usd": 2, "source_floor": 1}
            }
        }
        with (
            mock.patch.object(
                research, "gather_once", return_value={"error": False, "cost_usd": 0.1}
            ),
            mock.patch.object(
                research,
                "isolated_check",
                return_value={"cost_usd": 0.1, "rejected": {}, "budget_exit": False},
            ) as check,
            mock.patch.object(research, "load_config", return_value=config),
        ):
            self.assertEqual(
                research.run_topic("test-b14", root=self.root), "proved claims"
            )
        check.assert_called_once_with("test-b14", {1}, cost_limit=1.9, root=self.root)

    def test_round_loop_restores_protected_plan_fields(self):
        path = self.make_runnable_topic(self.root)
        before = path.read_text()

        def changes_mode(*_args, **_kwargs):
            path.write_text(before.replace("| Round | Calls |", "| Edited | Calls |"))
            return {"error": False, "cost_usd": 0.1}

        config = {
            "presets": {
                "survey": {"rounds": 1, "calls": 5, "cost_usd": 2, "source_floor": 1}
            }
        }
        with (
            mock.patch.object(research, "gather_once", side_effect=changes_mode),
            mock.patch.object(research, "load_config", return_value=config),
            self.assertRaisesRegex(ValueError, "changed protected"),
        ):
            research.run_topic("test-b14", root=self.root)
        self.assertEqual(path.read_text(), before)
        self.assertTrue(
            any(
                record["status"] == "failed protected controls; cost_usd=0.100000"
                for record in research.run_records("test-b14", root=self.root)
            )
        )

        def interrupted(*_args, **_kwargs):
            path.write_text(before.replace("**Question:**", "**Question:** changed"))
            raise KeyboardInterrupt

        with (
            mock.patch.object(research, "gather_once", side_effect=interrupted),
            mock.patch.object(research, "load_config", return_value=config),
            self.assertRaises(KeyboardInterrupt),
        ):
            research.run_topic("test-b14", root=self.root)
        self.assertEqual(path.read_text(), before)

    def test_recorded_outside_grep_gets_terminal_round_row(self):
        path = self.make_runnable_topic(self.root, "test-b20")
        before = path.read_text()
        fixture = (
            Path(__file__).parent / "fixtures" / "claude-gather-outside-grep.jsonl"
        ).read_text()
        events = research.stream_events(fixture)
        log = self.root / "70_Research" / "_log" / "test.jsonl"
        archive = path.parent / "raw" / "one.json"
        outcome = {
            "events": events,
            "cost_usd": events[-1]["total_cost_usd"],
            "error": False,
            "subtype": "success",
        }

        def agent(*_args, **_kwargs):
            path.write_text(
                path.read_text().replace(
                    "| 1 | TODO | | open |", "| 1 | GAP | | should be restored |"
                )
            )
            log.parent.mkdir(parents=True)
            log.write_text(
                json.dumps(
                    {
                        "ts": "2026-09-28T01:44:00Z",
                        "via": "gw",
                        "host": "api.example.test",
                        "url": "https://api.example.test/",
                        "status": 200,
                        "run": "test-b20",
                        "archive": "70_Research/test-b20/sources/raw/one.json",
                    }
                )
                + "\n"
            )
            self.write_envelope(archive)
            return outcome

        config = {
            "agent": {
                "gather_tools": ["Read", "Grep", "Glob", "Edit", "Write", "lookup.py"]
            },
            "presets": {
                "survey": {
                    "rounds": 3,
                    "calls": 15,
                    "cost_usd": 4,
                    "source_floor": 1,
                }
            },
        }
        with (
            mock.patch.object(research, "run_agent", side_effect=agent),
            mock.patch.object(research, "load_config", return_value=config),
            mock.patch.object(research, "append_research_event"),
            self.assertRaisesRegex(
                research.GatherToolViolation, "Grep outside topic folder"
            ),
        ):
            research.run_topic("test-b20", root=self.root)
        rounds = research.section(path.read_text(), "Rounds")
        self.assertIn("| 1 | 1 | 1 | 0 | 0.487615 | tool violation: ", rounds)
        self.assertIn("Grep outside topic folder:", rounds)
        self.assertIn("skills/research/scripts/lookup.py", rounds)
        self.assertEqual(rounds.count("\n| 1 |"), 1)
        row = next(line for line in rounds.splitlines() if line.startswith("| 1 |"))
        self.assertEqual(path.read_text().replace(row + "\n", "", 1), before)
        self.assertEqual(
            research.round_stop(path.read_text()), row.strip("|").split("|")[-1].strip()
        )

    def test_round_violation_cell_is_safe_and_unknown_cost_is_explicit(self):
        path = self.make_runnable_topic(self.root, "test-b20-cell")
        research.append_round(
            path,
            round_number=1,
            calls=0,
            new_archives=0,
            claims_moved=0,
            cost=None,
            stop="tool violation: grep -E 'x\\d' thing | head\n## injected",
        )
        row = next(
            line
            for line in research.section(path.read_text(), "Rounds").splitlines()
            if line.startswith("| 1 |")
        )
        self.assertEqual(len(row.strip("|").split("|")), 6)
        self.assertIn("| unreported |", row)
        self.assertIn("&#124;", row)
        reason = research.round_stop(path.read_text())
        self.assertIn("## injected", reason)
        synthesis = "## How far this went\n- **Why I stopped:** old\n"
        updated = research.replace_how_far_field(synthesis, "Why I stopped", reason)
        self.assertIn("grep -E 'x\\d'", updated)

        long_path = self.make_runnable_topic(self.root, "test-b20-long-cell")
        research.append_round(
            long_path,
            round_number=1,
            calls=0,
            new_archives=0,
            claims_moved=0,
            cost=0.0,
            stop="x" * 239 + "|tail",
        )
        long_reason = research.round_stop(long_path.read_text())
        self.assertEqual(long_reason, "x" * 239 + "&#124;")
        self.assertNotIn("tail", long_reason)

    def test_recorded_redirected_lookup_gets_terminal_round_row(self):
        path = self.make_runnable_topic(self.root, "test-b21")
        before = path.read_text()
        fixture = (
            Path(__file__).parent / "fixtures" / "claude-gather-redirected-lookup.jsonl"
        ).read_text()
        events = research.stream_events(fixture)
        recorded_script = (
            "/var/home/sh4i_yurei/Documents/claude-config/"
            "skills/research/scripts/lookup.py"
        )
        actual_script = str(Path(research.__file__).with_name("lookup.py").resolve())
        events[0]["message"]["content"][0]["input"]["command"] = events[0]["message"][
            "content"
        ][0]["input"]["command"].replace(recorded_script, actual_script)
        log = self.root / "70_Research" / "_log" / "test.jsonl"
        archive = path.parent / "raw" / "page-forum.json"
        outcome = {
            "events": events,
            "cost_usd": events[-1]["total_cost_usd"],
            "error": False,
            "subtype": "success",
        }

        def agent(*_args, **_kwargs):
            path.write_text(
                path.read_text().replace(
                    "| 1 | TODO | | open |", "| 1 | SUPPORTED | | discarded |"
                )
            )
            log.parent.mkdir(parents=True)
            log.write_text(
                json.dumps(
                    {
                        "ts": "2026-09-28T06:18:00Z",
                        "via": "gw",
                        "host": "api.firecrawl.dev",
                        "url": "https://api.firecrawl.dev/v2/scrape",
                        "status": 200,
                        "run": "test-b21",
                        "archive": "70_Research/test-b21/sources/raw/page-forum.json",
                    }
                )
                + "\n"
            )
            self.write_envelope(archive)
            return outcome

        config = {
            "agent": {
                "gather_tools": ["Read", "Grep", "Glob", "Edit", "Write", "lookup.py"]
            },
            "presets": {
                "survey": {
                    "rounds": 3,
                    "calls": 15,
                    "cost_usd": 4,
                    "source_floor": 1,
                }
            },
        }
        with (
            mock.patch.object(research, "run_agent", side_effect=agent),
            mock.patch.object(research, "load_config", return_value=config),
            mock.patch.object(research, "append_research_event"),
            self.assertRaisesRegex(
                research.GatherToolViolation, "Bash is not the lookup command"
            ),
        ):
            research.run_topic("test-b21", root=self.root)
        rounds = research.section(path.read_text(), "Rounds")
        self.assertIn("| 1 | 1 | 1 | 0 | 0.675017 | tool violation: ", rounds)
        self.assertIn("Bash is not the lookup command:", rounds)
        row = next(line for line in rounds.splitlines() if line.startswith("| 1 |"))
        self.assertEqual(path.read_text().replace(row + "\n", "", 1), before)
        self.assertIn("> /dev/null; echo done", row)

    def test_malformed_claim_cell_cannot_count_as_supported(self):
        text = """## Required claims
1. Claim
## Ledger
| Claim | Status | Sources | Note |
|---|---|---|---|
| 1. altered | SUPPORTED | `70_Research/test/raw/a.json` | no |
## Sources
Evidence: `70_Research/test/raw/a.json`.
"""
        self.assertEqual(research.claim_statuses(text), {})
        self.assertFalse(research.proved(text, 1))
        unicode_digit = text.replace("1. altered", "²")
        self.assertEqual(research.claim_statuses(unicode_digit), {})
        self.assertEqual(
            research.scriptable_problems(
                unicode_digit,
                None,
                {"sources_per_claim": 1, "source_floor": 0},
            ),
            ["claim 1 has no valid ledger status"],
        )

    def test_round_loop_stops_on_saturation_and_each_limit(self):
        cases = (
            ("saturation", {}, 0.2, None),
            ("round limit", {"max_rounds": 1}, 0.2, "GAP"),
            ("call limit", {"max_calls": 1}, 0.2, "GAP"),
            ("cost limit", {"max_cost": 0.1}, 0.2, "GAP"),
        )
        for index, (expected, limits, cost, status) in enumerate(cases):
            with self.subTest(expected=expected):
                root = self.root / str(index)
                path = self.make_runnable_topic(root)

                def gather(
                    *_args,
                    current_status=status,
                    current_path=path,
                    current_expected=expected,
                    current_root=root,
                    current_cost=cost,
                    **_kwargs,
                ):
                    if current_status:
                        current_path.write_text(
                            current_path.read_text().replace(
                                "| 1 | TODO | | open |",
                                f"| 1 | {current_status} | | moved |",
                            )
                        )
                    if current_expected == "call limit":
                        log = current_root / "70_Research" / "_log" / "test.jsonl"
                        log.parent.mkdir(parents=True)
                        log.write_text(
                            json.dumps(
                                {
                                    "ts": "2026-09-27T15:00:00Z",
                                    "run": "test-b14",
                                    "via": "gw",
                                    "host": "example.test",
                                    "url": "https://example.test/",
                                    "status": 200,
                                    "duration_s": 0.1,
                                    "attempt": 1,
                                    "repo": None,
                                    "archive": None,
                                }
                            )
                            + "\n"
                        )
                    return {"error": False, "cost_usd": current_cost}

                config = {
                    "presets": {
                        "survey": {
                            "rounds": 3,
                            "calls": 5,
                            "cost_usd": 2,
                            "source_floor": 1,
                        }
                    }
                }
                with (
                    mock.patch.object(research, "gather_once", side_effect=gather),
                    mock.patch.object(research, "load_config", return_value=config),
                ):
                    self.assertEqual(
                        research.run_topic("test-b14", root=root, **limits), expected
                    )
                self.assertIn(f"| {expected} |", path.read_text())

    def test_round_loop_records_budget_exit_and_rejects_missing_cost(self):
        path = self.make_runnable_topic(self.root)
        config = {
            "presets": {
                "survey": {
                    "rounds": 3,
                    "calls": 5,
                    "cost_usd": 0.1,
                    "source_floor": 1,
                }
            }
        }
        budget = {
            "error": True,
            "subtype": "error_max_budget_usd",
            "cost_usd": 0.2,
        }

        def exhausted_gather(*_args, **_kwargs):
            (path.parent / "raw" / "proof.json").write_text("{}")
            path.write_text(
                path.read_text().replace(
                    "| 1 | TODO | | open |",
                    "| 1 | SUPPORTED | `70_Research/test-b14/sources/raw/proof.json` | asserted |",
                )
            )
            return budget

        with (
            mock.patch.object(research, "gather_once", side_effect=exhausted_gather),
            mock.patch.object(research, "load_config", return_value=config),
        ):
            self.assertEqual(
                research.run_topic("test-b14", root=self.root), "cost limit"
            )
        self.assertIn("| 1 | 0 | 1 | 0 | 0.200000 | cost limit |", path.read_text())
        self.assertIn("| 1 | TODO |", path.read_text())
        self.assertIn("gather exhausted the cost limit", path.read_text())

        other_root = self.root / "missing"
        self.make_runnable_topic(other_root)
        with (
            mock.patch.object(
                research,
                "gather_once",
                return_value={"error": False, "cost_usd": None},
            ),
            mock.patch.object(research, "load_config", return_value=config),
            self.assertRaisesRegex(TypeError, "did not report its cost"),
        ):
            research.run_topic("test-b14", root=other_root)

    def test_round_loop_passes_remaining_budgets_and_records_round_deltas(self):
        path = self.make_runnable_topic(self.root)
        log = self.root / "70_Research" / "_log" / "test.jsonl"
        calls = 0

        def gather(*_args, **kwargs):
            nonlocal calls
            self.assertEqual(kwargs["calls_left"], 3 - calls)
            self.assertAlmostEqual(kwargs["cost_limit"], 1.0 - calls * 0.2)
            calls += 1
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "ts": f"2026-09-27T15:0{calls}:00Z",
                            "run": "test-b14",
                            "via": "gw",
                            "host": "example.test",
                            "url": "https://example.test/",
                            "status": 200,
                            "duration_s": 0.1,
                            "attempt": 1,
                            "repo": None,
                            "archive": None,
                        }
                    )
                    + "\n"
                )
            old = f"| 1 | {'TODO' if calls == 1 else 'GAP'} | |"
            new = f"| 1 | {'GAP' if calls == 1 else 'REJECTED'} | |"
            path.write_text(path.read_text().replace(old, new))
            return {"error": False, "cost_usd": 0.2}

        config = {
            "presets": {
                "survey": {
                    "rounds": 2,
                    "calls": 3,
                    "cost_usd": 1.0,
                    "source_floor": 1,
                }
            }
        }
        with (
            mock.patch.object(research, "gather_once", side_effect=gather),
            mock.patch.object(research, "load_config", return_value=config),
        ):
            self.assertEqual(
                research.run_topic("test-b14", root=self.root), "round limit"
            )
        rounds = research.section(path.read_text(), "Rounds")
        self.assertIn("| 1 | 1 | 0 | 1 | 0.200000 | continue |", rounds)
        self.assertIn("| 2 | 1 | 0 | 1 | 0.200000 | round limit |", rounds)

    def test_source_floor_counts_source_paragraphs_not_archives(self):
        text = """## Required claims
1. Claim
## Ledger
| Claim | Status | Sources | Note |
|---|---|---|---|
| 1 | SUPPORTED | `70_Research/test/raw/a.json`, `70_Research/test/raw/b.json` | ok |
## Sources
One source cites two archives: `70_Research/test/raw/a.json` and `70_Research/test/raw/b.json`.
"""
        self.assertEqual(research.supported_source_count(text), 1)
        self.assertFalse(research.proved(text, 2))

        bulleted = text.replace(
            "One source cites two archives: `70_Research/test/raw/a.json` and `70_Research/test/raw/b.json`.",
            "- First source: `70_Research/test/raw/a.json`.\n"
            "- Second source: `70_Research/test/raw/b.json`.",
        )
        indented_bullets = text.replace(
            "One source cites two archives: `70_Research/test/raw/a.json` and `70_Research/test/raw/b.json`.",
            "  - First source: `70_Research/test/raw/a.json`.\n"
            "  - Second source: `70_Research/test/raw/b.json`.",
        )
        nested_bullet = text.replace(
            "One source cites two archives: `70_Research/test/raw/a.json` and `70_Research/test/raw/b.json`.",
            "- First source: `70_Research/test/raw/a.json`.\n"
            "  - Detail: `70_Research/test/raw/b.json`.\n"
            "- Second source: `70_Research/test/raw/b.json`.",
        )
        paragraphs = text.replace(
            "One source cites two archives: `70_Research/test/raw/a.json` and `70_Research/test/raw/b.json`.",
            "First source: `70_Research/test/raw/a.json`.\n\n"
            "Second source: `70_Research/test/raw/b.json`.",
        )
        self.assertEqual(research.supported_source_count(bulleted), 2)
        self.assertEqual(research.supported_source_count(indented_bullets), 2)
        self.assertEqual(research.supported_source_count(nested_bullet), 2)
        self.assertEqual(research.supported_source_count(paragraphs), 2)
        self.assertTrue(research.proved(bulleted, 2))
        self.assertTrue(research.proved(paragraphs, 2))

        duplicate = text.replace(
            "| 1 | SUPPORTED |",
            "| 1 | TODO | | duplicate |\n| 1 | SUPPORTED |",
        )
        self.assertIn(
            "claim 1 has duplicate ledger rows",
            research.scriptable_problems(
                duplicate,
                None,
                {"sources_per_claim": 1, "source_floor": 0},
                root=self.root,
            ),
        )

    def test_deep_claim_requires_independent_lookup_subjects(self):
        first = self.root / "70_Research" / "test" / "raw" / "a.json"
        second = first.with_name("b.json")
        first.parent.mkdir(parents=True)
        self.write_envelope(first, subject="arXiv:2506.08837v2", kind="paper")
        self.write_envelope(
            second,
            subject="https://arxiv.org/pdf/2506.08837.pdf",
            kind="fulltext",
        )
        text = """## Required claims
1. Claim
## Ledger
| Claim | Status | Sources | Note |
|---|---|---|---|
| 1 | SUPPORTED | `70_Research/test/raw/a.json`, `70_Research/test/raw/b.json` | ok |
## Sources
One: `70_Research/test/raw/a.json`.

Two: `70_Research/test/raw/b.json`.
"""
        problems = research.scriptable_problems(
            text,
            None,
            {"sources_per_claim": 2, "source_floor": 0},
            root=self.root,
        )
        self.assertIn("supported claim 1 cites too few independent sources", problems)

        self.write_envelope(first, subject="AlmaLinux 10", kind="eol")
        self.write_envelope(second, subject="almalinux 10", kind="eol")
        problems = research.scriptable_problems(
            text,
            None,
            {"sources_per_claim": 2, "source_floor": 0},
            root=self.root,
        )
        self.assertIn("supported claim 1 cites too few independent sources", problems)

        self.write_envelope(first, subject="first-paper", kind="paper")
        self.write_envelope(second, subject="second-paper", kind="paper")
        problems = research.scriptable_problems(
            text,
            None,
            {"sources_per_claim": 2, "source_floor": 0},
            root=self.root,
        )
        self.assertNotIn(
            "supported claim 1 cites too few independent sources", problems
        )

        self.write_envelope(first, subject="10.1145/example", kind="paper")
        second.write_text(
            json.dumps(
                {
                    "url": "https://api.firecrawl.dev/v2/scrape",
                    "status": 200,
                    "body": "{}",
                    "sha256": hashlib.sha256(b"{}").hexdigest(),
                    "lookup": {
                        "kind": "fulltext",
                        "arguments": ["https://dl.acm.org/doi/pdf/10.1145/example"],
                        "subject": "10.1145/example",
                    },
                }
            )
        )
        self.assertIn(
            "supported claim 1 cites too few independent sources",
            research.scriptable_problems(
                text,
                None,
                {"sources_per_claim": 2, "source_floor": 0},
                root=self.root,
            ),
        )

    def test_command_variants_share_nonpaper_evidence_subjects(self):
        for first, second in (
            (
                {"kind": "page", "arguments": ["https://www.example.com/a/"]},
                {"kind": "page", "arguments": ["https://example.com/a"]},
            ),
            (
                {"kind": "eol", "arguments": ["AlmaLinux"]},
                {"kind": "eol", "arguments": ["almalinux", "10"]},
            ),
            (
                {"kind": "repo", "arguments": ["owner/name"]},
                {"kind": "repo", "arguments": ["OWNER/NAME", "README.md"]},
            ),
        ):
            with self.subTest(first=first, second=second):
                self.assertEqual(
                    research.evidence_subject({"lookup": first}),
                    research.evidence_subject({"lookup": second}),
                )

    def test_round_loop_returns_nonindependent_deep_claim_to_todo(self):
        path = self.make_runnable_topic(self.root, "test-deep")
        path.write_text(path.read_text().replace("**Mode:** survey", "**Mode:** deep"))
        first = path.parent / "raw" / "paper.json"
        second = path.parent / "raw" / "fulltext.json"

        def gather(*_args, **_kwargs):
            self.write_envelope(
                first, subject="10.48550/arXiv.2506.08837", kind="paper"
            )
            self.write_envelope(
                second,
                subject="https://arxiv.org/pdf/2506.08837",
                kind="fulltext",
            )
            text = path.read_text().replace(
                "| 1 | TODO | | open |",
                "| 1 | SUPPORTED | `70_Research/test-deep/sources/raw/paper.json`, "
                "`70_Research/test-deep/sources/raw/fulltext.json` | asserted |",
            )
            text = text.replace(
                "## Sources\n",
                "## Sources\n\nEvidence: `70_Research/test-deep/sources/raw/paper.json` "
                "and `70_Research/test-deep/sources/raw/fulltext.json`.\n",
            )
            path.write_text(text)
            return {"error": False, "cost_usd": 0.1}

        config = {
            "presets": {
                "deep": {
                    "rounds": 1,
                    "calls": 5,
                    "cost_usd": 1.0,
                    "source_floor": 1,
                    "sources_per_claim": 2,
                }
            }
        }
        with (
            mock.patch.object(research, "gather_once", side_effect=gather),
            mock.patch.object(
                research,
                "isolated_check",
                return_value={
                    "cost_usd": 0.0,
                    "rejected": {},
                    "budget_exit": False,
                },
            ),
            mock.patch.object(research, "load_config", return_value=config),
        ):
            self.assertEqual(
                research.run_topic("test-deep", root=self.root), "round limit"
            )
        result = path.read_text()
        self.assertIn("| 1 | TODO |", result)
        self.assertIn("too few lookup subjects", result)

    def test_adding_initial_todo_is_not_claim_movement(self):
        before = {}
        after = {1: "TODO"}
        moved = sum(
            before.get(claim, "TODO") != status for claim, status in after.items()
        )
        self.assertEqual(moved, 0)

    def test_round_loop_passes_true_subcent_remainder(self):
        path = self.make_runnable_topic(self.root)
        seen = []

        def gather(*_args, **kwargs):
            seen.append(kwargs["cost_limit"])
            if len(seen) == 1:
                path.write_text(
                    path.read_text().replace(
                        "| 1 | TODO | | open |", "| 1 | GAP | | moved |"
                    )
                )
                return {"error": False, "cost_usd": 0.995}
            return {
                "error": True,
                "subtype": "error_max_budget_usd",
                "cost_usd": 0.005,
            }

        config = {
            "presets": {
                "survey": {
                    "rounds": 3,
                    "calls": 5,
                    "cost_usd": 1.0,
                    "source_floor": 1,
                }
            }
        }
        with (
            mock.patch.object(research, "gather_once", side_effect=gather),
            mock.patch.object(research, "load_config", return_value=config),
        ):
            self.assertEqual(
                research.run_topic("test-b14", root=self.root), "cost limit"
            )
        self.assertEqual(seen[0], 1.0)
        self.assertAlmostEqual(seen[1], 0.005)

    def test_isolated_check_gets_complete_wrapped_claim_and_rejects_it(self):
        path = self.make_runnable_topic(self.root, "test-b15")
        archive = path.parent / "raw" / "claim.json"
        archive.write_text(json.dumps({"body": "The feature is disabled."}))
        path.write_text(
            path.read_text()
            .replace(
                "1. filled",
                "1. The feature remains enabled when the service restarts,\n"
                "   and the archive must prove both parts.",
            )
            .replace(
                "| 1 | TODO | | open |",
                "| 1 | SUPPORTED | `70_Research/test-b15/sources/raw/claim.json` | asserted |",
            )
        )
        result = {
            "error": False,
            "cost_usd": 0.12,
            "events": [
                {
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "StructuredOutput",
                                "input": {"claims": []},
                            }
                        ]
                    }
                }
            ],
            "structured_output": {
                "claims": [
                    {
                        "claim": 1,
                        "supported": False,
                        "passage": "",
                        "reason": "The archive says the feature is disabled.",
                    }
                ]
            },
        }
        with mock.patch.object(research, "run_agent", return_value=result) as run:
            outcome = research.isolated_check(
                "test-b15", {1}, cost_limit=0.5, root=self.root
            )
        self.assertEqual(
            outcome["rejected"],
            {1: "The archive says the feature is disabled."},
        )
        text = path.read_text()
        self.assertIn(
            "| 1 | TODO | `70_Research/test-b15/sources/raw/claim.json` | "
            '"The archive says the feature is disabled." |',
            text,
        )
        self.assertIn(
            "Claim 1: The feature remains enabled when the service restarts, "
            "and the archive must prove both parts.",
            run.call_args.args[0],
        )
        self.assertIn("claim-1-1-claim.json", run.call_args.args[0])
        self.assertEqual(run.call_args.args[1], ["Read"])
        self.assertTrue(run.call_args.kwargs["stream"])
        self.assertEqual(run.call_args.kwargs["schema"], research.CHECK_SCHEMA)
        self.assertIn("research-check-", str(run.call_args.kwargs["working_directory"]))
        self.assertNotIn("Bash", run.call_args.args[1])

    def test_isolated_check_fails_closed_on_malformed_or_budget_result(self):
        for index, result in enumerate(
            (
                {
                    "error": False,
                    "cost_usd": 0.1,
                    "structured_output": {"claims": []},
                },
                {
                    "error": True,
                    "subtype": "error_max_budget_usd",
                    "cost_usd": 0.2,
                },
            )
        ):
            with self.subTest(index=index):
                root = self.root / str(index)
                path = self.make_runnable_topic(root, "test-b15")
                archive = path.parent / "raw" / "claim.json"
                archive.write_text("{}")
                path.write_text(
                    path.read_text().replace(
                        "| 1 | TODO | | open |",
                        "| 1 | SUPPORTED | `70_Research/test-b15/sources/raw/claim.json` | asserted |",
                    )
                )
                with mock.patch.object(research, "run_agent", return_value=result):
                    if index == 0:
                        with self.assertRaisesRegex(ValueError, "omitted claims"):
                            research.isolated_check(
                                "test-b15", {1}, cost_limit=0.5, root=root
                            )
                    else:
                        outcome = research.isolated_check(
                            "test-b15", {1}, cost_limit=0.5, root=root
                        )
                        self.assertTrue(outcome["budget_exit"])
                        self.assertEqual(outcome["cost_usd"], 0.2)
                self.assertIn("| 1 | TODO |", path.read_text())
                self.assertTrue(
                    any(
                        str(record["status"]).startswith("failed ")
                        for record in research.run_records("test-b15", root=root)
                    )
                )

    def test_isolated_check_fails_closed_when_agent_output_cannot_parse(self):
        path = self.make_runnable_topic(self.root, "test-b15")
        archive = path.parent / "raw" / "claim.json"
        archive.write_text("{}")
        path.write_text(
            path.read_text().replace(
                "| 1 | TODO | | open |",
                "| 1 | SUPPORTED | `70_Research/test-b15/sources/raw/claim.json` | asserted |",
            )
        )
        with (
            mock.patch.object(
                research,
                "run_agent",
                side_effect=ValueError("Claude returned invalid JSON"),
            ),
            self.assertRaisesRegex(ValueError, "invalid JSON"),
        ):
            research.isolated_check("test-b15", {1}, cost_limit=0.5, root=self.root)
        self.assertIn("| 1 | TODO |", path.read_text())
        self.assertIn("Claude returned invalid JSON", path.read_text())

    def test_round_loop_accounts_for_isolated_check_budget_exit(self):
        path = self.make_runnable_topic(self.root, "test-b15")
        archive = path.parent / "raw" / "claim.json"

        def gather(*_args, **_kwargs):
            archive.write_text("{}")
            path.write_text(
                path.read_text().replace(
                    "| 1 | TODO | | open |",
                    "| 1 | SUPPORTED | `70_Research/test-b15/sources/raw/claim.json` | asserted |",
                )
            )
            return {"error": False, "cost_usd": 0.2}

        checker = {
            "error": True,
            "subtype": "error_max_budget_usd",
            "cost_usd": 0.3,
        }
        config = {
            "presets": {
                "survey": {
                    "rounds": 3,
                    "calls": 5,
                    "cost_usd": 1.0,
                    "source_floor": 1,
                }
            }
        }
        with (
            mock.patch.object(research, "gather_once", side_effect=gather),
            mock.patch.object(research, "run_agent", return_value=checker),
            mock.patch.object(research, "load_config", return_value=config),
        ):
            self.assertEqual(
                research.run_topic("test-b15", root=self.root), "cost limit"
            )
        self.assertIn("| 1 | TODO |", path.read_text())
        self.assertIn("| 1 | 0 | 1 | 0 | 0.500000 | cost limit |", path.read_text())


if __name__ == "__main__":
    unittest.main()
