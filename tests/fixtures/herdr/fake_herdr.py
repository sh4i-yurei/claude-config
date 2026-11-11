#!/usr/bin/python3
"""Replay a test's ordered herdr responses without contacting herdr."""

import json
import os
from pathlib import Path
import sys
import time


args = sys.argv[1:]
calls = Path(os.environ["FAKE_HERDR_CALLS"])
previous = (
    [json.loads(line) for line in calls.read_text().splitlines()]
    if calls.exists()
    else []
)
scenario = json.loads(Path(os.environ["FAKE_HERDR_SCENARIO"]).read_text())
with calls.open("a") as stream:
    stream.write(json.dumps(args) + "\n")
response = scenario[len(previous)]
time.sleep(response.get("delay", 0))
if args != response["args"]:
    print(f"unexpected herdr call: {args!r}", file=sys.stderr)
    sys.exit(1)
sys.stdout.write(response.get("stdout", ""))
sys.stderr.write(response.get("stderr", ""))
sys.exit(response.get("status", 0))
