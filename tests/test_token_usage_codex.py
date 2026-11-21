import importlib.util
from pathlib import Path
import runpy
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/token-usage/codex_tokens.py"
FIXTURES = ROOT / "tests/fixtures/token_usage/codex"
SESSIONS = FIXTURES / "sessions"
EXPECTED = FIXTURES / "expected"


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
        "usage: codex_tokens.py [-h] [--sessions FOLDER]\n"
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
        "usage: codex_tokens.py [-h] [--sessions FOLDER]\n\n"
        "Attribute Codex context tokens to the action that put them there.\n\n"
        "options:\n"
        "  -h, --help         show this help message and exit\n"
        "  --sessions FOLDER  folder of Codex session files to read (default:\n"
        "                     ~/.codex/sessions)\n"
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
