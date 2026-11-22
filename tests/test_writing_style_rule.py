from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULE = ROOT / "rules/writing-style.md"


def test_github_writing_rule_and_self_check():
    lines = RULE.read_text().splitlines()
    rule_8_lines = []
    collecting = False
    for line in lines:
        if line.startswith("8. "):
            collecting = True
        if collecting and not line:
            break
        if collecting:
            rule_8_lines.append(line.strip())

    assert rule_8_lines

    rule_7_start = next(i for i, line in enumerate(lines) if line.startswith("7. "))
    rule_7_end = next(i for i in range(rule_7_start, len(lines)) if not lines[i])
    rule_8_start = lines.index(rule_8_lines[0])
    structure_start = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("Structure is not the problem")
    )
    assert rule_7_end < rule_8_start < structure_start
    assert " ".join(rule_8_lines) == (
        "8. **When writing on GitHub, describe the work.** Commit messages, pull requests, "
        "issues and review comments describe the change, the problem and the reason. They never "
        "refer to Mark in the third person or to any agent or AI, and identifiers in the code "
        'stay. Full rule in the writing directive\'s "Writing on GitHub" section.'
    )

    check_start = lines.index("## Before sending anything")
    full_version_start = lines.index("## The full version")
    assert (
        "- If this goes on GitHub: does it describe the work, with no Mark in the third person "
        "and no agent or AI?"
    ) in lines[check_start:full_version_start]
