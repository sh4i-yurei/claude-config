import importlib.util
import json
import math
import os
from pathlib import Path
import runpy
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/token-usage/claude_tokens.py"
FIXTURES = ROOT / "tests/fixtures/token_usage/claude"


@pytest.fixture
def claude(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ("TOKEN_USAGE_OUT", "FORCE_COLOR", "PYTHON_COLORS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "80")
    name = "tools.token-usage.claude_tokens"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def assert_value(actual, expected):
    if isinstance(actual, (int, float)) and not isinstance(actual, bool):
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            if isinstance(actual, float) or isinstance(expected, float):
                assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
            else:
                assert actual == expected
            return
    assert type(actual) is type(expected)
    if isinstance(actual, (list, tuple)):
        assert len(actual) == len(expected)
        for found, wanted in zip(actual, expected):
            assert_value(found, wanted)
    else:
        assert actual == expected


def assert_expected(folder, tree):
    for name in ("items.jsonl", "calls.jsonl"):
        found = [
            json.loads(line, object_pairs_hook=list)
            for line in (folder / name).read_text().splitlines()
        ]
        wanted = [
            json.loads(line, object_pairs_hook=list)
            for line in (FIXTURES / "expected" / tree / name).read_text().splitlines()
        ]
        assert len(found) == len(wanted)
        for actual, expected in zip(found, wanted):
            assert_value(actual, expected)


@pytest.mark.parametrize("tree", ["projects", "edge"])
def test_explicit_projects_after_chdir(claude, monkeypatch, tmp_path, tree):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    assert claude.main(["--projects", str(FIXTURES / tree)]) == 0
    assert_expected(out, tree)


def test_output_folder_at_call_time(claude, monkeypatch, tmp_path):
    out = tmp_path / "out"
    current = tmp_path / "current"
    out.mkdir()
    current.mkdir()
    monkeypatch.setenv("TOKEN_USAGE_OUT", str(out))
    monkeypatch.chdir(current)
    assert claude.main(["--projects", str(FIXTURES / "projects")]) == 0
    assert_expected(out, "projects")
    assert list(current.iterdir()) == []


def test_default_projects_at_call_time(claude, monkeypatch, tmp_path):
    home = tmp_path / "later_home"
    shutil.copytree(FIXTURES / "projects", home / ".claude/projects")
    monkeypatch.setenv("HOME", str(home))
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    assert claude.main([]) == 0
    assert_expected(out, "projects")


def test_relative_projects(claude, monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("TOKEN_USAGE_OUT", str(out))
    monkeypatch.chdir(FIXTURES)
    assert claude.main(["--projects", "projects"]) == 0
    assert_expected(out, "projects")


def test_empty_projects(claude, monkeypatch, tmp_path):
    projects = tmp_path / "projects"
    out = tmp_path / "out"
    projects.mkdir()
    out.mkdir()
    monkeypatch.chdir(out)
    assert claude.main(["--projects", str(projects)]) == 0
    for name in ("items.jsonl", "calls.jsonl"):
        assert (out / name).read_bytes() == b""


def test_bad_option(claude, monkeypatch, tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    with pytest.raises(SystemExit) as error:
        claude.main(["--bogus"])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "usage: claude_tokens.py [-h] [--projects FOLDER]\n"
        "claude_tokens.py: error: unrecognized arguments: --bogus\n"
    )
    assert list(out.iterdir()) == []


def test_help(claude, capsys):
    with pytest.raises(SystemExit) as error:
        claude.main(["--help"])
    assert error.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        "usage: claude_tokens.py [-h] [--projects FOLDER]\n\n"
        "Attribute Claude Code context tokens to the action that put them there.\n\n"
        "options:\n"
        "  -h, --help         show this help message and exit\n"
        "  --projects FOLDER  folder of Claude Code project folders to read (default:\n"
        "                     ~/.claude/projects)\n"
    )


def test_script_exit(claude, monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--projects", str(FIXTURES / "projects")]
    )
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert error.value.code == 0
    assert_expected(out, "projects")
