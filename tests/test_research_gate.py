"""In-process behavior checks for the research gate's PreToolUse decision."""

import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest


HOOK = Path(__file__).resolve().parents[1] / "hooks/research-gate.py"
SPEC = importlib.util.spec_from_file_location("hooks.research-gate", HOOK)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

SUBAGENT_REASON = (
    "Subagents must not fetch the web. Parallel agents each searching is the pattern that got "
    "this address flagged. Do the research in the main session, one fetch at a time."
)
SEARCHES = (
    ("mcp__claude_ai_Firecrawl__firecrawl_search", {"query": "x"}),
    ("mcp__firecrawl__firecrawl_search", {"query": "x"}),
    ("mcp__claude_ai_Firecrawl__firecrawl_developer_search", {"query": "x"}),
    ("mcp__claude_ai_Firecrawl__firecrawl_gov_search", {"query": "x"}),
    ("mcp__claude_ai_Firecrawl__firecrawl_research_search_papers", {"query": "x"}),
    ("mcp__claude_ai_Firecrawl__firecrawl_agent", {"prompt": "x"}),
)


@pytest.fixture
def gate(tmp_path, monkeypatch, capsys):
    state_file = tmp_path / "research-state.json"
    known_apis = tmp_path / "known-apis.md"
    monkeypatch.setattr(GATE, "STATE_FILE", state_file)
    monkeypatch.setattr(GATE, "KNOWN_APIS", known_apis)

    def call(payload, now=20000):
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
        monkeypatch.setattr(GATE.time, "time", lambda: now)
        assert GATE.main() == 0
        printed = capsys.readouterr().out
        if not printed:
            return None
        return json.loads(printed)["hookSpecificOutput"]

    return call, state_file, known_apis


def decision(reason):
    return {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }


def webfetch(**identity):
    return {
        "tool_name": "WebFetch",
        "tool_input": {"url": "https://example.com/a"},
        **identity,
    }


def site_state(path, **fields):
    path.write_text(json.dumps({"domains": {"example.com": fields}}))


@pytest.mark.parametrize("name,tool_input", SEARCHES)
def test_subagent_searches_are_refused(gate, name, tool_input):
    call, state, _ = gate
    assert call(
        {"tool_name": name, "tool_input": tool_input, "agent_id": "a1"}
    ) == decision(SUBAGENT_REASON)
    assert not state.exists()


@pytest.mark.parametrize("name,tool_input", SEARCHES)
def test_main_session_searches_leave_state_alone(gate, name, tool_input):
    call, state, _ = gate
    assert call({"tool_name": name, "tool_input": tool_input}) is None
    assert not state.exists()


@pytest.mark.parametrize(
    "name,tool_input",
    (
        ("mcp__claude_ai_Firecrawl__firecrawl_agent_status", {"id": "x"}),
        ("mcp__claude_ai_Firecrawl__firecrawl_search_feedback", {"searchId": "x"}),
        ("mcp__claude_ai_Firecrawl__firecrawl_research_read_paper", {"id": "x"}),
    ),
)
def test_other_firecrawl_tools_are_allowed(gate, name, tool_input):
    call, state, _ = gate
    assert call({"tool_name": name, "tool_input": tool_input, "agent_id": "a1"}) is None
    assert not state.exists()


@pytest.mark.parametrize(
    "payload",
    (
        "not JSON",
        {"tool_name": "Bash", "tool_input": {"command": "true"}},
        {"tool_input": {"url": "https://example.com/"}},
        {"tool_name": "WebFetch", "tool_input": {"url": "file:///a"}},
    ),
)
def test_unhandled_inputs_are_allowed(gate, payload):
    call, state, _ = gate
    assert call(payload) is None
    assert not state.exists()


@pytest.mark.parametrize(
    "tool_name", ("WebFetch", "mcp__claude_ai_Firecrawl__firecrawl_scrape")
)
@pytest.mark.parametrize(
    "identity",
    (
        {"is_subagent": True},
        {"subagent": "x"},
        {"agent_id": "a1"},
        {"parent_session_id": "p"},
    ),
)
def test_subagent_fetch_is_refused(gate, tool_name, identity):
    call, state, _ = gate
    assert call(
        {
            "tool_name": tool_name,
            "tool_input": {"url": "https://example.com/"},
            **identity,
        }
    ) == decision(SUBAGENT_REASON)
    assert not state.exists()


@pytest.mark.parametrize("identity", ({"is_subagent": False}, {"agent_id": ""}))
def test_false_subagent_identity_allows_fetch(gate, identity):
    call, state, _ = gate
    assert call(webfetch(**identity)) is None
    assert json.loads(state.read_text()) == {
        "domains": {"example.com": {"pending_since": 20000}}
    }


def test_in_flight_boundary(gate):
    call, state, _ = gate
    assert call(webfetch(), now=1000) is None
    assert json.loads(state.read_text()) == {
        "domains": {"example.com": {"pending_since": 1000}}
    }
    assert call(webfetch(), now=1299) == decision(
        "A fetch to example.com is already in flight. One connection to a site at a time. "
        "Wait for it to finish."
    )
    assert call(webfetch(), now=1300) is None
    assert json.loads(state.read_text()) == {
        "domains": {"example.com": {"pending_since": 1300}}
    }


@pytest.mark.parametrize(
    "duration,gap,reason",
    (
        (
            50,
            1,
            "Too soon for example.com. The last fetch there took 50ms, so the polite gap "
            "is 1s and only 0s have passed. Fetch a different site meanwhile, or wait. "
            "Pacing is per site, not overall.",
        ),
        (
            3000,
            30,
            "Too soon for example.com. The last fetch there took 3000ms, so the polite gap "
            "is 30s and only 29s have passed. Fetch a different site meanwhile, or wait. "
            "Pacing is per site, not overall.",
        ),
        (
            20000,
            120,
            "Too soon for example.com. The last fetch there took 20000ms, so the polite gap "
            "is 120s and only 119s have passed. Fetch a different site meanwhile, or wait. "
            "Pacing is per site, not overall.",
        ),
        (
            None,
            1,
            "Too soon for example.com. The last fetch there took 0ms, so the polite gap "
            "is 1s and only 0s have passed. Fetch a different site meanwhile, or wait. "
            "Pacing is per site, not overall.",
        ),
    ),
)
def test_polite_gap_boundary(gate, duration, gap, reason):
    call, state, _ = gate
    fields = {"last_fetch": 1000, "consecutive_errors": 0, "count_today": 0}
    if duration is not None:
        fields["last_duration_ms"] = duration
    site_state(state, **fields)
    assert call(webfetch(), now=1000 + gap - 1) == decision(reason)
    assert call(webfetch(), now=1000 + gap) is None


def test_fractional_gap_is_enforced(gate):
    call, state, _ = gate
    site_state(state, last_fetch=1000, last_duration_ms=3000)
    assert call(webfetch(), now=1029.99) == decision(
        "Too soon for example.com. The last fetch there took 3000ms, so the polite gap "
        "is 30s and only 30s have passed. Fetch a different site meanwhile, or wait. "
        "Pacing is per site, not overall."
    )


@pytest.mark.parametrize(
    "errors,age,reason",
    (
        (
            5,
            1800,
            "example.com has failed 5 times in a row. Standard practice is to leave a site "
            "alone for hours after that, not minutes. About 3.5h left. Find the material "
            "somewhere else.",
        ),
        (
            5,
            14399,
            "example.com has failed 5 times in a row. Standard practice is to leave a site "
            "alone for hours after that, not minutes. About 0.0h left. Find the material "
            "somewhere else.",
        ),
        (
            5,
            1979,
            "example.com has failed 5 times in a row. Standard practice is to leave a site "
            "alone for hours after that, not minutes. About 3.5h left. Find the material "
            "somewhere else.",
        ),
        (5, 14400, None),
        (4, 1800, None),
    ),
)
def test_error_streak_boundary(gate, errors, age, reason):
    call, state, _ = gate
    site_state(state, consecutive_errors=errors, last_error=20000 - age, count_today=0)
    expected = decision(reason) if reason else None
    assert call(webfetch()) == expected


def test_missing_last_error_uses_zero(gate):
    call, state, _ = gate
    site_state(state, consecutive_errors=5)
    assert call(webfetch(), now=14400) is None


@pytest.mark.parametrize("count,reason", ((300, True), (299, False)))
def test_daily_count_boundary(gate, count, reason):
    call, state, _ = gate
    site_state(state, consecutive_errors=0, count_today=count)
    expected = (
        decision(
            "example.com has been fetched 300 times today. That is a loop, not research. "
            "Stop and work out what is repeating."
        )
        if reason
        else None
    )
    assert call(webfetch()) == expected


def test_no_last_fetch_has_no_gap(gate):
    call, state, _ = gate
    assert call(webfetch(), now=1) is None
    assert json.loads(state.read_text()) == {
        "domains": {"example.com": {"pending_since": 1}}
    }


def test_known_api_cooldown_boundary(gate):
    call, state, known_apis = gate
    known_apis.write_text("| `example.com` | Use the public API |\n")
    assert call(webfetch(), now=1000) is None
    assert json.loads(state.read_text()) == {
        "domains": {"example.com": {"known_api_used_at": 1000, "pending_since": 1000}}
    }
    site_state(state, known_api_used_at=1000, count_today=0, consecutive_errors=0)
    assert call(webfetch(), now=22599) == decision(
        "example.com has a cheaper route and you have already fetched it directly once "
        "recently. Use it instead: Use the public API. See known-apis.md in the research skill."
    )
    assert call(webfetch(), now=22600) is None
    assert (
        json.loads(state.read_text())["domains"]["example.com"]["known_api_used_at"]
        == 22600
    )


@pytest.mark.parametrize("content", (None, "| `example.com` |\n"))
def test_missing_or_short_known_api_row_does_not_mark_site(gate, content):
    call, state, known_apis = gate
    if content is not None:
        known_apis.write_text(content)
    assert call(webfetch()) is None
    assert json.loads(state.read_text()) == {
        "domains": {"example.com": {"pending_since": 20000}}
    }
