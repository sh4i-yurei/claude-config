from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_always_loaded_testing_rule_covers_build_and_evidence():
    assert (ROOT / "rules/testing.md").is_file()
    rule = (ROOT / "rules/testing.md").read_text()
    prose = " ".join(rule.split())
    assert len(rule.splitlines()) <= 35
    for expected in (
        "Every change ships with its tests",
        "WHEN and THEN",
        "real inputs",
        "fails on an assertion",
        "existing behaviour",
        "kills mutants",
        "decision 11",
        "never weakened to pass",
        "behaviour, not implementation",
        "finished every mutant",
        "current code and tests",
        "cache invalidation",
        "timestamps",
        "no test of behaviour could kill it",
        "only a test pinning an internal detail could kill",
        "_Templates/handoff-codex-build.md",
        "pre-handoff checklist",
        "40_Reference/testing-standard.md",
        "60_Operational_Manual/68_Dev_Workflow/codex-build-loop.md",
    ):
        assert expected in prose


def test_testing_rule_explains_why_it_loads_and_gives_a_concrete_example():
    rule = (ROOT / "rules/testing.md").read_text()
    prose = " ".join(rule.split())
    assert (
        "This loads every session because a build can start outside a handoff, and the "
        "testing bar must still apply."
    ) in prose
    assert (
        "For example, a coverage number can rise while a test never checks the result; "
        "a mutant that survives exposes that gap."
    ) in prose


def test_testing_rule_does_not_repeat_engineering_rule():
    assert (ROOT / "rules/testing.md").is_file()
    testing_lines = set((ROOT / "rules/testing.md").read_text().splitlines())
    engineering_lines = set((ROOT / "rules/engineering.md").read_text().splitlines())
    assert not {line for line in testing_lines & engineering_lines if line.strip()}


def test_project_note_skill_sizes_design_from_inbox_authority():
    skill = (ROOT / "skills/project-note/SKILL.md").read_text()
    assert "## Sizing the design" in skill
    section = skill.split("## Sizing the design", 1)[1].split("\n## ", 1)[0]
    prose = " ".join(section.split())
    assert len(section.splitlines()) <= 20
    for expected in (
        "00_Inbox/README.md",
        "new system or service",
        "authentication, secrets or how data is stored",
        "data migration or a schema change",
        "fix",
        "feature",
        "architecture",
        "at least two options",
        "Codex",
        "critique",
    ):
        assert expected in prose
