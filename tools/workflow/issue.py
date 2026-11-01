"""Open checked GitHub issues, file review debt, and check readiness."""

import argparse
import base64
import json
from pathlib import Path
import re
import subprocess
import tomllib

from config import ConfigError, load, load_board_config, load_boards


class IssueError(Exception):
    """The input or a GitHub response cannot be used."""


def gh(args, payload=None, graphql_errors=False):
    result = subprocess.run(
        ["gh", *args],
        input=json.dumps(payload) if payload is not None else "",
        text=True,
        capture_output=True,
    )
    if result.returncode:
        if graphql_errors:
            try:
                response = json.loads(result.stdout)
            except json.JSONDecodeError:
                response = None
            errors = response.get("errors") if isinstance(response, dict) else None
            if isinstance(errors, list):
                raise IssueError("\n".join(error["message"] for error in errors))
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


CARD_QUERY = """query($url: URI!, $owner: String!, $number: Int!) { resource(url: $url) { ... on Issue { projectItems(first: 20) { nodes { id project { id number owner { ... on User { login } ... on Organization { login } } } fieldValues(first: 20) { nodes { ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } } ... on ProjectV2ItemFieldNumberValue { number field { ... on ProjectV2FieldCommon { name } } } } } } } } } repositoryOwner(login: $owner) { ... on ProjectV2Owner { projectV2(number: $number) { id field(name: "Status") { ... on ProjectV2SingleSelectField { id options { id name } } } } } } }"""
REPOSITORY_QUERY = """query($owner: String!, $name: String!, $number: Int!, $cursor: String) { repository(owner: $owner, name: $name) { issues(states: OPEN, first: 100, after: $cursor) { pageInfo { hasNextPage endCursor } nodes { number url projectItems(first: 20) { nodes { project { number owner { ... on User { login } ... on Organization { login } } } } } } } } repositoryOwner(login: $owner) { ... on ProjectV2Owner { projectV2(number: $number) { id field(name: "Status") { ... on ProjectV2SingleSelectField { id options { id name } } } } } } }"""


def graphql(query, **variables):
    args = ["api", "graphql", "-f", f"query={query}"]
    for name, value in variables.items():
        if value is not None:
            args.extend(["-F" if type(value) is int else "-f", f"{name}={value}"])
    return gh(args, graphql_errors=True)


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


def validate(data, form=None, scopes=None, global_labels=None):
    problems = []
    allowed = {
        "repo",
        "kind",
        "title",
        "scope",
        "milestone",
        "parent",
        "blocked_by",
        "labels",
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
    if "labels" in data and global_labels is not None:
        extra_labels = data["labels"]
        if not isinstance(extra_labels, list) or not all(
            isinstance(label, str) and label.strip() for label in extra_labels
        ):
            problems.append("labels must be a list of label names")
        else:
            for label in extra_labels:
                if label.startswith("type:"):
                    problems.append(
                        f"labels: {label} is set by the issue form, not the labels list"
                    )
                elif label.startswith("scope:"):
                    problems.append(
                        f"labels: {label} is set by the scope key, not the labels list"
                    )
                elif label not in global_labels:
                    problems.append(
                        f"labels: {label} is not a global label in labels.toml"
                    )
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


def board_data(response, board, status_name="Backlog"):
    data = response.get("data") if isinstance(response, dict) else None
    owner = data.get("repositoryOwner") if isinstance(data, dict) else None
    project = owner.get("projectV2") if isinstance(owner, dict) else None
    status = project.get("field") if isinstance(project, dict) else None
    option = next(
        (
            option
            for option in (status or {}).get("options", [])
            if option["name"] == status_name
        ),
        None,
    )
    if not status or not option:
        raise IssueError(
            f"project {board['owner']}/{board['number']}: no Status {status_name} option"
        )
    return project["id"], status["id"], option["id"]


def on_board(card, board):
    project = card.get("project") if isinstance(card, dict) else None
    owner = project.get("owner") if isinstance(project, dict) else None
    return (
        isinstance(project, dict)
        and project.get("number") == board["number"]
        and isinstance(owner, dict)
        and owner.get("login") == board["owner"]
    )


def card_nodes(response):
    data = response.get("data") if isinstance(response, dict) else None
    resource = data.get("resource") if isinstance(data, dict) else None
    if not isinstance(resource, dict):
        raise IssueError("resource is not an issue")
    items = resource.get("projectItems")
    if not isinstance(items, dict):
        raise IssueError("projectItems is missing")
    nodes = items.get("nodes")
    if not isinstance(nodes, list):
        raise IssueError("board cards are missing")
    for card in nodes:
        project = card.get("project") if isinstance(card, dict) else None
        owner = project.get("owner") if isinstance(project, dict) else None
        if (
            not isinstance(project, dict)
            or not isinstance(project.get("number"), int)
            or not isinstance(owner, dict)
            or not isinstance(owner.get("login"), str)
            or not isinstance(card.get("id"), str)
        ):
            raise IssueError("board card is incomplete")
    return nodes


def card_read(board, url):
    response = graphql(
        CARD_QUERY, url=url, owner=board["owner"], number=board["number"]
    )
    return response, next(
        (card for card in card_nodes(response) if on_board(card, board)), None
    )


def repository_read(repo, board):
    owner, name = repo.split("/", 1)
    cursor = None
    strays = []
    board_ids = None
    while True:
        response = graphql(
            REPOSITORY_QUERY,
            owner=owner,
            name=name,
            number=board["number"],
            cursor=cursor,
        )
        if board_ids is None:
            board_ids = board_data(response, board)
        data = response.get("data") if isinstance(response, dict) else None
        repository = data.get("repository") if isinstance(data, dict) else None
        issues = repository.get("issues") if isinstance(repository, dict) else None
        if not isinstance(issues, dict) or not isinstance(issues.get("nodes"), list):
            raise IssueError("repository issues are missing")
        for issue in issues["nodes"]:
            cards = issue.get("projectItems") if isinstance(issue, dict) else None
            nodes = cards.get("nodes") if isinstance(cards, dict) else None
            if not isinstance(nodes, list):
                raise IssueError("board cards are missing")
            if not any(on_board(card, board) for card in nodes):
                strays.append(issue)
        page = issues.get("pageInfo")
        if not isinstance(page, dict):
            raise IssueError("repository issue page is missing")
        if not page.get("hasNextPage"):
            return (*board_ids, strays)
        cursor = page.get("endCursor")
        if not isinstance(cursor, str) or not cursor:
            raise IssueError("repository issue cursor is missing")


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


def board_card(board, url):
    _, card = card_read(board, url)
    return card["id"] if card else None


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
    return open_data(read_input(path), dry_run)


def open_data(data, dry_run):
    repo = data.get("repo")
    try:
        _, exceptions, global_labels, labels = load()
        boards, products = load_board_config()
    except ConfigError as error:
        raise IssueError(str(error)) from error
    problems = []
    mapped = False
    if not isinstance(repo, str) or repo.count("/") != 1 or not all(repo.split("/")):
        problems.append("repo must be owner/name")
    elif repo in exceptions:
        problems.append(f"{repo}: workflow exception")
    elif repo not in boards:
        problems.append(
            f"no board mapping for {repo}; add to workflow.toml [boards], naming its product:\n"
            f'"{repo}" = "<product>"\nproducts: {", ".join(products)}'
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
    problems = (
        validate(data, form, labels.get(repo, {}) if mapped else None, global_labels)
        + problems
    )
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
    project_id, field_id, backlog_id, strays = repository_read(repo, board)
    body = render_body(form, data["body"])
    issue_labels = list(
        dict.fromkeys(
            [
                *form.get("labels", []),
                *([data["scope"]] if "scope" in data else []),
                *data.get("labels", []),
            ]
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
            [
                f"linked parent #{parent['number']}",
                lambda: api(
                    f"repos/{repo}/issues/{parent['number']}/sub_issues",
                    payload={"sub_issue_id": created["id"]},
                ),
            ]
        )
    for issue in blocked:
        planned.append(
            [
                f"linked blocked-by #{issue['number']}",
                lambda issue=issue: api(
                    f"repos/{repo}/issues/{created['number']}/dependencies/blocked_by",
                    payload={"issue_id": issue["id"]},
                ),
            ]
        )
    item_ids = {}

    def plan_board(description, item_url):
        def add():
            try:
                item_ids[item_url] = board_add(board, item_url)["id"]
            except IssueError as add_error:
                try:
                    item_id = board_card(board, item_url)
                except IssueError as lookup_error:
                    raise IssueError(
                        f"{add_error}; checking the board also failed: {lookup_error}"
                    ) from lookup_error
                if item_id is None:
                    raise
                item_ids[item_url] = item_id
                step[0] = f"found {description} already on board"

        step = [f"added {description} to board", add]
        planned.append(step)
        planned.append(
            [
                f"set {description} Status Backlog",
                lambda: board_status(
                    project_id, field_id, backlog_id, item_ids[item_url]
                ),
            ]
        )

    plan_board("new issue", url)
    for item in strays:
        plan_board(f"stray #{item['number']}", item["url"])
    for index, step in enumerate(planned):
        try:
            step[1]()
        except (IssueError, KeyError) as error:
            print(url)
            print("completed: " + "; ".join(completed))
            print("not completed: " + "; ".join(name for name, _ in planned[index:]))
            print(f"failed: {error}")
            return 2
        completed.append(step[0])
    print(url)
    for step in completed:
        print(step)
    return 0


def review_result(path):
    try:
        lines = Path(path).read_text().splitlines()
    except OSError as error:
        raise IssueError(f"{path}: {error}") from error
    response = []
    in_response = False
    for line in lines:
        if line == "## Response":
            in_response = True
            continue
        if in_response and line.startswith("## "):
            break
        if in_response:
            response.append(line)
    blocks = []
    inside = False
    content = []
    for line in response:
        if not inside and line == "```json":
            inside = True
            content = []
        elif inside and line == "```":
            inside = False
            try:
                value = json.loads("\n".join(content))
            except json.JSONDecodeError:
                continue
            if (
                isinstance(value, dict)
                and {"repo", "issue", "item", "verdict", "findings"} <= value.keys()
            ):
                blocks.append(value)
        elif inside:
            content.append(line)
    if len(blocks) != 1:
        raise IssueError(
            f"{Path(path).name}: expected exactly one review result block in Response, found {len(blocks)}"
        )
    return blocks[0]


def review_file_identity(name):
    match = re.search(r"-review-(\d+)\.md$", name)
    if match is None:
        return None
    build = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name[: match.start()])
    return build, int(match.group(1))


def debt_issue(path, dry_run):
    result = review_result(path)
    name = Path(path).name
    identity = review_file_identity(name)
    if identity is None:
        raise IssueError(f"{name}: expected a -review-<round>.md file name")
    build, final_round = identity
    rounds = {}
    for candidate in Path(path).parent.iterdir():
        if not candidate.is_file():
            continue
        candidate_identity = review_file_identity(candidate.name)
        if candidate_identity is not None and candidate_identity[0] == build:
            rounds.setdefault(candidate_identity[1], []).append(candidate)
    if 0 in rounds:
        zero = min(candidate.name for candidate in rounds[0])
        raise IssueError(f"{name}: {zero} is round 0; rounds start at 1")
    for number in sorted(rounds):
        if len(rounds[number]) > 1:
            names = sorted(candidate.name for candidate in rounds[number])
            files = ", ".join(names[:-1]) + " and " + names[-1]
            raise IssueError(
                f"{name}: round {number} appears in more than one file: {files}"
            )
    rounds = {number: paths[0] for number, paths in rounds.items()}
    highest = max(rounds)
    if highest > final_round:
        raise IssueError(
            f"{name}: round {highest} exists in {rounds[highest].name}; run debt on the final round"
        )
    for round_number in range(1, final_round + 1):
        if round_number not in rounds:
            raise IssueError(f"{name}: round {round_number} is missing")
    if result["verdict"] != "pass":
        raise IssueError(
            f"{name}: the final round's verdict is {result['verdict']}; leftovers are filed once the build passes"
        )
    reviews = []
    for round_number in range(1, final_round + 1):
        round_path = rounds[round_number]
        round_result = (
            result if round_number == final_round else review_result(round_path)
        )
        if round_number != final_round and any(
            round_result[key] != result[key] for key in ("repo", "issue", "item")
        ):
            raise IssueError(
                f"{name}: {round_path.name} names a different repository, issue or item"
            )
        reviews.append((round_number, round_path.name, round_result))
    leftovers = []
    for round_number, round_name, round_result in reviews:
        findings = round_result["findings"]
        if not isinstance(findings, list):
            raise IssueError(f"{round_name}: findings must be a list")
        leftovers.extend(
            (round_number, finding)
            for finding in findings
            if isinstance(finding, dict)
            and finding.get("severity") == "non_blocking"
            and finding.get("breaks_test_case") == "none"
        )
    if not leftovers:
        print(f"{name}: no leftover findings; nothing opened")
        return 0
    repo, number, item = result["repo"], result["issue"], result["item"]
    if (
        not isinstance(repo, str)
        or repo.count("/") != 1
        or type(number) is not int
        or number < 1
        or not isinstance(item, str)
        or not item
    ):
        raise IssueError(f"{name}: review result has invalid repo, issue or item")
    children = api(f"repos/{repo}/issues/{number}/sub_issues")
    if not isinstance(children, list):
        raise IssueError(f"{name}: GitHub returned invalid sub-issues")
    for child in children:
        if isinstance(child, dict) and name in (child.get("body") or ""):
            raise IssueError(
                f"{name}: #{child['number']} already files this review's leftovers"
            )
    for _, round_name, _ in reviews[:-1]:
        for child in children:
            if isinstance(child, dict) and round_name in (child.get("body") or ""):
                raise IssueError(
                    f"{name}: #{child['number']} already files leftovers from {round_name}"
                )
    issue = related(repo, number)
    scopes = [
        label["name"]
        for label in issue.get("labels", [])
        if label["name"].startswith("scope:")
    ]
    if len(scopes) != 1:
        raise IssueError(f"{name}: #{number} must have one scope label")
    changes = []
    for round_number, finding in leftovers:
        summary = finding.get("summary")
        if not isinstance(summary, str) or not summary:
            raise IssueError(f"{name}: leftover finding has no summary")
        prefix = f"Round {round_number}: " if final_round > 1 else ""
        location = finding.get("file")
        if location:
            location = f"{location}:{finding['line']}"
            changes.append(f"- {prefix}{location}: {summary}")
        else:
            changes.append(f"- {prefix}{summary}")
    sources = [f"05_Agents/handoffs/{round_name}" for _, round_name, _ in reviews]
    if final_round == 1:
        context = f"Non-blocking findings from {item}'s round 1 review of #{number}, in {sources[0]}."
    else:
        context = f"Non-blocking findings from {item}'s review rounds 1 to {final_round} of #{number}, in {', '.join(sources[:-1])} and {sources[-1]}."
    data = {
        "repo": repo,
        "kind": "chore",
        "title": f"Tech debt from the review of {item}",
        "scope": scopes[0],
        "parent": number,
        "labels": ["tech-debt"],
        "body": {
            "context": context,
            "changes": "\n".join(changes),
            "done": "Each finding above is fixed with a test, or closed in triage with the reason it stays.",
        },
    }
    return open_data(data, dry_run)


def form_sections(body):
    """Read GitHub's issue-form heading layout and the text below each heading."""
    sections = {}
    heading = None
    for line in body.splitlines():
        if line.startswith("### "):
            heading = line[4:].strip()
            sections.setdefault(heading, [])
        elif heading is not None:
            sections[heading].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def ready_issue(reference, check):
    if reference.count("#") != 1:
        raise IssueError("issue must be owner/repo#number")
    repo, number_text = reference.split("#")
    if (
        repo.count("/") != 1
        or not all(repo.split("/"))
        or not number_text.isdigit()
        or int(number_text) < 1
    ):
        raise IssueError("issue must be owner/repo#number")
    number = int(number_text)
    try:
        _, _, _, repository_labels = load()
        boards = load_boards()
    except ConfigError as error:
        raise IssueError(str(error)) from error
    if repo not in boards:
        raise IssueError(f"no board mapping for {repo}")
    issue = related(repo, number)
    board = boards[repo]
    issue_url = issue["html_url"]
    response, item = card_read(board, issue_url)
    project_id, status_id, ready_id = board_data(response, board, "Ready")
    if item is None:
        raise IssueError(f"{reference} is not on its repository's board")

    source, files = form_files(repo)
    forms = [read_form(source, file["name"]) for file in files.values()]
    labels = [label["name"] for label in issue.get("labels", [])]
    types = [label for label in labels if label.startswith("type:")]
    matched = [
        form
        for form in forms
        if any(label in types for label in form.get("labels", []))
    ]
    form = matched[0] if len(types) == 1 and len(matched) == 1 else None
    scope_labels = set(repository_labels.get(repo, {}))
    scopes = [label for label in labels if label.startswith("scope:")]
    output = []
    unmet = False

    def report(ok, name, detail=""):
        nonlocal unmet
        output.append(f"{'met' if ok else 'unmet'}: {name}{detail}")
        unmet |= not ok

    report(
        len(types) == 1 and form is not None,
        "one type: label",
        " (" + ", ".join(types) + ")" if types and len(types) != 1 else "",
    )
    report(
        not scope_labels or len(scopes) == 1 and scopes[0] in scope_labels,
        "a scope: label" if scope_labels else "scope: label not required",
        " (" + ", ".join(scopes) + ")"
        if scopes and (len(scopes) != 1 or scopes[0] not in scope_labels)
        else "",
    )

    def required_labels(candidate):
        return {
            field["attributes"]["label"]
            for field in candidate["body"]
            if field.get("type") != "markdown"
            and field.get("validations", {}).get("required")
        }

    required = (
        required_labels(form)
        if form
        else set.intersection(*(required_labels(candidate) for candidate in forms))
        if forms
        else set()
    )
    sections = form_sections(issue.get("body") or "")
    missing = sorted(
        label
        for label in required
        if not sections.get(label) or sections[label] == "_No response_"
    )
    if missing:
        for label in missing:
            report(False, label)
    else:
        report(True, "required form sections")

    field_values = item.get("fieldValues", {}).get("nodes", [])
    values = {
        node["field"]["name"]: node.get("name", node.get("number"))
        for node in field_values
        if isinstance(node, dict) and isinstance(node.get("field"), dict)
    }
    for field in ("Priority", "Size", "Estimate"):
        report(values.get(field) not in (None, ""), field)
    try:
        parent = api(f"repos/{repo}/issues/{number}/parent")
    except IssueError as error:
        if "No parent issue found" in str(error) and "404" in str(error):
            parent = None
        else:
            raise
    report(bool(issue.get("milestone") or parent), "milestone or parent")
    blockers = api(f"repos/{repo}/issues/{number}/dependencies/blocked_by")
    if not isinstance(blockers, list):
        raise IssueError(f"{reference}: blocked_by response is not a list")
    open_blockers = [blocker for blocker in blockers if blocker.get("state") == "open"]
    if open_blockers:
        for blocker in open_blockers:
            blocker_repo = blocker["repository"]["full_name"]
            report(
                False,
                f"open blocker {blocker_repo}#{blocker['number']}",
            )
    else:
        report(True, "no open blocking issues")
    architecture = values.get("Size") == "Architecture"
    design = any(
        line.startswith("Design: ") for line in (issue.get("body") or "").splitlines()
    )
    report(
        not architecture or design,
        "Architecture design link"
        if architecture and design
        else "Architecture design link not required"
        if not architecture
        else "Design: line",
    )
    if unmet:
        print("\n".join(output))
        return 1
    if not check:
        board_status(project_id, status_id, ready_id, item["id"])
        output.append(f"set Status Ready on {reference}")
    else:
        output.append(f"ready: {reference}")
    print("\n".join(output))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    opener = commands.add_parser("open", help="create a checked issue from a TOML file")
    opener.add_argument("file")
    opener.add_argument("--dry-run", action="store_true")
    debt_parser = commands.add_parser(
        "debt", help="file a build's review leftovers from its final round"
    )
    debt_parser.add_argument("review_handoff")
    debt_parser.add_argument("--dry-run", action="store_true")
    ready_parser = commands.add_parser(
        "ready", help="check an issue's Definition of Ready"
    )
    ready_parser.add_argument("issue")
    ready_parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "ready":
            return ready_issue(arguments.issue, arguments.check)
        if arguments.command == "debt":
            return debt_issue(arguments.review_handoff, arguments.dry_run)
        return open_issue(arguments.file, arguments.dry_run)
    except IssueError as error:
        print(error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
