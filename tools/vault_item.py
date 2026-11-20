"""Find one Bitwarden item by its exact name."""

import json
import os
from pathlib import Path
import subprocess


CONTAINER_MARKER = Path("/run/.containerenv")


class VaultItemError(Exception):
    """A vault item cannot be read unambiguously."""


def read_item(name):
    if not CONTAINER_MARKER.is_file():
        raise VaultItemError(
            "bw runs only inside the dev container (distrobox enter dev)"
        )

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
