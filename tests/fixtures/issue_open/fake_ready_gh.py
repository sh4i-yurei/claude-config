#!/usr/bin/python3
"""Replay issue and project responses for the ready command."""

import json
import os
from pathlib import Path
import sys


args = sys.argv[1:]
root = Path(os.environ["FAKE_GH_FIXTURES"])
state = json.loads(Path(os.environ["FAKE_GH_STATE"]).read_text())
with Path(os.environ["FAKE_GH_CALLS"]).open("a") as out:
    out.write(json.dumps({"args": args, "input": sys.stdin.read()}) + "\n")


def fixture(name):
    return json.loads((root / (name + ".json")).read_text())


if args[:1] == ["api"]:
    endpoint = args[1]
    if endpoint.startswith("repos/sh4i-yurei/claude-config/issues/"):
        number = endpoint.split("/")[4]
        if endpoint.endswith("/parent"):
            if "parent_response" in state:
                result = state["parent_response"]
            else:
                print(
                    state.get("parent_error", "gh: No parent issue found (HTTP 404)"),
                    file=sys.stderr,
                )
                sys.exit(1)
        elif endpoint.endswith("/dependencies/blocked_by"):
            result = state.get("blocked_by", fixture(f"ready-issue-{number}-blocked"))
        else:
            result = fixture(
                f"ready-issue-{number}" if number != "1" else "ready-issue-23"
            )
            if number == "1":
                result["html_url"] = (
                    "https://github.com/sh4i-yurei/claude-config/issues/1"
                )
            result.update(state.get("issue_fields", {}))
            if state.get("issue_without_labels"):
                result.pop("labels")
    elif endpoint.startswith("repos/sh4i-yurei/keepbreathing-infra/issues/60"):
        if endpoint.endswith("/parent"):
            result = fixture("ready-infra-60-parent")
        elif endpoint.endswith("/dependencies/blocked_by"):
            result = fixture("ready-infra-60-blocked")
        else:
            result = fixture("ready-infra-60")
    elif endpoint.endswith("/contents/.github/ISSUE_TEMPLATE"):
        if "keepbreathing-infra" in endpoint:
            result = fixture("infra-templates-list")
        elif "/.github/contents/" in endpoint:
            result = fixture("forms-list")
        else:
            print("HTTP 404: Not Found", file=sys.stderr)
            sys.exit(1)
    elif endpoint.startswith(
        "repos/sh4i-yurei/.github/contents/.github/ISSUE_TEMPLATE/"
    ):
        filename = endpoint.rsplit("/", 1)[1]
        result = state.get("form_responses", {}).get(
            filename, fixture("form-" + filename)
        )
    else:
        print("unexpected API " + endpoint, file=sys.stderr)
        sys.exit(1)
elif args[:2] == ["project", "view"]:
    result = fixture("project-view")
elif args[:2] == ["project", "field-list"]:
    result = fixture("project-fields")
elif args[:2] == ["project", "item-list"]:
    result = fixture("ready-board-items")
    for item in result["items"]:
        if (
            item.get("content", {})
            .get("url", "")
            .endswith("/issues/" + state.get("number", ""))
        ):
            item.update(state.get("board_fields", {}))
            if state.get("board_item_without_content"):
                item.pop("content")
    if state.get("missing_board_item"):
        result["items"] = [
            item
            for item in result["items"]
            if item.get("content", {}).get("url", "")
            != "https://github.com/sh4i-yurei/claude-config/issues/" + state["number"]
        ]
elif args[:2] == ["project", "item-edit"]:
    result = {}
else:
    print("unexpected command " + repr(args), file=sys.stderr)
    sys.exit(1)
print(json.dumps(result))
