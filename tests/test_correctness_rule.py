from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULE = ROOT / "rules/correctness.md"


def test_correctness_rule_has_required_authority_and_example():
    assert RULE.is_file()
    rule = RULE.read_text()
    prose = " ".join(rule.split())
    assert len(rule.splitlines()) <= 40
    for expected in (
        "This loads every session because the mistake it prevents can happen in any session: acting on what I believe as if I had checked it, and saying both in the same confident voice.",
        "For example, a search limited to `.yml` files missed ten vault reads in eight templates, and the handoff built on it stopped Codex's build.",
        "~/Documents/Second_Brain/10_Projects/Operating model.md",
        "decision 17",
        "Vault system decision 20",
    ):
        assert expected in prose


def test_correctness_rule_states_the_checks_and_response_to_failure():
    assert RULE.is_file()
    prose = " ".join(RULE.read_text().split()).lower()
    for expected in (
        "correct comes before fast",
        "slow is smooth, and smooth is fast",
        "searched without filters",
        "summary",
        "unchecked",
        "only the question",
        "slow down further",
        "the operating model wins",
    ):
        assert expected in prose


def test_correctness_rule_ends_with_questions_before_acting():
    assert RULE.is_file()
    lines = RULE.read_text().splitlines()
    assert "## Before acting" in lines
    checklist = lines[lines.index("## Before acting") + 1 :]
    assert sum(line.startswith("- ") and "?" in line for line in checklist) >= 4


def test_correctness_rule_does_not_repeat_other_rules():
    assert RULE.is_file()
    lines = {line for line in RULE.read_text().splitlines() if line.strip()}
    for name in ("engineering", "testing", "writing-style"):
        other = {
            line
            for line in (ROOT / f"rules/{name}.md").read_text().splitlines()
            if line.strip()
        }
        assert lines.isdisjoint(other)
