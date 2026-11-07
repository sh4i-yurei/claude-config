#!/usr/bin/env python3
"""Check build handoffs before Claude Code writes them."""

import json
import os
from pathlib import Path
import re
import sys


VAULT = Path.home() / "Documents/Second_Brain"
HANDOFFS = Path(
    os.environ.get("HANDOFF_CHECK_ROOT", VAULT / "05_Agents/handoffs")
).resolve()
TEMPLATE = Path(
    os.environ.get(
        "HANDOFF_BUILD_TEMPLATE", VAULT / "_Templates/handoff-codex-build.md"
    )
)
PLACEHOLDER = re.compile(r"(?<!\$)\{\{[\s\S]*?\}\}")
SECTION = re.compile(r"[A-Z][A-Z ]+(?:, [^\n]+)?")
BRANCH = re.compile(r"- Branch: stay on (\S+)\.(?: .*)?")
EVIDENCE = re.compile(r"Evidence:\s*\S")


def request_lines(content):
    """Return the build instructions inside the handoff's Request fence."""
    content = content.replace("\r\n", "\n")
    match = re.search(r"(?m)^## Request\s*\n\s*```text\n([\s\S]*?)\n```", content)
    return match.group(1).splitlines() if match else []


def is_build_handoff(content):
    front = re.match(r"\A---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|\Z)", content)
    return bool(
        front
        and re.search(
            r"(?m)^template:[ \t]*['\"]?handoff-codex-build['\"]?[ \t]*\r?$",
            front.group(1),
        )
    )


def sections_from_template(content):
    return [line for line in request_lines(content) if SECTION.fullmatch(line)]


def section_bullets(lines, section):
    """Return each bullet in a Request section as its first line and its full text.

    A bullet's full text joins its continuation lines, up to the next bullet or
    a blank line. The section ends at the next section heading.
    """
    start = lines.index(section) + 1
    end = next(
        (i for i in range(start, len(lines)) if SECTION.fullmatch(lines[i])),
        len(lines),
    )
    body = lines[start:end]
    starts = [i for i, line in enumerate(body) if line.startswith("- ")]
    bullets = []
    for offset, following in zip(starts, [*starts[1:], len(body)]):
        continuation = []
        for line in body[offset + 1 : following]:
            if not line.strip():
                break
            continuation.append(line.strip())
        bullets.append((body[offset], " ".join([body[offset], *continuation])))
    return bullets


def problems(content, template):
    lines = request_lines(content)
    sections = sections_from_template(template)
    # Placeholder text is not a section or a test-case bullet.
    masked = PLACEHOLDER.sub(lambda match: "\n" * match.group().count("\n"), content)
    masked_lines = request_lines(masked)
    issues = [
        f"Missing section: {section}"
        for section in sections
        if section not in masked_lines
    ]

    branch_lines = [line for line in lines if line.startswith("- Branch:")]
    if not branch_lines or any(
        (match := BRANCH.fullmatch(line)) is None
        or any(c in match.group(1) for c in "{}")
        for line in branch_lines
    ):
        issues.append("Branch line is missing or unfilled")

    issues.extend(
        "Unfilled placeholder: " + re.sub(r"[ \t]*\r?\n[ \t]*", " ", match.group())
        for match in PLACEHOLDER.finditer(content)
    )

    for section in sections:
        if section not in masked_lines:
            continue
        if section == "TEST CASES":
            bullets = section_bullets(masked_lines, section)
            if not bullets:
                issues.append("Handoff has no test cases")
            for first, joined in bullets:
                if not first.startswith("- WHEN ") or ", THEN" not in joined:
                    issues.append(f"Invalid test case: {first[:60]}")
        elif section == "FACTS":
            bullets = section_bullets(masked_lines, section)
            if not bullets:
                issues.append("Handoff has no facts")
            for first, joined in bullets:
                if not EVIDENCE.search(joined):
                    issues.append(f"Fact without evidence: {first[:60]}")
    return issues


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = event.get("tool_input") or {}
    if event.get("tool_name") not in {"Write", "Edit"} or not isinstance(
        tool_input, dict
    ):
        return 0
    raw_path = tool_input.get("file_path")
    if not isinstance(raw_path, str):
        return 0
    try:
        path = Path(raw_path).resolve()
        path.relative_to(HANDOFFS)
    except (OSError, ValueError):
        return 0
    # A target that doesn't exist yet, or can't be read, has no Request on disk.
    try:
        current = path.read_text()
    except (OSError, UnicodeError):
        current = None
    if event["tool_name"] == "Write":
        content = tool_input.get("content")
    elif current is None:
        return 0
    else:
        content = current
        old = tool_input.get("old_string")
        new = tool_input.get("new_string")
        if isinstance(old, str) and isinstance(new, str) and old:
            content = content.replace(
                old, new, -1 if tool_input.get("replace_all") else 1
            )
    if not isinstance(content, str) or not is_build_handoff(content):
        return 0
    # Decision 53: an existing handoff is checked only when its Request changes.
    if current is not None and request_lines(current) == request_lines(content):
        return 0
    try:
        template = TEMPLATE.read_text()
    except (OSError, UnicodeError):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": f"Warning: cannot read template {TEMPLATE}",
                    }
                }
            )
        )
        return 0
    issues = problems(content, template)
    if issues:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "\n".join(issues),
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
