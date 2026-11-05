#!/usr/bin/python3
"""Replay issue and project responses for the ready command."""

import json
import os
from pathlib import Path
import sys
import tomllib
from urllib.parse import parse_qs, urlsplit


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
        linked_query = "query($owner: String!, $name: String!, $number: Int!, $cursor: String) { repository(owner: $owner, name: $name) { issue(number: $number) { linkedBranches(first: 100, after: $cursor) { pageInfo { hasNextPage endCursor } nodes { ref { name } } } } } }"
        if query == linked_query:
            fields = {
                arg.split("=", 1)[0]: (arg.split("=", 1)[1], args[index - 1])
                for index, arg in enumerate(args)
                if "=" in arg
            }
            if (
                fields.get("owner") != ("sh4i-yurei", "-f")
                or fields.get("name") != ("claude-config", "-f")
                or fields.get("number", (None, None))[1] != "-F"
                or ("cursor" in fields and fields["cursor"][1] != "-f")
            ):
                print("gh: invalid linked branches variables", file=sys.stderr)
                sys.exit(1)
            if state.get("linked_graphql_error"):
                message = state["linked_graphql_error"]
                print(json.dumps({"errors": [{"message": message}]}))
                print("gh: " + message, file=sys.stderr)
                sys.exit(1)
            issue_number = fields["number"][0]
            answer = state.get("linked_branches", {}).get(
                issue_number, fixture("linked-branches-63")
            )
            nodes = answer["data"]["repository"]["issue"]["linkedBranches"]["nodes"]
            start = int(fields["cursor"][0]) if "cursor" in fields else 0
            page = answer["data"]["repository"]["issue"]["linkedBranches"]
            page["nodes"] = nodes[start : start + 100]
            page["pageInfo"] = {
                "hasNextPage": start + 100 < len(nodes),
                "endCursor": str(min(start + 100, len(nodes))) if nodes else None,
            }
            print(json.dumps(answer))
            sys.exit(0)
        closing_query = "query($owner: String!, $name: String!, $number: Int!, $cursor: String) { repository(owner: $owner, name: $name) { issue(number: $number) { closedByPullRequestsReferences(first: 100, after: $cursor, includeClosedPrs: false) { pageInfo { hasNextPage endCursor } nodes { number state headRefName repository { nameWithOwner } } } } } }"
        if query == closing_query:
            fields = {
                arg.split("=", 1)[0]: (arg.split("=", 1)[1], args[index - 1])
                for index, arg in enumerate(args)
                if "=" in arg
            }
            if (
                set(fields) - {"query", "owner", "name", "number", "cursor"}
                or fields.get("owner") != ("sh4i-yurei", "-f")
                or fields.get("name") != ("claude-config", "-f")
                or fields.get("number", (None, None))[1] != "-F"
                or ("cursor" in fields and fields["cursor"][1] != "-f")
            ):
                print("gh: invalid closing pull variables", file=sys.stderr)
                sys.exit(1)
            if state.get("closing_graphql_error"):
                message = state["closing_graphql_error"]
                print(json.dumps({"errors": [{"message": message}]}))
                print("gh: " + message, file=sys.stderr)
                sys.exit(1)
            issue_number = fields["number"][0]
            answer = state.get("closing_pulls", {}).get(
                issue_number, fixture("closing-pulls-108")
            )
            page = answer["data"]["repository"]["issue"][
                "closedByPullRequestsReferences"
            ]
            nodes = page["nodes"]
            start = int(fields["cursor"][0]) if "cursor" in fields else 0
            page["nodes"] = nodes[start : start + 100]
            page["pageInfo"] = {
                "hasNextPage": start + 100 < len(nodes),
                "endCursor": str(min(start + 100, len(nodes))) if nodes else None,
            }
            print(json.dumps(answer))
            sys.exit(0)
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
        url = next(arg.removeprefix("url=") for arg in args if arg.startswith("url="))
        card_error = state.get("card_errors_by_url", {}).get(url)
        if card_error or state.get("graphql_error"):
            messages = card_error or state["graphql_error"]
            if isinstance(messages, str):
                messages = [messages]
            print(
                json.dumps({"errors": [{"message": message} for message in messages]})
            )
            print("gh: " + messages[0], file=sys.stderr)
            sys.exit(1)
        result = state.get("cards_by_url", {}).get(
            url, state.get("card_response", fixture("card-query"))
        )
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
    elif endpoint.startswith("repos/sh4i-yurei/claude-config/pulls?"):
        query = parse_qs(urlsplit(endpoint).query)
        if query.get("state") != ["open"] or len(query.get("head", [])) != 1:
            print("unexpected API " + endpoint, file=sys.stderr)
            sys.exit(1)
        result = [
            pull
            for pull in state.get("pulls_by_head", {}).get(query["head"][0], [])
            if pull["state"] == "open" and pull["head"]["label"] == query["head"][0]
        ][:30]
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
