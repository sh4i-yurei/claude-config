"""Public behavior of the interactive session naming hook."""

from contextlib import redirect_stdout
import importlib.util
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
HOOK = ROOT / "hooks/herdr-session-name.py"
SPEC = importlib.util.spec_from_file_location("hooks.herdr-session-name", HOOK)
NAME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NAME)


def workspaces(labels=("Workflow upkeep", "IaC / Platform"), ids=("w1", "w3")):
    return (
        json.dumps(
            {
                "id": "cli:workspace:list",
                "result": {
                    "type": "workspace_list",
                    "workspaces": [
                        {
                            "active_tab_id": tab,
                            "agent_status": "working",
                            "focused": False,
                            "label": label,
                            "number": number,
                            "pane_count": panes,
                            "tab_count": 2,
                            "workspace_id": workspace,
                        }
                        for label, workspace, tab, number, panes in zip(
                            labels, ids, ("w1:t1", "w3:t1"), (1, 3), (3, 2)
                        )
                    ],
                },
            }
        )
        + "\n"
    )


def renamed(name):
    return (
        json.dumps(
            {
                "id": "cli:agent:rename",
                "result": {
                    "type": "agent_info",
                    "agent": {
                        "agent": "claude",
                        "agent_session": {
                            "agent": "claude",
                            "kind": "id",
                            "source": "herdr:claude",
                            "value": "session_test",
                        },
                        "agent_status": "idle",
                        "name": name,
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
            {"error": {"code": code, "message": message}, "id": f"cli:{command}"}
        )
        + "\n"
    )


class HerdrSessionName(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "herdr"
        shutil.copy(ROOT / "tests/fixtures/herdr/fake_herdr.py", fake)
        fake.chmod(0o755)
        self.env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(self.root),
            "FAKE_HERDR_SCENARIO": str(self.root / "scenario.json"),
            "FAKE_HERDR_CALLS": str(self.root / "calls.jsonl"),
            "CLAUDE_CODE_ENTRYPOINT": "cli",
            "HERDR_PANE_ID": "w1:p1",
            "HERDR_WORKSPACE_ID": "w3",
        }
        self.scenario = []

    def calls(self):
        path = Path(self.env["FAKE_HERDR_CALLS"])
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def step(self, args, *, output="", error="", status=0, **extra):
        self.scenario.append(
            {"args": args, "stdout": output, "stderr": error, "status": status, **extra}
        )

    def success(
        self,
        label="IaC / Platform",
        name="iac-platform",
        workspace="w3",
        labels=None,
        ids=None,
    ):
        self.step(
            ["workspace", "list"],
            output=workspaces(
                labels or ("Workflow upkeep", label), ids or ("w1", workspace)
            ),
        )
        self.step(["agent", "rename", "w1:p1", name], output=renamed(name))

    def run_hook(self, event='{"source":"startup"}', main_block=False):
        Path(self.env["FAKE_HERDR_SCENARIO"]).write_text(json.dumps(self.scenario))
        output = io.StringIO()
        with (
            patch.dict(os.environ, self.env, clear=True),
            patch.object(sys, "stdin", io.StringIO(event)),
            redirect_stdout(output),
        ):
            if main_block:
                with self.assertRaises(SystemExit) as raised:
                    runpy.run_path(str(HOOK), run_name="__main__")
                code = raised.exception.code
            else:
                code = NAME.main()
        return code, output.getvalue()

    def test_startup_resume_and_other_sources(self):
        for source, workspace, expected in (
            ("startup", "w3", "iac-platform"),
            ("resume", "w1", "workflow-upkeep"),
            ("clear", "w3", "iac-platform"),
            ("compact", "w3", "iac-platform"),
            ("fork", "w3", "iac-platform"),
        ):
            with self.subTest(source=source):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.env["HERDR_WORKSPACE_ID"] = workspace
                self.scenario = []
                self.success(name=expected)
                self.assertEqual(
                    self.run_hook(
                        json.dumps({"source": source}), main_block=source == "startup"
                    ),
                    (0, f"This session's herdr name is {expected}.\n"),
                )
                self.assertEqual(self.calls(), [step["args"] for step in self.scenario])

    def test_noninteractive_and_missing_inputs(self):
        for key, value, event in (
            ("CLAUDE_CODE_ENTRYPOINT", "sdk-cli", "{}"),
            ("CLAUDE_CODE_ENTRYPOINT", None, "{}"),
            ("HERDR_PANE_ID", None, "{}"),
            ("HERDR_WORKSPACE_ID", None, "{}"),
            (None, None, "bad json"),
        ):
            with self.subTest(key=key, value=value):
                old = self.env.copy()
                if key:
                    if value is None:
                        self.env.pop(key)
                    else:
                        self.env[key] = value
                self.assertEqual(self.run_hook(event), (0, ""))
                self.assertEqual(self.calls(), [])
                self.env = old

    def test_no_herdr_and_failed_lookup(self):
        self.env["PATH"] = "/usr/bin:/bin"
        self.assertEqual(self.run_hook(), (0, ""))
        self.env["PATH"] = f"{self.root / 'bin'}:/usr/bin:/bin"
        self.step(
            ["workspace", "list"],
            error=failure("workspace:list", "unavailable", "server failed"),
            status=1,
        )
        self.assertEqual(self.run_hook(), (0, ""))
        self.assertEqual(len(self.calls()), 1)

    def test_missing_workspace_and_invalid_label(self):
        self.step(["workspace", "list"], output=workspaces())
        self.env["HERDR_WORKSPACE_ID"] = "w9"
        self.assertEqual(self.run_hook(), (0, ""))
        self.assertEqual(len(self.calls()), 1)
        Path(self.env["FAKE_HERDR_CALLS"]).unlink()
        self.env["HERDR_WORKSPACE_ID"] = "w3"
        self.scenario[0]["stdout"] = workspaces(labels=("Workflow upkeep", "///"))
        self.assertEqual(self.run_hook(), (0, ""))
        self.assertEqual(len(self.calls()), 1)

    def test_rename_errors(self):
        for code in ("agent_name_taken", "agent_not_found"):
            with self.subTest(code=code):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.success()
                message = (
                    "agent name workflow-upkeep is already used; candidates: terminal_id=term_test pane_id=w1:p1 workspace_id=w1 tab_id=w1:t1 cwd=/home/user status=Working"
                    if code == "agent_name_taken"
                    else "agent target w1:p1 not found"
                )
                self.scenario[1].update(
                    stdout="", stderr=failure("agent:rename", code, message), status=1
                )
                self.assertEqual(self.run_hook(), (0, ""))
                self.assertEqual(len(self.calls()), 2)

    def test_label_normalization(self):
        for label, name in (
            ("Staging Environment", "staging-environment"),
            ("  Bugfix -- Agent  ", "bugfix-agent"),
            ("Ansible Config", "ansible-config"),
        ):
            with self.subTest(label=label):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.success(label=label, name=name)
                self.assertEqual(
                    self.run_hook(), (0, f"This session's herdr name is {name}.\n")
                )
                self.assertEqual(self.calls(), [step["args"] for step in self.scenario])

    def test_herdr_malformed_answer_and_timeout(self):
        for response in ({"stdout": "not JSON"}, {"delay": 6, "stdout": workspaces()}):
            with self.subTest(response=response):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.step(["workspace", "list"], output=response["stdout"])
                self.scenario[0].update(response)
                self.assertEqual(self.run_hook(), (0, ""))
                self.assertEqual(len(self.calls()), 1)

    def test_herdr_process_cannot_start(self):
        fake = self.root / "bin/herdr"
        fake.write_text("#!/no/such/interpreter\n")
        self.assertEqual(self.run_hook(), (0, ""))

    def test_unreadable_workspace_and_rename_answers(self):
        for payload in (
            "[]",
            '["w3"]',
            '{"id":"cli:workspace:list","result":[]}',
            '{"id":"cli:workspace:list","result":{"workspaces":["w3"]}}',
            '{"id":"cli:workspace:list","result":{"type":"workspace_list"}}',
            '{"id":"cli:workspace:list"}',
        ):
            with self.subTest(payload=payload):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.step(["workspace", "list"], output=payload)
                self.assertEqual(self.run_hook(), (0, ""))
                self.assertEqual(self.calls(), [["workspace", "list"]])
        Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
        self.scenario = []
        self.success()
        self.scenario[1]["stdout"] = "[]"
        self.assertEqual(self.run_hook(), (0, ""))
        self.assertEqual(self.calls(), [step["args"] for step in self.scenario])

    def test_binary_failure_and_exit_status(self):
        for step in (
            {"stdout_hex": "ff7b7d0a"},
            {"delay": 5.5, "output": workspaces()},
            {"output": workspaces(), "status": 1},
        ):
            with self.subTest(step=step):
                Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
                self.scenario = []
                self.step(["workspace", "list"], **step)
                self.assertEqual(self.run_hook(), (0, ""))
                self.assertEqual(self.calls(), [["workspace", "list"]])
        Path(self.env["FAKE_HERDR_CALLS"]).unlink(missing_ok=True)
        self.scenario = []
        self.success()
        self.scenario[1].update(status=1)
        self.assertEqual(self.run_hook(), (0, ""))
        self.assertEqual(self.calls(), [step["args"] for step in self.scenario])
