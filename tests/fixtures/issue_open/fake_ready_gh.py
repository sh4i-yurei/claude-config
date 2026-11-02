#!/usr/bin/python3
"""Replay issue and project responses for the ready command."""

import json
import os
from pathlib import Path
import sys
import tomllib


args = sys.argv[1:]
root = Path(os.environ["FAKE_GH_FIXTURES"])
state = json.loads(Path(os.environ["FAKE_GH_STATE"]).read_text())
with Path(os.environ["FAKE_GH_CALLS"]).open("a") as out:
    out.write(json.dumps({"args": args, "input": sys.stdin.read()}) + "\n")


def fixture(name):
    return json.loads((root / (name + ".json")).read_text())


if args[:1] == ["api"]:
    endpoint = args[1]
    if endpoint == "graphql":
        if any(
            arg.startswith(
                (
                    "query=",
                    "owner=",
                    "boardOwner=",
                    "name=",
                    "url=",
                    "number=",
                    "cursor=",
                )
            )
            and args[index - 1] not in ("-f", "-F")
            for index, arg in enumerate(args)
        ):
            print("gh: invalid GraphQL field flag", file=sys.stderr)
            sys.exit(1)
        query = next(
            (arg.removeprefix("query=") for arg in args if arg.startswith("query=")), ""
        )
        if (
            not query.startswith("query(")
            or "resource(" not in query
            or "repositoryOwner(" not in query
        ):
            print("gh: invalid GraphQL query", file=sys.stderr)
            sys.exit(1)
        number = next(
            (index for index, arg in enumerate(args) if arg.startswith("number=")), None
        )
        if number is None or args[number - 1] != "-F":
            print("gh: number must be an integer", file=sys.stderr)
            sys.exit(1)
        if state.get("graphql_error"):
            messages = state["graphql_error"]
            if isinstance(messages, str):
                messages = [messages]
            print(
                json.dumps({"errors": [{"message": message} for message in messages]})
            )
            print("gh: " + messages[0], file=sys.stderr)
            sys.exit(1)
        result = state.get("card_response", fixture("card-query"))
        owner = next(
            arg.removeprefix("owner=") for arg in args if arg.startswith("owner=")
        )
        products = tomllib.loads(Path(os.environ["FAKE_GH_WORKFLOW"]).read_text())[
            "products"
        ]
        board_owner = next(
            product["owner"]
            for product in products.values()
            if product["number"] == int(args[number].removeprefix("number="))
        )
        if owner != board_owner:
            result["data"]["repositoryOwner"] = None
        nodes = result["data"]["resource"]["projectItems"]["nodes"]
        if (
            state.get("number") == "1"
            or state.get("missing_board_item")
            or state.get("board_item_without_content")
        ):
            nodes.clear()
        elif state.get("number") == "60":
            nodes[0]["project"]["number"] = 3
        if nodes and not state.get("preserve_nodes"):
            defaults = (
                {"priority": "P1", "size": "Feature", "estimate": 1.5}
                if state.get("number") == "22"
                else {}
            )
            for name, value in {
                **defaults,
                **state.get("board_fields", {}),
            }.items():
                nodes[0][name] = (
                    {"number" if name == "estimate" else "name": value}
                    if value not in (None, "")
                    else None
                )
            for name in ("priority", "size", "estimate"):
                if name not in state.get("board_fields", {}) and name not in defaults:
                    nodes[0][name] = None
    elif endpoint.startswith("repos/sh4i-yurei/claude-config/issues/"):
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
elif args[:2] == ["project", "item-edit"]:
    result = {}
else:
    print("unexpected command " + repr(args), file=sys.stderr)
    sys.exit(1)
print(json.dumps(result))
