import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/token-usage/claude_tokens.py"
FIXTURES = ROOT / "tests/fixtures/token_usage/claude"
PROJECT = "-var-home-sh4i-yurei-Documents-claude-config"
W1 = f"{PROJECT}/e3a1b2c4-1d5e-4f60-8a71-0b2c3d4e5f61.jsonl"
W2 = f"{PROJECT}/f4b2c3d5-2e6f-4071-9b82-1c3d4e5f6072.jsonl"
W2_SUB = f"{PROJECT}/f4b2c3d5-2e6f-4071-9b82-1c3d4e5f6072/subagents/agent-e5f4a3b2c1d0e9f8.jsonl"
W3 = f"{PROJECT}/a5c3d4e6-3f70-4182-ac93-2d4e5f607183.jsonl"


@pytest.fixture
def claude(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
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


def assert_expected(out, tree, sessions=None):
    for name in ("items.jsonl", "calls.jsonl"):
        found = [
            json.loads(line, object_pairs_hook=list)
            for line in (out / name).read_text().splitlines()
        ]
        wanted = [
            json.loads(line, object_pairs_hook=list)
            for line in (FIXTURES / "expected" / tree / name).read_text().splitlines()
        ]
        if sessions is not None:
            wanted = [row for row in wanted if dict(row)["f"] in sessions]
        assert len(found) == len(wanted)
        for actual, expected in zip(found, wanted):
            assert_value(actual, expected)


def run_window(
    claude, monkeypatch, tmp_path, capsys, tree, options, sessions, unreadable
):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    assert claude.main(["--projects", str(FIXTURES / tree), *options]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"left out {unreadable} session file(s) with no readable start\n"
        if unreadable
        else ""
    )
    assert_expected(out, tree, sessions)


@pytest.mark.parametrize(
    ("options", "sessions"),
    [
        (["--since", "2026-11-20T10:30:00Z"], {W2, W2_SUB, W3}),
        (
            ["--since", "2026-11-20T11:00:00.000Z", "--until", "2026-11-20T11:15:00Z"],
            {W2, W2_SUB},
        ),
        (["--until", "2026-11-20T12:00:00.000Z"], {W1, W2, W2_SUB}),
        (["--since", "2026-11-20T11:30:00Z"], {W3}),
        (["--until", "2027-01-01T00:00:00Z"], {W1, W2, W2_SUB, W3}),
    ],
)
def test_window(claude, monkeypatch, tmp_path, capsys, options, sessions):
    run_window(claude, monkeypatch, tmp_path, capsys, "window", options, sessions, 3)


@pytest.mark.parametrize(
    ("since", "sessions"),
    [
        ("2026-11-20T04:30:00", {W2, W2_SUB, W3}),
        ("0001-01-01T00:00:00+00:00", {W1, W2, W2_SUB, W3}),
    ],
)
def test_local_zone(claude, monkeypatch, tmp_path, capsys, since, sessions):
    monkeypatch.setenv("TZ", "CST6")
    time.tzset()
    try:
        run_window(
            claude,
            monkeypatch,
            tmp_path,
            capsys,
            "window",
            ["--since", since],
            sessions,
            3,
        )
    finally:
        monkeypatch.undo()
        time.tzset()


def test_first_valid_timestamp_after_bad_json(claude, monkeypatch, tmp_path, capsys):
    session = "-tmp-research-check-7f3a/c9e3f4b6-5d7f-4081-ac9d-2e3f4a5b6c73.jsonl"
    run_window(
        claude,
        monkeypatch,
        tmp_path,
        capsys,
        "projects",
        [
            "--since",
            "2026-11-19T00:00:00Z",
            "--until",
            "2026-11-20T00:00:00Z",
        ],
        {session},
        1,
    )


def test_null_timestamp_and_missing_parent(claude, monkeypatch, tmp_path, capsys):
    session = "-var-home-sh4i-yurei-Documents-codex-config/e1a5b6d8-7f91-42a3-8ebf-4a5b6c7d8e95.jsonl"
    run_window(
        claude,
        monkeypatch,
        tmp_path,
        capsys,
        "edge",
        [
            "--since",
            "2026-11-21T07:30:00Z",
        ],
        {session},
        1,
    )


def test_no_window_preserves_full_run(claude, monkeypatch, tmp_path, capsys):
    run_window(claude, monkeypatch, tmp_path, capsys, "window", [], None, 0)


def test_window_without_unreadable_files(claude, monkeypatch, tmp_path, capsys):
    tree = tmp_path / "projects"
    for session in (W1, W2, W3):
        target = tree / session
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / "window" / session, target)
    source_sub = FIXTURES / "window" / W2.removesuffix(".jsonl") / "subagents"
    target_sub = tree / W2.removesuffix(".jsonl") / "subagents"
    shutil.copytree(source_sub, target_sub)
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    assert (
        claude.main(["--projects", str(tree), "--since", "2026-11-20T09:00:00Z"]) == 0
    )
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert_expected(out, "window", {W1, W2, W2_SUB, W3})


@pytest.mark.parametrize(
    ("options", "error"),
    [
        (
            ["--since", "not a date"],
            "argument --since: not an ISO 8601 date or date and time: 'not a date'",
        ),
        (
            ["--until", "2026-13-01"],
            "argument --until: not an ISO 8601 date or date and time: '2026-13-01'",
        ),
        (
            ["--since", "2026-11-20T12:00:00Z", "--until", "2026-11-20T11:00:00Z"],
            "--since must be before --until",
        ),
        (
            ["--since", "2026-11-20T11:00:00Z", "--until", "2026-11-20T11:00:00Z"],
            "--since must be before --until",
        ),
    ],
)
def test_bad_window(claude, monkeypatch, tmp_path, capsys, options, error):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    with pytest.raises(SystemExit) as raised:
        claude.main(options)
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "usage: claude_tokens.py [-h] [--projects FOLDER] [--since WHEN] [--until WHEN]\n"
        f"claude_tokens.py: error: {error}\n"
    )
    assert list(out.iterdir()) == []
