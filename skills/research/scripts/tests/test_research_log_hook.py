"""Offline checks for the Claude fetch recorder's shared-log entry."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HOOK = Path(__file__).resolve().parents[4] / "hooks" / "research-log.py"
SPEC = importlib.util.spec_from_file_location("research_log_hook", HOOK)
research_log = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(research_log)


class ResearchLogHookTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
