"""Find one Bitwarden item by its exact name."""

import base64
import json
import os
from pathlib import Path
import subprocess


CONTAINER_MARKER = Path("/run/.containerenv")


class VaultItemError(Exception):
    """A vault item cannot be read unambiguously."""


class StaleItemError(VaultItemError):
    """The local copy was changed by another client."""


def _container_check():
    if not CONTAINER_MARKER.is_file():
        raise VaultItemError(
            "bw runs only inside the dev container (distrobox enter dev)"
        )


def _environment():
    environment = os.environ.copy()
    environment["BW_NOINTERACTION"] = "true"
    if not environment.get("BW_SESSION"):
        session_file = (
            Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
            / "bw-session"
        )
        try:
            environment["BW_SESSION"] = session_file.read_text()
        except OSError:
            environment.pop("BW_SESSION", None)
    return environment


def read_item(name):
    _container_check()
    environment = _environment()
    unavailable = f'nothing from the vault for "{name}". Is it unlocked? Run vu.'
    try:
        result = subprocess.run(
            ["bw", "list", "items", "--search", name],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise VaultItemError(unavailable)
        items = json.loads(result.stdout)
    except (OSError, ValueError) as error:
        raise VaultItemError(unavailable) from error
    if not isinstance(items, list):
        raise VaultItemError(unavailable)

    exact = [
        item for item in items if isinstance(item, dict) and item.get("name") == name
    ]
    if not exact:
        raise VaultItemError(f'no vault item is named exactly "{name}"')
    if len(exact) > 1:
        raise VaultItemError(f'{len(exact)} vault items are named exactly "{name}"')
    return exact[0]


def sync():
    _container_check()
    try:
        result = subprocess.run(
            ["bw", "sync"],
            env=_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise VaultItemError("bw sync failed") from error
    if result.returncode != 0:
        raise VaultItemError("bw sync failed")


def edit_item(item_id, item):
    _container_check()
    request = base64.b64encode(json.dumps(item).encode())
    try:
        result = subprocess.run(
            ["bw", "edit", "item", item_id],
            input=request,
            env=_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise VaultItemError("bw edit could not run") from error
    if result.returncode != 0 and result.stderr.decode(
        "utf-8", errors="replace"
    ).startswith("The client copy of this cipher is out of date."):
        raise StaleItemError("item changed while loading")
    return result.returncode
