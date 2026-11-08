from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/handoff_cost"
SCRIPT = ROOT / "tools/workflow/handoff_cost.py"
HANDOFF = "2026-11-07-claude-to-codex-workflow-upkeep-handoff-facts.md"
sys.path.insert(0, str(ROOT))
from tools.workflow.handoff_cost import main


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(args))
    return code, out.getvalue(), err.getvalue()


def sessions(name):
    return str(FIXTURES / name)


SINGLE = (
    "rollout-2026-11-07T09-12-07-01a1c217-4d8b-7b94-9f61-c2a03e5b7f04.jsonl: "
    "1 steps, 53466 input tokens (50048 cached), 984 output tokens\n"
    "1 sessions, 1 steps, 53466 input tokens (50048 cached), 984 output tokens\n"
)
THREE_SESSIONS = (
    "rollout-2026-11-06T21-40-12-01a1bf3c-5e20-7d41-a7c3-6f0b2d9e1a01.jsonl: "
    "2 steps, 47934 input tokens (33792 cached), 861 output tokens\n"
    "rollout-2026-11-07T08-31-50-01a1c1f0-9c3e-7a63-b2d8-1e5f4c7a8d03.jsonl: "
    "2 steps, 92069 input tokens (79616 cached), 1161 output tokens\n"
    "2 sessions, 4 steps, 140003 input tokens (113408 cached), 2022 output tokens\n"
)


class HandoffCost(unittest.TestCase):
    def test_matching_sessions_print_in_path_order_with_a_total(self):
        self.assertEqual(
            run(HANDOFF, "--sessions", sessions("three_sessions")),
            (
                0,
                THREE_SESSIONS,
                "",
            ),
        )

    def test_full_path_compares_only_the_file_name(self):
        path = f"~/Documents/Second_Brain/05_Agents/handoffs/{HANDOFF}"
        self.assertEqual(
            run(path, "--sessions", sessions("three_sessions")),
            (0, THREE_SESSIONS, ""),
        )

    def test_invalid_middle_line_does_not_stop_the_session(self):
        self.assertEqual(
            run(HANDOFF, "--sessions", sessions("invalid_middle")),
            (
                0,
                "rollout-2026-11-02T21-22-16-01a19f6d-cf4b-72b3-a100-69fae0e44600.jsonl: "
                "2 steps, 489565 input tokens (488448 cached), 3795 output tokens\n"
                "1 sessions, 2 steps, 489565 input tokens (488448 cached), 3795 output tokens\n",
                "",
            ),
        )

    def test_help_describes_the_command(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn(
            "Count the Codex sessions that followed one handoff, with their steps and tokens.",
            " ".join(out.getvalue().split()),
        )
        self.assertEqual(err.getvalue(), "")

    def test_request_after_the_agents_instructions_matches(self):
        self.assertEqual(
            run(HANDOFF, "--sessions", sessions("single")), (0, SINGLE, "")
        )

    def test_first_request_decides_the_session(self):
        self.assertEqual(
            run(HANDOFF, "--sessions", sessions("two_requests")),
            (
                0,
                "rollout-2026-11-07T09-47-26-01a1c238-7e15-7c25-a4f7-5d81b9c2e305.jsonl: "
                "2 steps, 109089 input tokens (108672 cached), 210 output tokens\n"
                "1 sessions, 2 steps, 109089 input tokens (108672 cached), 210 output tokens\n",
                "",
            ),
        )
        later = "2026-11-07-claude-to-codex-workflow-upkeep-handoff-cost.md"
        self.assertEqual(
            run(later, "--sessions", sessions("two_requests")),
            (1, "", f"no Codex session followed {later}\n"),
        )

    def test_compaction_call_is_counted_from_the_records(self):
        self.assertEqual(
            run(HANDOFF, "--sessions", sessions("compaction")),
            (
                0,
                "rollout-2026-11-02T21-22-16-01a19f6d-cf4b-72b3-a100-69fae0e44600.jsonl: "
                "2 steps, 489565 input tokens (488448 cached), 3795 output tokens\n"
                "1 sessions, 2 steps, 489565 input tokens (488448 cached), 3795 output tokens\n",
                "",
            ),
        )

    def test_steps_count_records_not_token_count_events(self):
        self.assertEqual(
            run(HANDOFF, "--sessions", sessions("more_counts")),
            (
                0,
                "rollout-2026-11-02T21-22-16-01a19f6d-cf4b-72b3-a100-69fae0e44600.jsonl: "
                "1 steps, 245276 input tokens (245120 cached), 2845 output tokens\n"
                "1 sessions, 1 steps, 245276 input tokens (245120 cached), 2845 output tokens\n",
                "",
            ),
        )

    def test_partial_last_line_is_skipped(self):
        self.assertEqual(
            run(HANDOFF, "--sessions", sessions("partial_line")),
            (
                0,
                "rollout-2026-11-07T10-41-38-01a1c26e-8b52-7fb8-a1d9-6c4e2f7b3508.jsonl: "
                "1 steps, 57632 input tokens (57472 cached), 173 output tokens\n"
                "1 sessions, 1 steps, 57632 input tokens (57472 cached), 173 output tokens\n",
                "",
            ),
        )

    def test_session_without_a_request_is_ignored(self):
        self.assertEqual(
            run(HANDOFF, "--sessions", sessions("no_request")),
            (
                0,
                "rollout-2026-11-07T10-20-15-01a1c256-c3d7-7e87-95a2-3b6f8e1d4a07.jsonl: "
                "1 steps, 57290 input tokens (54912 cached), 318 output tokens\n"
                "1 sessions, 1 steps, 57290 input tokens (54912 cached), 318 output tokens\n",
                "",
            ),
        )

    def test_sessions_default_to_codex_folder_under_home(self):
        with tempfile.TemporaryDirectory() as home:
            shutil.copytree(FIXTURES / "single", Path(home) / ".codex/sessions")
            with patch.dict(os.environ, {"HOME": home}):
                self.assertEqual(run(HANDOFF), (0, SINGLE, ""))

    def test_script_runs_main_and_exits_with_its_status(self):
        out = io.StringIO()
        argv = [str(SCRIPT), HANDOFF, "--sessions", sessions("single")]
        with patch.object(sys, "argv", argv), redirect_stdout(out):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(SCRIPT), run_name="__main__")
        self.assertEqual((raised.exception.code, out.getvalue()), (0, SINGLE))

    def test_no_matching_session_is_an_error(self):
        self.assertEqual(
            run(HANDOFF, "--sessions", sessions("other_handoff")),
            (1, "", f"no Codex session followed {HANDOFF}\n"),
        )

    def test_missing_handoff_argument_exits_2(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                main([])
        self.assertEqual((raised.exception.code, out.getvalue()), (2, ""))


if __name__ == "__main__":
    unittest.main()
