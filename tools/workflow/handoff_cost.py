"""Count the Codex sessions that followed one handoff, with their steps and tokens."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

REQUEST = re.compile(r"[Ff]ollow the Request in (\S+\.md)")


@dataclass
class Cost:
    """Model calls and their summed tokens, from token_usage_record entries."""

    steps: int = 0
    input: int = 0
    cached: int = 0
    output: int = 0

    def record(self, usage):
        self.steps += 1
        self.input += usage["input_tokens"]
        self.cached += usage["cached_input_tokens"]
        self.output += usage["output_tokens"]

    def add(self, other):
        self.steps += other.steps
        self.input += other.input
        self.cached += other.cached
        self.output += other.output

    def describe(self):
        return (
            f"{self.steps} steps, {self.input} input tokens ({self.cached} cached), "
            f"{self.output} output tokens"
        )


def entries(path):
    """Yield each JSON line of a session file.

    A running session's last line can be partial, and it can end inside a
    multi-byte character, so a line that fails to decode or parse is skipped.
    """
    with path.open("rb") as lines:
        for line in lines:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def requested_name(entry):
    """Return the file name a user message's request names, or None."""
    if entry["type"] != "response_item":
        return None
    message = entry["payload"]
    if message["type"] != "message" or message["role"] != "user":
        return None
    for item in message["content"]:
        match = REQUEST.search(item["text"])
        if match:
            return Path(match.group(1)).name
    return None


def read_session(path):
    """Return the file name a session's first request names, and its recorded cost."""
    followed = None
    cost = Cost()
    for entry in entries(path):
        if entry["type"] == "token_usage_record":
            cost.record(entry["payload"]["usage"])
        elif followed is None:
            followed = requested_name(entry)
    return followed, cost


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff")
    parser.add_argument(
        "--sessions", type=Path, default=Path.home() / ".codex/sessions"
    )
    arguments = parser.parse_args(argv)
    name = Path(arguments.handoff).name
    total = Cost()
    count = 0
    for path in sorted(arguments.sessions.rglob("rollout-*.jsonl")):
        followed, cost = read_session(path)
        if followed != name:
            continue
        print(f"{path.name}: {cost.describe()}")
        total.add(cost)
        count += 1
    if not count:
        print(f"no Codex session followed {name}", file=sys.stderr)
        return 1
    print(f"{count} sessions, {total.describe()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
