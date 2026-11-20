#!/usr/bin/python3
"""Give Git its GitHub token from the vault."""

import sys

import vault_item


TOKEN_ITEM = "API tokens (keepbreath.ing)"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] != "get":
        return 0
    try:
        item = vault_item.read_item(TOKEN_ITEM)
    except vault_item.VaultItemError as error:
        print(f"git-credential-bw: {error}", file=sys.stderr)
        return 1
    token = next(
        (
            field.get("value")
            for field in item.get("fields") or []
            if field.get("name") == "GH_TOKEN"
        ),
        None,
    )
    if not isinstance(token, str) or not token:
        print(f'git-credential-bw: no GH_TOKEN on "{TOKEN_ITEM}"', file=sys.stderr)
        return 1
    print("username=sh4i-yurei")
    print(f"password={token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
