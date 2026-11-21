import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/token-usage/codex_tokens.py"
FIXTURES = ROOT / "tests/fixtures/token_usage/codex"
SESSIONS = FIXTURES / "sessions"
EXPECTED = FIXTURES / "expected"
SESSION_NAMES = {
    key: next(SESSIONS.rglob(f"rollout-{day}*.jsonl"))
    for key, day in {
        "S18": "2026-11-18",
        "S19": "2026-11-19",
        "S20": "2026-11-20",
        "SPARSE": "2026-11-21T01",
        "NOMETA": "2026-11-21T02",
        "S21": "2026-11-21T03",
    }.items()
}


@pytest.fixture
def codex(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in (
        "TOKEN_USAGE_OUT",
        "CX_CPT_OUT",
        "CX_CPT_TXT",
        "FORCE_COLOR",
        "PYTHON_COLORS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    name = "tools.token-usage.codex_tokens"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def assert_expected(folder):
    for name in ("cx_items.jsonl", "cx_calls.jsonl"):
        assert (folder / name).read_bytes() == (EXPECTED / name).read_bytes()


def assert_filtered(folder, keys):
    names = {SESSION_NAMES[key].name for key in keys}
    for name in ("cx_items.jsonl", "cx_calls.jsonl"):
        expected = b"".join(
            line
            for line in (EXPECTED / name).read_bytes().splitlines(keepends=True)
            if json.loads(line)["f"] in names
        )
        assert (folder / name).read_bytes() == expected


@pytest.fixture
def local_zone(monkeypatch):
    previous = os.environ.get("TZ")

    def set_zone(value):
        monkeypatch.setenv("TZ", value)
        time.tzset()

    yield set_zone
    if previous is None:
        monkeypatch.delenv("TZ", raising=False)
    else:
        monkeypatch.setenv("TZ", previous)
    time.tzset()


def copy_session(folder, key, name=None, start=None, before=None, after=None):
    source = SESSION_NAMES[key]
    target = folder / (name or str(source.relative_to(SESSIONS)))
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = source.read_text().splitlines(keepends=True)
    if start is not None:
        record = json.loads(lines[0])
        record["payload"]["timestamp"] = start
        lines[0] = json.dumps(record, separators=(",", ":")) + "\n"
    target.write_text((before or "") + "".join(lines) + (after or ""))
    return target


@pytest.mark.parametrize(
    "zone,options,keys",
    [
        ("CST6", ["--since", "2026-11-19", "--until", "2026-11-21"], {"S19", "S20"}),
        ("CST6", ["--since", "2026-11-21", "--until", "2026-11-21T04:00"], {"S21"}),
        ("UTC0", ["--since", "2026-11-21", "--until", "2026-11-21T04:00"], set()),
        (
            "CST6",
            [
                "--since",
                "2026-11-20T14:05:33.412Z",
                "--until",
                "2026-11-21T09:59:06.301Z",
            ],
            {"S20"},
        ),
        (
            "CST6",
            [
                "--since",
                "2026-11-20T08:05:33-06:00",
                "--until",
                "2026-11-20T14:05:33.600+00:00",
            ],
            {"S20"},
        ),
        ("CST6", ["--since", "2026-11-20"], {"S20", "S21"}),
        ("CST6", ["--until", "2026-11-19T12:40:24.501-06:00"], {"S18"}),
        (
            "CST6",
            ["--since", "0001-01-01T00:00:00+00:00"],
            {"S18", "S19", "S20", "S21"},
        ),
    ],
)
def test_window_fixture_sessions(
    codex, monkeypatch, tmp_path, capsys, local_zone, zone, options, keys
):
    local_zone(zone)
    monkeypatch.chdir(tmp_path)
    assert codex.main(["--sessions", str(SESSIONS), *options]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "left out 2 session file(s) with no readable start\n"
    assert_filtered(tmp_path, keys)


@pytest.mark.parametrize(
    "copies,expected_keys,count",
    [
        (["S18", "S20"], {"S18", "S20"}, 0),
        (["S18", "NOMETA"], {"S18"}, 1),
    ],
)
def test_window_copied_sessions(
    codex, monkeypatch, tmp_path, capsys, local_zone, copies, expected_keys, count
):
    local_zone("CST6")
    sessions = tmp_path / "sessions"
    for key in copies:
        copy_session(sessions, key)
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.chdir(output)
    assert codex.main(["--sessions", str(sessions), "--since", "2026-11-18"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"left out {count} session file(s) with no readable start\n" if count else ""
    )
    assert_filtered(output, expected_keys)


def test_window_unreadable_starts(codex, monkeypatch, tmp_path, capsys, local_zone):
    local_zone("CST6")
    sessions = tmp_path / "sessions"
    copy_session(sessions, "S18")
    for name, start in (
        ("bad-text", "2026-11-20 late"),
        ("naive", "2026-11-20T14:05:33.412"),
        ("number", 1763647533),
    ):
        copy_session(sessions, "S20", f"2026/11/20/{name}.jsonl", start=start)
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.chdir(output)
    assert codex.main(["--sessions", str(sessions), "--since", "2026-11-01"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "left out 3 session file(s) with no readable start\n"
    assert_filtered(output, {"S18"})


def test_window_first_session_meta(codex, monkeypatch, tmp_path, capsys, local_zone):
    local_zone("CST6")
    sessions = tmp_path / "sessions"
    copy_session(
        sessions,
        "S20",
        before='{"type":"event_msg","payload":{"type":"task_started"}}\n',
        after='{"timestamp":"2026-11-25T00:00:00.000Z","type":"session_meta","payload":{"timestamp":"2026-11-25T00:00:00.000Z","source":{"subagent":"review"}}}\n',
    )
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.chdir(output)
    assert codex.main(["--sessions", str(sessions), "--until", "2026-11-21"]) == 0
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert_filtered(output, {"S20"})


def test_no_window_keeps_unreadable_sessions(codex, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert codex.main(["--sessions", str(SESSIONS)]) == 0
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert_expected(tmp_path)


@pytest.mark.parametrize(
    "options,message",
    [
        (
            ["--since", "11/20/2026"],
            "argument --since: not an ISO 8601 date or date and time: '11/20/2026'",
        ),
        (
            ["--until", "2026-11-20T25:00"],
            "argument --until: not an ISO 8601 date or date and time: '2026-11-20T25:00'",
        ),
        (
            ["--since", "2026-11-21", "--until", "2026-11-20"],
            "--since must be before --until",
        ),
        (
            ["--since", "2026-11-20", "--until", "2026-11-20"],
            "--since must be before --until",
        ),
    ],
)
def test_bad_window_before_output(
    codex, monkeypatch, tmp_path, capsys, local_zone, options, message
):
    local_zone("CST6")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as error:
        codex.main(options)
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "usage: codex_tokens.py [-h] [--sessions FOLDER] [--since WHEN] [--until WHEN]\n"
        f"codex_tokens.py: error: {message}\n"
    )
    assert list(tmp_path.iterdir()) == []


def test_current_folder_is_resolved_when_main_runs(codex, monkeypatch, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.chdir(output)
    assert codex.main(["--sessions", str(SESSIONS)]) == 0
    assert_expected(output)


def test_output_environment_is_resolved_when_main_runs(codex, monkeypatch, tmp_path):
    output = tmp_path / "output"
    current = tmp_path / "current"
    output.mkdir()
    current.mkdir()
    monkeypatch.setenv("TOKEN_USAGE_OUT", str(output))
    monkeypatch.chdir(current)
    assert codex.main(["--sessions", str(SESSIONS)]) == 0
    assert_expected(output)
    assert list(current.iterdir()) == []


def test_default_sessions_is_resolved_when_main_runs(codex, monkeypatch, tmp_path):
    home = tmp_path / "later_home"
    shutil.copytree(SESSIONS, home / ".codex/sessions")
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(output)
    assert codex.main([]) == 0
    assert_expected(output)


def test_relative_sessions_folder(codex, monkeypatch, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setenv("TOKEN_USAGE_OUT", str(output))
    monkeypatch.chdir(SESSIONS.parent)
    assert codex.main(["--sessions", "sessions"]) == 0
    assert_expected(output)


def test_empty_sessions_folder(codex, monkeypatch, tmp_path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    sessions.mkdir()
    output.mkdir()
    monkeypatch.chdir(output)
    assert codex.main(["--sessions", str(sessions)]) == 0
    assert (output / "cx_items.jsonl").read_bytes() == b""
    assert (output / "cx_calls.jsonl").read_bytes() == b""


def test_unknown_option(codex, monkeypatch, tmp_path, capsys):
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.chdir(output)
    with pytest.raises(SystemExit) as error:
        codex.main(["--bogus"])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "usage: codex_tokens.py [-h] [--sessions FOLDER] [--since WHEN] [--until WHEN]\n"
        "codex_tokens.py: error: unrecognized arguments: --bogus\n"
    )
    assert list(output.iterdir()) == []


def test_help(codex, capsys):
    with pytest.raises(SystemExit) as error:
        codex.main(["--help"])
    assert error.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        "usage: codex_tokens.py [-h] [--sessions FOLDER] [--since WHEN] [--until WHEN]\n\n"
        "Attribute Codex context tokens to the action that put them there.\n\n"
        "options:\n"
        "  -h, --help         show this help message and exit\n"
        "  --sessions FOLDER  folder of Codex session files to read (default:\n"
        "                     ~/.codex/sessions)\n"
        "  --since WHEN       keep only sessions that started at or after WHEN, an ISO\n"
        "                     8601 date or date and time read in local time when it has\n"
        "                     no offset\n"
        "  --until WHEN       keep only sessions that started before WHEN, given the\n"
        "                     same way as --since\n"
    )


def test_script_entry_returns_main_status(codex, monkeypatch, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.chdir(output)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--sessions", str(SESSIONS)])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert error.value.code == 0
    assert_expected(output)
