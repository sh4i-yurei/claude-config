"""Public behavior of the handoff delivery command."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.workflow import handoff_send


def answer(command, status="idle"):
    return (
        json.dumps(
            {
                "id": f"cli:agent:{command}",
                "result": {
                    "type": "agent_prompted" if command == "prompt" else "agent_info",
                    "agent": {
                        "agent": "codex",
                        "agent_session": {
                            "agent": "codex",
                            "kind": "id",
                            "source": "herdr:codex",
                            "value": "session_test",
                        },
                        "agent_status": status,
                        "name": "workflow-upkeep",
                        "pane_id": "w1:p1",
                        "cwd": "/home/user",
                        "focused": False,
                        "foreground_cwd": "/home/user",
                        "revision": 3,
                        "state_change_seq": 376,
                        "tab_id": "w1:t1",
                        "terminal_id": "term_test",
                        "terminal_title": "Claude Code",
                        "terminal_title_stripped": "Claude Code",
                        "workspace_id": "w1",
                    },
                },
            }
        )
        + "\n"
    )


def failure(command, code, message):
    return (
        json.dumps(
            {"error": {"code": code, "message": message}, "id": f"cli:agent:{command}"}
        )
        + "\n"
    )


class HandoffSend(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.folder = self.root / "handoffs"
        self.folder.mkdir()
        self.handoff = self.folder / "delivery.md"
        self.handoff.write_text(
            "---\nstate: open\nsession: workflow-upkeep\nreply_to: backups\n---\n# Request\n"
        )
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "herdr"
        shutil.copy(ROOT / "tests/fixtures/herdr/fake_herdr.py", fake)
        fake.chmod(0o755)
        self.env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(self.root),
            "HANDOFFS_DIR": str(self.folder),
            "FAKE_HERDR_SCENARIO": str(self.root / "scenario.json"),
            "FAKE_HERDR_CALLS": str(self.root / "calls.jsonl"),
        }
        self.scenario = []

    def calls(self):
        path = Path(self.env["FAKE_HERDR_CALLS"])
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def step(self, args, *, output=None, error=None, status=0, **extra):
        self.scenario.append(
            {
                "args": args,
                "stdout": output or "",
                "stderr": error or "",
                "status": status,
                **extra,
            }
        )

    def success(
        self,
        mode="deliver",
        target="workflow-upkeep",
        wait=1800000,
        prompt_status="working",
    ):
        self.step(["agent", "get", target], output=answer("get"))
        self.step(
            ["agent", "wait", target, "--timeout", str(wait)], output=answer("wait")
        )
        text = (
            f"Read {self.handoff.resolve()} and follow its Request."
            if mode == "deliver"
            else f"Your handoff {self.handoff.resolve()} has its Response."
        )
        self.step(
            [
                "agent",
                "prompt",
                target,
                text,
                "--wait",
                "--until",
                "working",
                "--until",
                "blocked",
                "--timeout",
                "10000",
            ],
            output=answer("prompt", prompt_status),
        )

    def run_command(self, *args, main_block=False):
        Path(self.env["FAKE_HERDR_SCENARIO"]).write_text(json.dumps(self.scenario))
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, self.env, clear=True),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            if main_block:
                with (
                    patch.object(
                        sys,
                        "argv",
                        [str(ROOT / "tools/workflow/handoff_send.py"), *args],
                    ),
                    self.assertRaises(SystemExit) as raised,
                ):
                    runpy.run_path(
                        str(ROOT / "tools/workflow/handoff_send.py"),
                        run_name="__main__",
                    )
                code = raised.exception.code
            else:
                try:
                    code = handoff_send.main(list(args))
                except SystemExit as exit_status:
                    code = exit_status.code
        return code, out.getvalue(), err.getvalue()

    def test_deliver_path_and_name_and_main_block(self):
        for value, main_block in (
            (str(self.handoff), False),
            (self.handoff.name, True),
        ):
            with self.subTest(value=value):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.success()
                self.assertEqual(
                    self.run_command("deliver", value, main_block=main_block),
                    (0, "delivered delivery.md to workflow-upkeep\n", ""),
                )
                self.assertEqual(self.calls(), [step["args"] for step in self.scenario])

    def test_default_folder_and_wait_minutes(self):
        self.env.pop("HANDOFFS_DIR")
        folder = self.root / "Documents/Second_Brain/05_Agents/handoffs"
        folder.mkdir(parents=True)
        self.handoff = folder / "delivery.md"
        self.handoff.write_text("---\nstate: open\nsession: workflow-upkeep\n---\n")
        self.success(wait=300000)
        self.assertEqual(
            self.run_command("deliver", "delivery.md", "--wait-minutes", "5")[0], 0
        )
        self.assertEqual(self.calls(), [step["args"] for step in self.scenario])

    def test_reply(self):
        self.handoff.write_text("---\nstate: done\nreply_to: backups\n---\n")
        self.success(mode="reply", target="backups")
        self.assertEqual(
            self.run_command("reply", self.handoff.name),
            (0, "told backups that delivery.md has its Response\n", ""),
        )
        self.assertEqual(self.calls(), [step["args"] for step in self.scenario])

    def test_refused_handoffs_without_calls(self):
        cases = [
            ("state: done\nsession: workflow-upkeep", "delivery.md is done, not open"),
            (
                "state: draft\nsession: workflow-upkeep",
                "delivery.md is draft, not open",
            ),
            ("session: workflow-upkeep", "delivery.md has no state: field"),
            ("state: open", "delivery.md has no session: field"),
            ("state: open\nsession:", "delivery.md has no session: field"),
            ("[bad", "delivery.md has no readable frontmatter"),
            ("- list", "delivery.md has no readable frontmatter"),
            ("", "delivery.md has no readable frontmatter"),
        ]
        for contents, message in cases:
            with self.subTest(contents=contents):
                self.handoff.write_text(f"---\n{contents}\n---\n")
                self.assertEqual(
                    self.run_command("deliver", self.handoff.name),
                    (2, "", message + "\n"),
                )
                self.assertEqual(self.calls(), [])
        self.handoff.write_text("no frontmatter")
        self.assertEqual(
            self.run_command("deliver", self.handoff.name),
            (2, "", "delivery.md has no readable frontmatter\n"),
        )
        self.handoff.write_text("---\nstate: done\n---\n")
        self.assertEqual(
            self.run_command("reply", self.handoff.name),
            (2, "", "delivery.md has no reply_to: field\n"),
        )

    def test_bad_paths_and_arguments(self):
        outside = self.root / "outside.md"
        outside.write_text(self.handoff.read_text())
        nonmd = self.folder / "plain.txt"
        nonmd.write_text(self.handoff.read_text())
        for path in (str(outside), str(nonmd)):
            self.assertEqual(
                self.run_command("deliver", path),
                (2, "", f"not a handoff in {self.folder.resolve()}: {path}\n"),
            )
        self.assertEqual(
            self.run_command("deliver", "missing.md"),
            (2, "", "no such handoff: missing.md\n"),
        )
        for value in ("0", "abc"):
            code, _, err = self.run_command(
                "deliver", self.handoff.name, "--wait-minutes", value
            )
            self.assertEqual(code, 2)
            self.assertEqual(
                err.splitlines()[-1],
                "handoff_send.py: error: argument --wait-minutes: must be a positive whole number",
            )
        self.assertEqual(self.calls(), [])

    def test_no_herdr(self):
        self.env["PATH"] = "/usr/bin:/bin"
        self.assertEqual(
            self.run_command("deliver", self.handoff.name),
            (2, "", "herdr is not on PATH\n"),
        )

    def test_target_failures(self):
        missing = failure(
            "get", "agent_not_found", "agent target workflow-upkeep not found"
        )
        self.step(["agent", "get", "workflow-upkeep"], error=missing, status=1)
        self.assertEqual(
            self.run_command("deliver", self.handoff.name),
            (1, "", "no live session named workflow-upkeep\n"),
        )
        self.assertEqual(len(self.calls()), 1)

    def test_blocked_timeout_and_done_wait(self):
        for status, error_text in (
            ("blocked", "workflow-upkeep is waiting on a prompt; nothing was sent"),
            (
                "timeout",
                "workflow-upkeep was not idle after 30 minutes; nothing was sent",
            ),
            ("done", None),
        ):
            with self.subTest(status=status):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.success()
                if status == "timeout":
                    self.scenario[1].update(
                        stdout="",
                        stderr=failure(
                            "wait", "timeout", "timed out waiting for agent status"
                        ),
                        status=1,
                    )
                else:
                    self.scenario[1]["stdout"] = answer("wait", status)
                code, out, err = self.run_command("deliver", self.handoff.name)
                self.assertEqual(
                    (code, err), (1, error_text + "\n") if error_text else (0, "")
                )
                self.assertEqual(len(self.calls()), 2 if error_text else 3)

    def test_prompt_outcomes(self):
        for status in (
            "blocked",
            "idle",
            "agent_blocked",
            "agent_not_found",
            "agent_prompt_stalled",
        ):
            with self.subTest(status=status):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.success(prompt_status=status)
                if status.startswith("agent_"):
                    self.scenario[2].update(
                        stdout="",
                        stderr=failure(
                            "prompt",
                            status,
                            {
                                "agent_blocked": "agent workflow-upkeep is blocked and requires interactive input",
                                "agent_not_found": "agent target workflow-upkeep not found",
                                "agent_prompt_stalled": "agent prompt produced no observed working or blocked state within 5000 ms; current status is idle",
                            }[status],
                        ),
                        status=1,
                    )
                if status == "agent_prompt_stalled":
                    self.step(
                        ["agent", "send-keys", "workflow-upkeep", "enter"],
                        output=json.dumps(
                            {"id": "cli:agent:send-keys", "result": {"type": "ok"}}
                        ),
                    )
                    self.step(
                        [
                            "agent",
                            "wait",
                            "workflow-upkeep",
                            "--until",
                            "working",
                            "--until",
                            "blocked",
                            "--timeout",
                            "5000",
                        ],
                        output=answer("wait", "working"),
                    )
                code, out, err = self.run_command("deliver", self.handoff.name)
                expected = {
                    "blocked": (0, "delivered delivery.md to workflow-upkeep\n", ""),
                    "idle": (
                        1,
                        "",
                        "workflow-upkeep did not start on the prompt; it may be sitting in its input box\n",
                    ),
                    "agent_blocked": (
                        1,
                        "",
                        "workflow-upkeep is waiting on a prompt; nothing was sent\n",
                    ),
                    "agent_not_found": (
                        1,
                        "",
                        "no live session named workflow-upkeep\n",
                    ),
                    "agent_prompt_stalled": (
                        0,
                        "delivered delivery.md to workflow-upkeep\n",
                        "",
                    ),
                }[status]
                self.assertEqual((code, out, err), expected)
                self.assertEqual(self.calls(), [step["args"] for step in self.scenario])

    def test_stall_timeout_and_other_error(self):
        self.success()
        self.scenario[2].update(
            stdout="",
            stderr=failure(
                "prompt",
                "agent_prompt_stalled",
                "agent prompt produced no observed working or blocked state within 5000 ms; current status is idle",
            ),
            status=1,
        )
        self.step(
            ["agent", "send-keys", "workflow-upkeep", "enter"],
            output=json.dumps({"id": "cli:agent:send-keys", "result": {"type": "ok"}}),
        )
        self.step(
            [
                "agent",
                "wait",
                "workflow-upkeep",
                "--until",
                "working",
                "--until",
                "blocked",
                "--timeout",
                "5000",
            ],
            error=failure("wait", "timeout", "timed out waiting for agent status"),
            status=1,
        )
        self.assertEqual(
            self.run_command("deliver", self.handoff.name),
            (
                1,
                "",
                "workflow-upkeep did not start on the prompt; it may be sitting in its input box\n",
            ),
        )
        Path(self.env["FAKE_HERDR_CALLS"]).unlink()
        self.scenario = self.scenario[:2]
        self.scenario[1].update(
            stdout="", stderr=failure("wait", "unexpected", "server failed"), status=1
        )
        self.assertEqual(
            self.run_command("deliver", self.handoff.name),
            (1, "", "herdr agent wait: server failed\n"),
        )

    def test_session_disappears_after_get(self):
        for index in (1, 2):
            with self.subTest(index=index):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.success()
                command = "wait" if index == 1 else "prompt"
                self.scenario[index].update(
                    stdout="",
                    stderr=failure(
                        command,
                        "agent_not_found",
                        "agent target workflow-upkeep not found",
                    ),
                    status=1,
                )
                self.assertEqual(
                    self.run_command("deliver", self.handoff.name),
                    (1, "", "no live session named workflow-upkeep\n"),
                )
                self.assertEqual(len(self.calls()), index + 1)

    def test_prompt_timeout_uses_herdr_error(self):
        self.success()
        self.scenario[2].update(
            stdout="",
            stderr=failure("prompt", "timeout", "timed out waiting for agent status"),
            status=1,
        )
        self.assertEqual(
            self.run_command("deliver", self.handoff.name),
            (1, "", "herdr agent prompt: timed out waiting for agent status\n"),
        )
        self.assertEqual(len(self.calls()), 3)

    def test_get_generic_error_and_unreadable_json(self):
        for error_text, expected in (
            (failure("get", "unavailable", "server failed"), "server failed"),
            ("not JSON", "invalid response"),
        ):
            with self.subTest(error_text=error_text):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.step(
                    ["agent", "get", "workflow-upkeep"], error=error_text, status=1
                )
                self.assertEqual(
                    self.run_command("deliver", self.handoff.name),
                    (1, "", f"herdr agent get: {expected}\n"),
                )
                self.assertEqual(len(self.calls()), 1)

    def test_stalled_prompt_send_keys_fails(self):
        for code, expected in (
            ("agent_not_found", "no live session named workflow-upkeep"),
            ("unavailable", "herdr agent send-keys: server failed"),
        ):
            with self.subTest(code=code):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.success()
                self.scenario[2].update(
                    stdout="",
                    stderr=failure(
                        "prompt",
                        "agent_prompt_stalled",
                        "agent prompt produced no observed working or blocked state within 5000 ms; current status is idle",
                    ),
                    status=1,
                )
                self.step(
                    ["agent", "send-keys", "workflow-upkeep", "enter"],
                    error=failure("send-keys", code, "server failed"),
                    status=1,
                )
                self.assertEqual(
                    self.run_command("deliver", self.handoff.name),
                    (1, "", expected + "\n"),
                )
                self.assertEqual(len(self.calls()), 4)

    def test_parser_and_relative_path(self):
        self.assertIn(
            "Deliver a handoff to a named interactive session.",
            [
                " ".join(part.split())
                for part in self.run_command("--help")[1].split("\n\n")
            ],
        )
        code, _, err = self.run_command("other", self.handoff.name)
        self.assertEqual(code, 2)
        self.assertIn(
            err.splitlines()[-1],
            (
                "handoff_send.py: error: argument mode: invalid choice: 'other' (choose from deliver, reply)",
                "handoff_send.py: error: argument mode: invalid choice: 'other' (choose from 'deliver', 'reply')",
            ),
        )
        self.assertEqual(self.calls(), [])
        self.success(wait=60000)
        with patch("os.getcwd", return_value=str(self.root)):
            self.assertEqual(
                self.run_command(
                    "deliver", "handoffs/delivery.md", "--wait-minutes", "1"
                ),
                (0, "delivered delivery.md to workflow-upkeep\n", ""),
            )
        self.assertEqual(self.calls(), [step["args"] for step in self.scenario])

    def test_unreadable_first_wait(self):
        for payload, status, stream in (
            ("boom", 1, "stderr"),
            ("boom", 0, "stdout"),
            ('{"id":"cli:agent:wait","result":{"type":"agent_info"}}', 0, "stdout"),
            ('{"id":"cli:agent:wait","result":[]}', 0, "stdout"),
        ):
            with self.subTest(payload=payload, status=status):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.success()
                self.scenario[1].update(stdout="", stderr="", status=status)
                self.scenario[1][stream] = payload
                self.assertEqual(
                    self.run_command("deliver", self.handoff.name),
                    (1, "", "herdr agent wait: invalid response\n"),
                )
                self.assertEqual(
                    self.calls(), [step["args"] for step in self.scenario[:2]]
                )

    def test_unreadable_get_and_prompt(self):
        bad_errors = (
            "[]",
            '{"error":"boom","id":"cli:agent:get"}',
            '{"error":{"message":"boom"},"id":"cli:agent:get"}',
            '{"error":{"code":"unavailable"},"id":"cli:agent:get"}',
            '{"error":{"code":"unavailable","message":5},"id":"cli:agent:get"}',
            '{"error":{"code":5,"message":"boom"},"id":"cli:agent:get"}',
        )
        for payload in bad_errors:
            with self.subTest(payload=payload):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.step(["agent", "get", "workflow-upkeep"], error=payload, status=1)
                self.assertEqual(
                    self.run_command("deliver", self.handoff.name),
                    (1, "", "herdr agent get: invalid response\n"),
                )
                self.assertEqual(self.calls(), [["agent", "get", "workflow-upkeep"]])
        Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
        self.scenario = []
        self.step(["agent", "get", "workflow-upkeep"], status=1, stderr_hex="ff7b7d0a")
        self.assertEqual(
            self.run_command("deliver", self.handoff.name),
            (1, "", "herdr agent get: invalid response\n"),
        )
        for payload, status, expected in (
            ("boom", 1, "herdr agent prompt: invalid response"),
            ("[]", 0, "herdr agent prompt: invalid response"),
            (
                '{"id":"cli:agent:prompt","result":{"type":"agent_prompted"}}',
                0,
                "workflow-upkeep did not start on the prompt; it may be sitting in its input box",
            ),
        ):
            with self.subTest(payload=payload, status=status):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.success()
                self.scenario[2].update(
                    stdout=payload if status == 0 else "",
                    stderr=payload if status else "",
                    status=status,
                )
                self.assertEqual(
                    self.run_command("deliver", self.handoff.name),
                    (1, "", expected + "\n"),
                )
                self.assertEqual(self.calls(), [step["args"] for step in self.scenario])

    def test_stall_followup_failures(self):
        for payload, status, expected in (
            ("boom", 1, "herdr agent send-keys: invalid response"),
            (None, 1, "no live session named workflow-upkeep"),
            ("boom", 0, "herdr agent wait: invalid response"),
            (None, 1, "herdr agent wait: server failed"),
            (
                '{"id":"cli:agent:wait","result":{"type":"agent_info"}}',
                0,
                "workflow-upkeep did not start on the prompt; it may be sitting in its input box",
            ),
            (
                answer("wait", "idle"),
                0,
                "workflow-upkeep did not start on the prompt; it may be sitting in its input box",
            ),
        ):
            with self.subTest(payload=payload, status=status):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.success()
                self.scenario[2].update(
                    stdout="",
                    stderr=failure(
                        "prompt",
                        "agent_prompt_stalled",
                        "agent prompt produced no observed working or blocked state within 5000 ms; current status is idle",
                    ),
                    status=1,
                )
                self.step(
                    ["agent", "send-keys", "workflow-upkeep", "enter"],
                    output=json.dumps(
                        {"id": "cli:agent:send-keys", "result": {"type": "ok"}}
                    ),
                )
                if expected == "herdr agent send-keys: invalid response":
                    self.scenario[3].update(stdout="", stderr=payload, status=1)
                else:
                    self.step(
                        [
                            "agent",
                            "wait",
                            "workflow-upkeep",
                            "--until",
                            "working",
                            "--until",
                            "blocked",
                            "--timeout",
                            "5000",
                        ],
                        output=payload if status == 0 else "",
                        error=(
                            failure(
                                "wait",
                                "agent_not_found",
                                "agent target workflow-upkeep not found",
                            )
                            if expected.startswith("no live")
                            else failure("wait", "unavailable", "server failed")
                            if payload is None
                            else payload
                        )
                        if status
                        else "",
                        status=status,
                    )
                self.assertEqual(
                    self.run_command("deliver", self.handoff.name),
                    (1, "", expected + "\n"),
                )
                self.assertEqual(self.calls(), [step["args"] for step in self.scenario])

    def test_numeric_session_is_refused(self):
        self.handoff.write_text("---\nstate: open\nsession: 5\n---\n")
        self.assertEqual(
            self.run_command("deliver", self.handoff.name),
            (2, "", "delivery.md has no session: field\n"),
        )
        self.assertEqual(self.calls(), [])
