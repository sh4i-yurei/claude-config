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
        "verification gate",
        "fail without the change",
        "read-only pre-flight",
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


def test_project_note_skill_lists_ten_sections_with_facts():
    skill = (ROOT / "skills/project-note/SKILL.md").read_text()
    section = skill.split("## Creating one", 1)[1].split("\n## ", 1)[0]
    prose = " ".join(section.split())
    assert "Ten sections:" in prose
    assert "**How it's built**, **Facts**, **Decisions**" in prose
    assert "fills all ten" in prose
    assert "Nine sections" not in prose
    assert "fills all nine" not in prose


def test_project_note_skill_describes_facts_and_their_place():
    skill = (ROOT / "skills/project-note/SKILL.md").read_text()
    section = skill.split("## Creating one", 1)[1].split(
        "\n## Decisions are numbered", 1
    )[0]
    paragraphs = [" ".join(part.split()) for part in section.split("\n\n")]
    facts = next(
        (part for part in paragraphs if part.startswith("**Facts** holds")), None
    )
    assert facts == (
        "**Facts** holds every claim a decision or a build depends on, about a real system, tool, "
        "service, machine, file or his own code, each with the evidence that proved it: a disposable "
        "test with its command and output, a source read with the file and line, a documentation "
        "lookup with its archive path, or a read-only check on the machine with the line it printed "
        "and the date. A decision rests only on facts listed there, and a claim that is still unchecked "
        "keeps its item out of Next. Build handoffs quote the entries their test cases depend on. "
        "The rule is Workflow upkeep decision 47, and the steps are the gate in `codex-build-loop`."
    )
    assert (
        paragraphs.index(facts)
        == next(
            i
            for i, part in enumerate(paragraphs)
            if part.startswith("**How it's built** carries")
        )
        + 1
    )


def test_vault_file_skill_names_ten_project_sections():
    prose = " ".join((ROOT / "skills/vault-file/SKILL.md").read_text().split())
    assert "has ten sections and specific rules" in prose
    assert "nine sections" not in prose
