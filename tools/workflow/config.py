"""The sole reader and validator of workflow TOML files."""

from pathlib import Path
import re
import tomllib


DIRECTORY = Path(__file__).resolve().parent
COLOR = re.compile(r"[0-9a-fA-F]{6}\Z")


class ConfigError(Exception):
    """A named workflow file cannot be used."""


def _read(filename):
    path = DIRECTORY / filename
    try:
        with path.open("rb") as source:
            return tomllib.load(source)
    except FileNotFoundError as error:
        raise ConfigError(f"{filename}: missing") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{filename}: malformed: {error}") from error
    except OSError as error:
        raise ConfigError(f"{filename}: {error}") from error


def _labels(group, filename):
    if not isinstance(group, dict):
        raise ConfigError(f"{filename}: labels must be tables")
    result = {}
    for name, fields in group.items():
        if not isinstance(fields, dict):
            raise ConfigError(f"{filename}: {name}: label must be a table")
        color = fields.get("color")
        if color is None:
            raise ConfigError(f"{filename}: missing color for {name}")
        if not isinstance(color, str) or not COLOR.fullmatch(color):
            raise ConfigError(f"{filename}: invalid color for {name}")
        description = fields.get("description")
        if not isinstance(description, str):
            raise ConfigError(f"{filename}: missing or invalid description for {name}")
        result[name] = {"color": color, "description": description}
    return result


def load():
    """Return owners, exceptions, global labels and repository scope labels."""
    label_data = _read("labels.toml")
    workflow_data = _read("workflow.toml")
    global_labels = _labels(label_data.get("global"), "labels.toml")
    if not global_labels:
        raise ConfigError("labels.toml: missing global labels")
    repository_data = label_data.get("repository", {})
    if not isinstance(repository_data, dict):
        raise ConfigError("labels.toml: repository labels must be tables")
    repository_labels = {
        repo: _labels(group, "labels.toml") for repo, group in repository_data.items()
    }
    for repo, labels in repository_labels.items():
        overlap = global_labels.keys() & labels.keys()
        if overlap:
            raise ConfigError(
                f"labels.toml: duplicate label {sorted(overlap)[0]} in {repo}"
            )
    owners = workflow_data.get("owners")
    exceptions = workflow_data.get("exceptions")
    if (
        not isinstance(owners, list)
        or not owners
        or not all(isinstance(owner, str) and owner for owner in owners)
    ):
        raise ConfigError("workflow.toml: missing or invalid owners")
    if not isinstance(exceptions, list) or not all(
        isinstance(repo, str) and repo for repo in exceptions
    ):
        raise ConfigError("workflow.toml: missing or invalid exceptions")
    return owners, set(exceptions), global_labels, repository_labels


def load_board_config():
    """Return repository board mappings and product names in configured order."""
    data = _read("workflow.toml")
    products = data.get("products")
    if not isinstance(products, dict):
        raise ConfigError("workflow.toml: missing or invalid products table")
    used_boards = {}
    for name, product in products.items():
        if (
            not name
            or not isinstance(product, dict)
            or set(product) != {"owner", "number"}
            or not isinstance(product["owner"], str)
            or not product["owner"]
            or type(product["number"]) is not int
            or product["number"] < 1
        ):
            raise ConfigError(f"workflow.toml: invalid product {name}")
        board = (product["owner"], product["number"])
        if board in used_boards:
            raise ConfigError(
                f"workflow.toml: products {used_boards[board]} and {name} "
                f"share board {board[0]} {board[1]}"
            )
        used_boards[board] = name
    boards = data.get("boards")
    if not isinstance(boards, dict):
        raise ConfigError("workflow.toml: missing or invalid boards table")
    result = {}
    for repo, product in boards.items():
        if (
            not isinstance(repo, str)
            or "/" not in repo
            or not isinstance(product, str)
            or not product
        ):
            raise ConfigError(f"workflow.toml: invalid board mapping for {repo}")
        if product not in products:
            raise ConfigError(
                f"workflow.toml: board mapping for {repo} names unknown product {product}"
            )
        result[repo] = dict(products[product])
    return result, list(products)


def load_boards():
    """Return validated repository-to-project mappings from workflow.toml."""
    boards, _ = load_board_config()
    return boards


def load_bot():
    """Return the configured nightly review bot's login."""
    bot = _read("workflow.toml").get("bot")
    login = bot.get("login") if isinstance(bot, dict) else None
    if not isinstance(login, str) or not login:
        raise ConfigError("workflow.toml: [bot] login must be a non-empty string")
    return login
