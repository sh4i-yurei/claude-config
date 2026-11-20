#!/usr/bin/python3
"""Stand-in for the Bitwarden search used by vault reader tests."""

import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse


with Path(os.environ["FAKE_BW_CALLS"]).open("a") as calls:
    calls.write(
        json.dumps(
            {
                "args": sys.argv[1:],
                "session": os.environ.get("BW_SESSION"),
                "nointeraction": os.environ.get("BW_NOINTERACTION"),
            }
        )
        + "\n"
    )

if not os.environ.get("BW_SESSION"):
    print("Vault is locked.", file=sys.stderr)
    raise SystemExit(1)
if len(sys.argv) != 5 or sys.argv[1:4] != ["list", "items", "--search"]:
    print("Not found.", file=sys.stderr)
    raise SystemExit(1)

terms = sys.argv[4].lower().split()
items = json.loads(Path(os.environ["FAKE_BW_ITEMS"]).read_text())


def searchable(item):
    login = item.get("login") or {}
    hosts = [
        urlparse(uri.get("uri") or "").hostname or "" for uri in login.get("uris") or []
    ]
    return [
        str(item.get("name") or ""),
        str(login.get("username") or ""),
        str(item.get("notes") or ""),
        *hosts,
    ]


kept = [
    item
    for item in items
    if all(any(term in value.lower() for value in searchable(item)) for term in terms)
]
mode = os.environ.get("FAKE_BW_MODE")
if mode == "stderr-secret":
    print("dummy-pass", file=sys.stderr)
if mode == "no-fields":
    for item in kept:
        item.pop("fields", None)
if mode == "null-fields":
    for item in kept:
        item["fields"] = None
if mode == "junk":
    kept = ["x", 7, *kept]
if mode == "not-json":
    print("not json")
elif mode == "object":
    print("{}")
else:
    print(json.dumps(kept))
if mode == "failed-json":
    raise SystemExit(1)
