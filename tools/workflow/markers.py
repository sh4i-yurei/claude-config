"""Marker formats shared by the nightly issue pipeline."""

import re

SHARED_BEGIN = "<!-- nightly:shared begin -->"
SHARED_END = "<!-- nightly:shared end -->"


def review_marker(issue, round_number):
    if any(type(value) is not int or value < 1 for value in (issue, round_number)):
        raise ValueError
    return f"<!-- nightly:review issue={issue} round={round_number} -->"


def parse_review_marker(line):
    if not isinstance(line, str):
        return None
    match = re.fullmatch(
        r"<!-- nightly:review issue=([1-9][0-9]*) round=([1-9][0-9]*) -->", line
    )
    return (int(match[1]), int(match[2])) if match else None
