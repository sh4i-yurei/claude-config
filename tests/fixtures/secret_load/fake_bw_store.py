#!/usr/bin/python3
"""Stateful Bitwarden CLI double for secret-load."""

import base64
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse


def record(path, value):
    with Path(os.environ[path]).open("a") as output:
        output.write(json.dumps(value) + "\n")


def read(name):
    return json.loads(Path(os.environ[name]).read_text())


def write(name, items):
    Path(os.environ[name]).write_text(json.dumps(items))


def later(value):
    date = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ") + timedelta(seconds=1)
    return date.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


args = sys.argv[1:]
mode = os.environ.get("FAKE_BW_MODE")
calls = Path(os.environ["FAKE_BW_CALLS"])
record(
    "FAKE_BW_CALLS",
    {
        "args": args,
        "session": os.environ.get("BW_SESSION"),
        "nointeraction": os.environ.get("BW_NOINTERACTION"),
    },
)
if args == ["sync"]:
    if mode == "sync-fails" or (
        mode == "late-sync-fails" and Path(os.environ["FAKE_BW_EDITS"]).exists()
    ):
        print("dummy-session", file=sys.stderr)
        raise SystemExit(1)
    write("FAKE_BW_LOCAL", read("FAKE_BW_SERVER"))
    print("Syncing complete.")
    raise SystemExit(0)

if not os.environ.get("BW_SESSION"):
    print("Vault is locked.", file=sys.stderr)
    raise SystemExit(1)

if len(args) == 4 and args[:3] == ["list", "items", "--search"]:
    entries = [json.loads(line) for line in calls.read_text().splitlines()]
    if (
        mode == "concurrent"
        and sum(call["args"][:1] == ["list"] for call in entries) == 1
    ):
        server = read("FAKE_BW_SERVER")
        for item in server:
            item["revisionDate"] = later(item["revisionDate"])
        write("FAKE_BW_SERVER", server)
    terms = args[3].lower().split()

    def searchable(item):
        login = item.get("login") or {}
        hosts = [
            urlparse(uri.get("uri") or "").hostname or ""
            for uri in login.get("uris") or []
        ]
        return [
            str(item.get("name") or ""),
            str(login.get("username") or ""),
            str(item.get("notes") or ""),
            *hosts,
        ]

    kept = [
        item
        for item in read("FAKE_BW_LOCAL")
        if all(any(term in text.lower() for text in searchable(item)) for term in terms)
    ]
    if Path(os.environ["FAKE_BW_EDITS"]).exists():
        if mode == "readback-other-id":
            for item in kept:
                item["id"] = "99999999-9999-4999-8999-999999999999"
        if mode == "readback-duplicate":
            for item in kept:
                item["fields"] = [
                    field for field in item.get("fields") or [] for _ in range(2)
                ]
    print(json.dumps(kept))
    if (
        mode in ("vanish", "unmark")
        and sum(call["args"][:1] == ["list"] for call in entries) == 1
    ):
        Path(
            os.environ["FAKE_BW_VANISH" if mode == "vanish" else "FAKE_BW_UNMARK"]
        ).unlink()
    raise SystemExit(0)

if len(args) == 3 and args[:2] == ["edit", "item"]:
    item = json.loads(base64.b64decode(sys.stdin.buffer.read()))
    record("FAKE_BW_EDITS", item)
    if mode == "edit-garbage":
        sys.stderr.buffer.write(b"\xff\xfe not text")
        raise SystemExit(1)
    if mode == "edit-fails":
        print("Error: dummy-session", file=sys.stderr)
        raise SystemExit(1)
    server = read("FAKE_BW_SERVER")
    local = read("FAKE_BW_LOCAL")
    old = next((entry for entry in server if entry["id"] == args[2]), None)
    copy = next((entry for entry in local if entry["id"] == args[2]), None)
    if old is None:
        print("Not found.", file=sys.stderr)
        raise SystemExit(1)
    if copy is None or old["revisionDate"] != copy["revisionDate"]:
        print(
            "The client copy of this cipher is out of date. Resync the client and try again.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    item["revisionDate"] = later(old["revisionDate"])
    local[local.index(copy)] = item
    write("FAKE_BW_LOCAL", local)
    server_item = json.loads(json.dumps(item))
    if mode == "readback-differs":
        for field in server_item.get("fields") or []:
            field["value"] = "dummy-vw-tampered-9999"
        if isinstance(server_item.get("login"), dict):
            server_item["login"]["password"] = "dummy-vw-tampered-9999"
    server[server.index(old)] = server_item
    write("FAKE_BW_SERVER", server)
    print(json.dumps(item))
    raise SystemExit(0)

print("Not found.", file=sys.stderr)
raise SystemExit(1)
