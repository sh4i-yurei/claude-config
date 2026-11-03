"""Offline checks for the Claude fetch recorder's shared-log entry."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "mutants"
    if os.environ.get("MUTANT_UNDER_TEST") and ROOT.name != "mutants"
    else ROOT
)
sys.path.insert(0, str(SOURCE))
HOOK = SOURCE / "hooks" / "research-log.py"
from hooks.research_log_shared import registered_domain

SPEC = importlib.util.spec_from_file_location("research_log_hook", HOOK)
research_log = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(research_log)


class ResearchLogHookTests(unittest.TestCase):
    def test_registered_domain_groups_hosts(self):
        for host, expected in (
            ("docs.github.com", "github.com"),
            ("a.b.co.uk", "b.co.uk"),
            ("EXAMPLE.COM.", "example.com"),
            ("", ""),
        ):
            with self.subTest(host=host):
                self.assertEqual(registered_domain(host), expected)

    def test_webfetch_appends_to_shared_log(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            payload = {
                "session_id": "session",
                "tool_name": "WebFetch",
                "tool_input": {"url": "https://docs.example.com/page"},
                "tool_response": {"content": "ok"},
            }
            with (
                patch.object(research_log, "STATE_FILE", state),
                patch.object(research_log, "append_log") as append,
                patch.object(research_log, "repository_name", return_value="repo"),
                patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
            ):
                self.assertEqual(research_log.main(), 0)
            record = append.call_args.args[0]
            self.assertEqual(record["via"], "webfetch")
            self.assertEqual(record["host"], "docs.example.com")
            self.assertEqual(record["repo"], "repo")
            self.assertIsNone(record["archive"])

    def test_firecrawl_connector_updates_shared_seeded_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "session_id": "session",
                "tool_name": "mcp__firecrawl__firecrawl_search",
                "tool_input": {"query": "example"},
                "tool_response": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"success": True, "data": [], "creditsUsed": 2}
                        ),
                    }
                ],
            }
            with (
                patch.object(research_log, "STATE_FILE", root / "state.json"),
                patch.object(research_log, "GATEWAY_STATE", root / "gw-state.json"),
                patch.object(research_log, "GATEWAY_LOCK", root / "gw.lock"),
                patch.object(research_log, "append_log"),
                patch.object(research_log.time, "time", return_value=1_790_294_400.0),
                patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
            ):
                self.assertEqual(research_log.main(), 0)
            state = json.loads((root / "gw-state.json").read_text())
            self.assertEqual(state["api.firecrawl.dev"]["window_used"], 213)


if __name__ == "__main__":
    unittest.main()
