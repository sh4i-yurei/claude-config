"""Bring labels in every active configured repository to the local definition."""

import argparse
import json
import subprocess
import sys

from config import ConfigError, load


class GhError(Exception):
    """A gh invocation failed with repository and label context."""


def gh(args, repo, label=None):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"exit {result.returncode}"
        )
        location = f"{repo} {label}" if label else repo
        raise GhError(f"{location}: {detail}")
    return result.stdout


def gh_json(args, repo, label=None):
    raw = gh(args, repo, label)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        location = f"{repo} {label}" if label else repo
        raise GhError(f"{location}: invalid JSON from gh: {error}") from error


def repositories(owners):
    for owner in owners:
        yield from gh_json(
            [
                "repo",
                "list",
                owner,
                "--limit",
                "1000",
                "--json",
                "nameWithOwner,isArchived",
            ],
            owner,
        )


def open_issues(repo, label):
    issues = gh_json(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--label",
            label,
            "--limit",
            "1000",
            "--json",
            "number",
        ],
        repo,
        label,
    )
    return sorted(item["number"] for item in issues)


def open_pull_requests(repo, label):
    pull_requests = gh_json(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--label",
            label,
            "--limit",
            "1000",
            "--json",
            "number",
        ],
        repo,
        label,
    )
    return sorted(item["number"] for item in pull_requests)


def sync_repo(repo, desired, dry_run):
    current = gh_json(
        [
            "label",
            "list",
            "--repo",
            repo,
            "--limit",
            "1000",
            "--json",
            "name,color,description,isDefault",
        ],
        repo,
    )
    existing = {label["name"]: label for label in current}
    print(repo)
    changes = 0
    blocked = False
    for name, fields in desired.items():
        old = existing.get(name)
        if old is None:
            action = "create"
        elif (
            old["color"].lower() != fields["color"].lower()
            or old["description"] != fields["description"]
        ):
            action = "update"
        else:
            continue
        changes += 1
        print(f"  {action} {name}")
        if not dry_run:
            gh(
                [
                    "label",
                    "create",
                    name,
                    "--repo",
                    repo,
                    "--color",
                    fields["color"],
                    "--description",
                    fields["description"],
                    "--force",
                ],
                repo,
                name,
            )
    for name in sorted(existing.keys() - desired.keys()):
        issues = open_issues(repo, name)
        pull_requests = open_pull_requests(repo, name)
        if issues or pull_requests:
            blocked = True
            uses = []
            if issues:
                numbers = ", ".join(f"#{number}" for number in issues)
                uses.append(f"open issues {numbers}")
            if pull_requests:
                numbers = ", ".join(f"#{number}" for number in pull_requests)
                uses.append(f"open pull requests {numbers}")
            reason = "; ".join(uses)
            print(f"  keep {name}: {reason}")
            print(f"keep {repo} {name}: {reason}")
            continue
        changes += 1
        print(f"  delete {name}")
        if not dry_run:
            gh(["label", "delete", name, "--repo", repo, "--yes"], repo, name)
    if not changes and not blocked:
        print("  no changes")
    return blocked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="show changes without writing"
    )
    args = parser.parse_args()
    try:
        owners, exceptions, global_labels, repository_labels = load()
        blocked = False
        for item in repositories(owners):
            repo = item["nameWithOwner"]
            if item["isArchived"]:
                print(f"skip {repo}: archived")
                continue
            if repo in exceptions:
                print(f"skip {repo}: exception")
                continue
            desired = global_labels | repository_labels.get(repo, {})
            blocked |= sync_repo(repo, desired, args.dry_run)
        return 1 if blocked else 0
    except (ConfigError, GhError) as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
