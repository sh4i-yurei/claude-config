#!/usr/bin/python3
"""Print selected vault fields as quoted shell exports."""

import shlex
import sys

import vault_item


TOKEN_ITEM = "API tokens (keepbreath.ing)"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv or sys.stdout.isatty():
        print('usage: eval "$(vault-env)"', file=sys.stderr)
        return 2
    try:
        item = vault_item.read_item(TOKEN_ITEM)
    except vault_item.VaultItemError as error:
        print(f"vault-env: {error}", file=sys.stderr)
        return 1
    for field in item.get("fields") or []:
        if field.get("name") and field.get("value") is not None:
            print(f"export {field['name']}={shlex.quote(field['value'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
