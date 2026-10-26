#!/usr/bin/python3
"""Replay captured GitHub responses and record every gh call."""

import json
import os
from pathlib import Path
import sys


args = sys.argv[1:]
fixtures = Path(os.environ["FAKE_GH_FIXTURES"])
calls = Path(os.environ["FAKE_GH_CALLS"])
with calls.open("a") as out:
    out.write(json.dumps({"args": args, "input": sys.stdin.read()}) + "\n")
state_file = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(state_file.read_text())
failure = state.get("failure")
if failure and args[: len(failure["prefix"])] == failure["prefix"]:
    print(failure["message"], file=sys.stderr)
    sys.exit(1)


def fixture(name):
    return json.loads((fixtures / (name + ".json")).read_text())


result = None
if args[:1] == ["api"]:
    endpoint = args[1].split("?", 1)[0]
    method = args[args.index("--method") + 1] if "--method" in args else "GET"
    if method == "GET":
        if endpoint.endswith("/contents/.github/ISSUE_TEMPLATE"):
            if endpoint.startswith("repos/missing-owner/.github/"):
                print("HTTP 404: Not Found", file=sys.stderr)
                sys.exit(1)
            if (
                "/.github/contents/" not in endpoint
                and "keepbreathing-infra" not in endpoint
            ):
                print("HTTP 404: Not Found", file=sys.stderr)
                sys.exit(1)
            result = fixture(
                "infra-templates-list"
                if "keepbreathing-infra" in endpoint
                else "forms-list"
            )
        elif "/contents/.github/ISSUE_TEMPLATE/" in endpoint:
            name = endpoint.rsplit("/", 1)[1]
            result = fixture(
                ("infra-" if "keepbreathing-infra" in endpoint else "form-") + name
            )
        elif endpoint.endswith("/milestones"):
            result = fixture("milestones")
        elif endpoint.endswith("/labels"):
            result = fixture("labels")
        elif endpoint.endswith("/issues/20"):
            result = fixture("issue-20")
        elif endpoint.endswith("/issues/22"):
            result = fixture("issue-22")
        elif "/issues/" in endpoint:
            print("HTTP 404: Not Found", file=sys.stderr)
            sys.exit(1)
        else:
            print("unexpected GET " + endpoint, file=sys.stderr)
            sys.exit(1)
    elif method == "POST" and endpoint.endswith("/issues"):
        repo = endpoint.removeprefix("repos/").removesuffix("/issues")
        result = {
            "id": 123456789,
            "number": 99,
            "html_url": f"https://github.com/{repo}/issues/99",
        }
    elif method == "POST" and (
        endpoint.endswith("/sub_issues") or endpoint.endswith("/blocked_by")
    ):
        result = {}
    else:
        print("unexpected API " + repr(args), file=sys.stderr)
        sys.exit(1)
elif args[:2] == ["project", "item-list"]:
    result = fixture("project-items")
elif args[:2] == ["project", "field-list"]:
    result = fixture("project-fields")
elif args[:2] == ["project", "view"]:
    result = fixture("project-view")
elif args[:2] == ["project", "item-add"]:
    result = {"id": "PVTI_NEW"}
elif args[:2] == ["project", "item-edit"]:
    if "--format" not in args:
        sys.exit(0)
    result = {}
elif args[:2] == ["issue", "list"]:
    result = fixture("open-issues")
else:
    print("unexpected command " + repr(args), file=sys.stderr)
    sys.exit(1)
state_file.write_text(json.dumps(state))
print(json.dumps(result))
