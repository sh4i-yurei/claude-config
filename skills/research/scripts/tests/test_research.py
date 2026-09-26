"""Offline checks for shared-log migration and verification."""

import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import research


class ResearchLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gateway = self.root / "gateway.jsonl"
        self.fetches = self.root / "fetches.jsonl"
        self.lock = self.root / "gateway.lock"

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


if __name__ == "__main__":
    unittest.main()
