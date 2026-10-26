"""Open a checked GitHub issue and place open repository issues on its board."""

import argparse
import base64
import json
from pathlib import Path
import subprocess
import tomllib

from config import ConfigError, load, load_boards


class IssueError(Exception):
    """The input or a GitHub response cannot be used."""


def gh(args, payload=None):
    result = subprocess.run(
        ["gh", *args],
        input=json.dumps(payload) if payload is not None else "",
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise IssueError(
            result.stderr.strip()
            or result.stdout.strip()
            or f"gh exit {result.returncode}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise IssueError(f"gh returned invalid JSON for {' '.join(args)}") from error


def api(endpoint, payload=None):
    args = ["api", endpoint]
    if payload is not None:
        args += ["--method", "POST", "--input", "-"]
    return gh(args, payload)


def read_input(path):
    try:
        with Path(path).open("rb") as source:
            return tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise IssueError(f"{path}: {error}") from error


def form_files(repo):
    try:
        files = api(f"repos/{repo}/contents/.github/ISSUE_TEMPLATE")
    except IssueError as error:
        if "404" not in str(error):
            raise
        files = []
    markdown = sorted(
        item["name"] for item in files if item["name"].lower().endswith(".md")
    )
    if markdown:
        raise IssueError(
            f"{repo}: own issue templates are not forms: {', '.join(markdown)}"
        )
    forms = {
        Path(item["name"]).stem: item
        for item in files
        if item["name"].lower().endswith((".yml", ".yaml"))
        and item["name"] not in ("config.yml", "config.yaml")
    }
    if forms:
        return repo, forms
    fallback = f"{repo.split('/', 1)[0]}/.github"
    try:
        files = api(f"repos/{fallback}/contents/.github/ISSUE_TEMPLATE")
    except IssueError as error:
        if "404" in str(error):
            raise IssueError(
                f"{repo}: no issue forms in its own templates or {fallback}"
            ) from error
        raise
    forms = {
        Path(item["name"]).stem: item
        for item in files
        if item["name"].lower().endswith((".yml", ".yaml"))
        and item["name"] not in ("config.yml", "config.yaml")
    }
    if not forms:
        raise IssueError(f"{repo}: no issue forms in its own templates or {fallback}")
    return fallback, forms


def read_form(repo, filename):
    raw = api(f"repos/{repo}/contents/.github/ISSUE_TEMPLATE/{filename}")
    try:
        import yaml
    except ImportError as error:
        raise IssueError(
            "PyYAML is required; install it in dev with /usr/bin/python3 -m pip install --user PyYAML"
        ) from error
    try:
        form = yaml.safe_load(base64.b64decode(raw["content"]))
    except (KeyError, ValueError, yaml.YAMLError) as error:
        raise IssueError(f"{repo}/{filename}: invalid issue form: {error}") from error
    if not isinstance(form, dict) or not isinstance(form.get("body"), list):
        raise IssueError(f"{repo}/{filename}: invalid issue form body")
    return form


def validate(data, form=None, scopes=None):
    problems = []
    allowed = {
        "repo",
        "kind",
        "title",
        "scope",
        "milestone",
        "parent",
        "blocked_by",
        "body",
    }
    problems += [f"unknown file key {key}" for key in sorted(set(data) - allowed)]
    for key in ("repo", "kind", "title"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            problems.append(f"{key} must be a nonempty string")
    body = data.get("body")
    if not isinstance(body, dict):
        problems.append("body must be a table")
        body = {}
    if form is not None:
        fields = [field for field in form["body"] if field.get("type") != "markdown"]
        ids = {field.get("id") for field in fields}
        problems += [f"unknown body field {key}" for key in sorted(set(body) - ids)]
        for field in fields:
            key = field.get("id")
            if not isinstance(key, str):
                raise IssueError("issue form contains a field without an id")
            value = body.get(key)
            if field.get("validations", {}).get("required") and (
                value is None
                or (isinstance(value, str) and not value.strip())
                or value == []
            ):
                problems.append(f"required body field {key} is missing or empty")
            if value is not None and not isinstance(value, (str, list)):
                problems.append(f"body.{key} must be text or a list")
            if isinstance(value, list) and not all(
                isinstance(part, str) and part.strip() for part in value
            ):
                problems.append(f"body.{key} has an empty or nontext choice")
    if scopes is not None:
        if scopes and data.get("scope") not in scopes:
            problems.append(f"scope must be one of: {', '.join(sorted(scopes))}")
        if not scopes and "scope" in data:
            problems.append("scope is not defined for this repository")
        if "milestone" in data and (
            type(data["milestone"]) not in (str, int) or not data["milestone"]
        ):
            problems.append("milestone must be a title or positive number")
        if "parent" in data and (type(data["parent"]) is not int or data["parent"] < 1):
            problems.append("parent must be a positive issue number")
        if "blocked_by" in data:
            blocked = data["blocked_by"]
            if not isinstance(blocked, list) or not blocked:
                problems.append("blocked_by must be a nonempty list of issue numbers")
            else:
                problems += [
                    f"invalid blocked_by issue {number}"
                    for number in blocked
                    if type(number) is not int or number < 1
                ]
    return problems


def render_body(form, values):
    sections = []
    for field in form["body"]:
        if field.get("type") == "markdown":
            continue
        value = values.get(field["id"])
        if isinstance(value, list):
            value = "\n".join(f"- {part}" for part in value)
        sections.append(
            f"### {field['attributes']['label']}\n\n{value or '_No response_'}"
        )
    return "\n\n".join(sections) + "\n"


def related(repo, number):
    try:
        issue = api(f"repos/{repo}/issues/{number}")
    except IssueError as error:
        if "404" in str(error):
            raise IssueError(f"{repo} issue #{number} does not exist") from error
        raise
    if "pull_request" in issue:
        raise IssueError(f"{repo} #{number} is a pull request, not an issue")
    return issue


def board_data(board):
    base = [str(board["number"]), "--owner", board["owner"], "--format", "json"]
    project = gh(["project", "view", *base])
    fields = gh(["project", "field-list", *base, "--limit", "100"])["fields"]
    items = gh(["project", "item-list", *base, "--limit", "10000"])["items"]
    status = next((field for field in fields if field.get("name") == "Status"), None)
    backlog = next(
        (
            option
            for option in (status or {}).get("options", [])
            if option["name"] == "Backlog"
        ),
        None,
    )
    if not status or not backlog:
        raise IssueError(
            f"project {board['owner']}/{board['number']}: no Status Backlog option"
        )
    return project["id"], status["id"], backlog["id"], items


def board_add(board, url):
    return gh(
        [
            "project",
            "item-add",
            str(board["number"]),
            "--owner",
            board["owner"],
            "--url",
            url,
            "--format",
            "json",
        ]
    )


def board_status(project_id, field_id, backlog_id, item_id):
    gh(
        [
            "project",
            "item-edit",
            "--id",
            item_id,
            "--project-id",
            project_id,
            "--field-id",
            field_id,
            "--single-select-option-id",
            backlog_id,
            "--format",
            "json",
        ]
    )


def open_issue(path, dry_run):
    data = read_input(path)
    repo = data.get("repo")
    try:
        _, exceptions, _, labels = load()
        boards = load_boards()
    except ConfigError as error:
        raise IssueError(str(error)) from error
    problems = []
    mapped = False
    if not isinstance(repo, str) or repo.count("/") != 1 or not all(repo.split("/")):
        problems.append("repo must be owner/name")
    elif repo in exceptions:
        problems.append(f"{repo}: workflow exception")
    elif repo not in boards:
        owner = repo.split("/", 1)[0]
        problems.append(
            f'no board mapping for {repo}; add to workflow.toml [boards]:\n"{repo}" = {{ owner = "{owner}", number = 1 }}'
        )
    else:
        mapped = True
    source, files = None, None
    if mapped:
        try:
            source, files = form_files(repo)
        except IssueError as error:
            problems.append(str(error))
    kind = data.get("kind")
    form = None
    if files is not None and isinstance(kind, str):
        if kind in files:
            try:
                form = read_form(source, files[kind]["name"])
            except IssueError as error:
                problems.append(str(error))
        else:
            problems.append(
                f"kind {kind!r} matches no issue form; valid kinds: {', '.join(sorted(files))}"
            )
    problems = validate(data, form, labels.get(repo, {}) if mapped else None) + problems
    milestone_number = None
    if mapped and (
        "milestone" in data
        and type(data["milestone"]) in (str, int)
        and data["milestone"]
    ):
        milestones = api(f"repos/{repo}/milestones?state=all&per_page=100")
        wanted = data["milestone"]
        found = next(
            (
                item
                for item in milestones
                if item["title"] == wanted or item["number"] == wanted
            ),
            None,
        )
        if found is None:
            problems.append(f"milestone {wanted!r} does not exist in {repo}")
        else:
            milestone_number = found["number"]
    parent = None
    if mapped and type(data.get("parent")) is int and data["parent"] > 0:
        try:
            parent = related(repo, data["parent"])
        except IssueError as error:
            problems.append(str(error))
    blocked = []
    for number in (
        data.get("blocked_by", [])
        if mapped and isinstance(data.get("blocked_by", []), list)
        else []
    ):
        if type(number) is not int or number < 1:
            continue
        try:
            blocked.append(related(repo, number))
        except IssueError as error:
            problems.append(str(error))
    if problems:
        print("\n".join(problems))
        return 2
    board = boards[repo]
    project_id, field_id, backlog_id, board_items = board_data(board)
    open_issues = gh(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            "10000",
            "--json",
            "number,url",
        ]
    )
    existing = {item.get("content", {}).get("url") for item in board_items}
    strays = [item for item in open_issues if item["url"] not in existing]
    body = render_body(form, data["body"])
    issue_labels = list(
        dict.fromkeys(
            [*form.get("labels", []), *([data["scope"]] if "scope" in data else [])]
        )
    )
    create = {"title": data["title"], "body": body, "labels": issue_labels}
    if milestone_number is not None:
        create["milestone"] = milestone_number
    endpoint = f"repos/{repo}/issues"
    if dry_run:
        print(f"Rendered body:\n{body}")
        print(f"Would call: POST {endpoint} {json.dumps(create, ensure_ascii=False)}")
        if parent:
            print(
                f"Would call: POST repos/{repo}/issues/{parent['number']}/sub_issues with sub_issue_id NEW_ISSUE_ID"
            )
        for issue in blocked:
            print(
                f"Would call: POST repos/{repo}/issues/NEW_ISSUE_NUMBER/dependencies/blocked_by with issue_id {issue['id']}"
            )
        print(
            f"Would call: project item-add {board['number']} --owner {board['owner']} --url NEW_ISSUE_URL"
        )
        print(
            "Would call: project item-edit Status Backlog on new issue; leave Priority, Size, Estimate and Iteration empty"
        )
        for item in strays:
            print(
                f"Would call: project item-add {board['number']} --owner {board['owner']} --url {item['url']}"
            )
            print(
                f"Would call: project item-edit Status Backlog on stray #{item['number']}"
            )
        return 0
    created = api(endpoint, payload=create)
    url = created["html_url"]
    completed = [
        f"created {url} with labels {', '.join(issue_labels)}"
        + (f" and milestone {milestone_number}" if milestone_number else "")
    ]
    planned = []
    if parent:
        planned.append(
            (
                f"linked parent #{parent['number']}",
                lambda: api(
                    f"repos/{repo}/issues/{parent['number']}/sub_issues",
                    payload={"sub_issue_id": created["id"]},
                ),
            )
        )
    for issue in blocked:
        planned.append(
            (
                f"linked blocked-by #{issue['number']}",
                lambda issue=issue: api(
                    f"repos/{repo}/issues/{created['number']}/dependencies/blocked_by",
                    payload={"issue_id": issue["id"]},
                ),
            )
        )
    item_ids = {}

    def plan_board(description, item_url):
        def add():
            item_ids[item_url] = board_add(board, item_url)["id"]

        planned.append((f"added {description} to board", add))
        planned.append(
            (
                f"set {description} Status Backlog",
                lambda: board_status(
                    project_id, field_id, backlog_id, item_ids[item_url]
                ),
            )
        )

    plan_board("new issue", url)
    for item in strays:
        plan_board(f"stray #{item['number']}", item["url"])
    for index, (description, action) in enumerate(planned):
        try:
            action()
        except (IssueError, KeyError) as error:
            print(url)
            print("completed: " + "; ".join(completed))
            print("not completed: " + "; ".join(name for name, _ in planned[index:]))
            print(f"failed: {error}")
            return 2
        completed.append(description)
    print(url)
    for step in completed:
        print(step)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    opener = commands.add_parser("open", help="create a checked issue from a TOML file")
    opener.add_argument("file")
    opener.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        return open_issue(arguments.file, arguments.dry_run)
    except IssueError as error:
        print(error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
