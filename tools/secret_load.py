#!/usr/bin/python3
"""Load one staged secret without displaying its value."""

import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import vault_item

OPENBAO_ADDR = "https://openbao.tail4cf2f3.ts.net"
LOGIN_ITEM = "openbao keepbreath0 (hub)"


class SourceError(Exception):
    """The staged source cannot be used."""


class BaoError(Exception):
    """OpenBao failed or answered unexpectedly."""


class VaultTargetError(Exception):
    """The selected Vaultwarden target cannot be used."""


def _vault_target(item, field):
    if field == "login.password":
        login = item.get("login")
        if not isinstance(login, dict):
            raise VaultTargetError("the item is not a login")
        return login.get("password"), "login", None
    fields = item.get("fields") or []
    matching = [
        (index, entry)
        for index, entry in enumerate(fields)
        if entry.get("name") == field
    ]
    if len(matching) > 1:
        raise VaultTargetError(f'{len(matching)} fields are named exactly "{field}"')
    if not matching:
        return None, "new", None
    index, entry = matching[0]
    if entry.get("type") not in (0, 1):
        raise VaultTargetError("the field is not a text or hidden field")
    return entry.get("value"), "field", index


def _vaultwarden(item_name, field, destination, value, options):
    try:
        vault_item.sync()
        item = vault_item.read_item(item_name)
        current, kind, index = _vault_target(item, field)
    except vault_item.VaultItemError as error:
        print(f"secret-load: {error}", file=sys.stderr)
        return 1
    except VaultTargetError as error:
        print(f"secret-load: {destination}: {error}", file=sys.stderr)
        return 1
    if current not in (None, "") and current != value and not options.replace:
        print(
            f"secret-load: {destination} holds a different value; use --replace to rotate it",
            file=sys.stderr,
        )
        return 1
    if options.dry_run:
        action = (
            "already holds this value"
            if current == value
            else "would replace a different value"
            if current not in (None, "")
            else "would add a hidden field"
            if kind == "new"
            else "would set the login password"
            if kind == "login"
            else "would set an empty field"
        )
        print(f"dry run: {destination}: {action}, length {len(value)}")
        return 0
    if current == value:
        print(f"{destination}: already holds this value, length {len(value)}")
        return 0
    changed = copy.deepcopy(item)
    if kind == "login":
        changed["login"]["password"] = value
    elif kind == "new":
        changed["fields"] = (changed.get("fields") or []) + [
            {"name": field, "value": value, "type": 1, "linkedId": None}
        ]
    else:
        changed["fields"][index]["value"] = value
    try:
        status = vault_item.edit_item(item["id"], changed)
    except vault_item.StaleItemError:
        print(
            f"secret-load: {destination} changed while loading; nothing written",
            file=sys.stderr,
        )
        return 1
    except vault_item.VaultItemError as error:
        print(f"secret-load: {error}", file=sys.stderr)
        return 1
    if status != 0:
        print(f"{destination}: write {status}")
        return 1
    try:
        vault_item.sync()
        read_back = vault_item.read_item(item_name)
    except vault_item.VaultItemError as error:
        print(f"{destination}: write 0")
        print(f"secret-load: {error}", file=sys.stderr)
        return 1
    try:
        read_value, _, _ = _vault_target(read_back, field)
        matches = read_back.get("id") == item["id"] and read_value == value
    except VaultTargetError:
        matches = False
    print(
        f"{destination}: write 0, read back 0, matches {matches}, length {len(value)}"
    )
    return 0 if matches else 1


def _parser():
    parser = argparse.ArgumentParser(prog="secret-load")
    parser.add_argument("--from", dest="source", required=True, metavar="FILE")
    parser.add_argument("--label", metavar="LABEL")
    parser.add_argument(
        "--to",
        required=True,
        metavar="DEST",
        help="openbao:PATH[#KEY] or vaultwarden:ITEM#FIELD",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace a different existing value. OpenBao keeps the old version; Vaultwarden keeps a replaced login password or hidden field in the item's password history, but not a replaced text field.",
    )
    parser.add_argument(
        "--remove-source",
        action="store_true",
        help="After a verified match, remove the label's line, or the whole file. Removal does not scrub the old data from a btrfs disk.",
    )
    return parser


def _destination(text):
    if text.startswith("vaultwarden:"):
        item_field = text[len("vaultwarden:") :]
        item, separator, field = item_field.rpartition("#")
        if not separator or not item or not field:
            raise SourceError("--to must be vaultwarden:ITEM#FIELD")
        return item, field, text
    if not text.startswith("openbao:"):
        raise SourceError("--to must be openbao:PATH[#KEY] or vaultwarden:ITEM#FIELD")
    path_key = text[len("openbao:") :]
    path, separator, key = path_key.rpartition("#")
    if not separator:
        path, key = path_key, "value"
    if (
        not path
        or not key
        or any(segment in ("", ".", "..") for segment in path.split("/"))
        or any(char in path_key for char in ("?", "\\"))
        or "#" in path
        or "/" in key
    ):
        raise SourceError("--to must be openbao:PATH[#KEY]")
    return path, key, f"openbao:{path}#{key}"


def _source(filename, label):
    try:
        original = Path(filename).read_bytes()
    except OSError as error:
        raise SourceError(f"cannot read {filename}: {error.strerror}") from error
    try:
        content = original.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceError(
            f"cannot read {filename}: source is not UTF-8 text"
        ) from error
    if label is None:
        value = content.removesuffix("\r\n").removesuffix("\n")
        if not value:
            raise SourceError(f"{filename} is empty")
        return value, original, None
    matches = []
    for number, raw_line in enumerate(original.splitlines(), 1):
        line = raw_line.decode("utf-8")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        positions = [
            position for position in (line.find("="), line.find(":")) if position >= 0
        ]
        if not positions:
            raise SourceError(
                f'line {number} of {filename} is not "label = value" or "label: value" (length {len(line)})'
            )
        position = min(positions)
        name = line[:position].strip()
        value = line[position + 1 :].strip()
        if not name or not value or any(character.isspace() for character in value):
            raise SourceError(
                f'line {number} of {filename} is not "label = value" or "label: value" (length {len(line)})'
            )
        if name == label:
            matches.append((number, value))
    if not matches:
        raise SourceError(f'no line labelled "{label}" in {filename}')
    if len(matches) > 1:
        numbers = " and ".join(str(number) for number, _ in matches)
        raise SourceError(f'"{label}" is on lines {numbers} of {filename}')
    return matches[0][1], original, matches[0][0]


def _request(method, route, token=None, body=None):
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Vault-Token"] = token
    request = Request(
        OPENBAO_ADDR + route, data=payload, headers=headers, method=method
    )
    try:
        response = urlopen(request, timeout=30)
    except HTTPError as error:
        response = error
    except (URLError, OSError) as error:
        raise BaoError(f"cannot reach OpenBao: {error}") from error
    try:
        with response:
            status = response.status
            raw = response.read()
    except (OSError, HTTPException) as error:
        raise BaoError(f"cannot reach OpenBao: {error}") from error
    try:
        answer = json.loads(raw) if raw else None
    except (ValueError, UnicodeDecodeError) as error:
        raise BaoError("OpenBao returned unreadable JSON") from error
    return status, answer


def _read(route, token):
    status, answer = _request("GET", route, token)
    if status == 200:
        try:
            data = answer["data"]["data"]
            version = answer["data"]["metadata"]["version"]
            if not isinstance(data, dict) or not isinstance(version, int):
                raise TypeError
        except (KeyError, TypeError) as error:
            raise BaoError("OpenBao returned an unreadable entry") from error
        return status, data, version
    if status == 404 and answer == {"errors": []}:
        return status, {}, 0
    if status == 404:
        try:
            data = answer["data"]["data"]
            version = answer["data"]["metadata"]["version"]
            if data is not None or not isinstance(version, int):
                raise TypeError
        except (KeyError, TypeError) as error:
            raise BaoError("OpenBao could not read the entry") from error
        return status, {}, version
    raise BaoError(f"OpenBao read failed with status {status}")


def _remove_source(filename, original, line_number):
    source = Path(filename)
    if source.read_bytes() != original:
        raise OSError("source changed while loading")
    if line_number is None:
        source.unlink()
        print(f"deleted {filename}")
        return
    remaining = b"".join(
        line
        for index, line in enumerate(original.splitlines(keepends=True), 1)
        if index != line_number
    )
    if all(
        not line.strip() or line.lstrip().startswith(b"#")
        for line in remaining.splitlines()
    ):
        source.unlink()
        print(f"deleted {filename}")
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=source.parent, prefix=f".{source.name}.", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(remaining)
            output.flush()
            os.fchmod(output.fileno(), source.stat().st_mode & 0o7777)
        os.replace(temporary, source)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    print(f"removed line {line_number} of {filename}")


def main(argv=None):
    try:
        options = _parser().parse_args(argv)
    except SystemExit as error:
        return error.code
    try:
        value, original, line_number = _source(options.source, options.label)
        path, key, destination = _destination(options.to)
    except SourceError as error:
        print(f"secret-load: {error}", file=sys.stderr)
        return 2
    if options.to.startswith("vaultwarden:"):
        result = _vaultwarden(path, key, destination, value, options)
        if result == 0 and options.remove_source:
            if options.dry_run:
                action = (
                    f"would remove line {line_number} of {options.source}"
                    if line_number is not None
                    else f"would delete {options.source}"
                )
                print(f"dry run: {action}")
            else:
                try:
                    _remove_source(options.source, original, line_number)
                except OSError as error:
                    print(
                        f"secret-load: cannot remove {options.source}: {error.strerror or error}",
                        file=sys.stderr,
                    )
                    return 1
        return result
    try:
        item = vault_item.read_item(LOGIN_ITEM)
    except vault_item.VaultItemError as error:
        print(f"secret-load: {error}", file=sys.stderr)
        return 1
    password = (item.get("login") or {}).get("password")
    if not isinstance(password, str):
        print(f'secret-load: "{LOGIN_ITEM}" has no password', file=sys.stderr)
        return 1
    try:
        status, answer = _request(
            "POST", "/v1/auth/userpass/login/keepbreath0", body={"password": password}
        )
    except BaoError as error:
        print(f"secret-load: {error}", file=sys.stderr)
        return 1
    print(f"login: {status}")
    if (
        status != 200
        or not isinstance(answer, dict)
        or not isinstance(answer.get("auth"), dict)
        or not isinstance(answer["auth"].get("client_token"), str)
    ):
        print("secret-load: OpenBao sign-in failed", file=sys.stderr)
        return 1
    token = answer["auth"]["client_token"]
    result = 1
    route = "/v1/secret/data/" + "/".join(
        quote(segment, safe="") for segment in path.split("/")
    )
    try:
        _, data, version = _read(route, token)
        current = data.get(key)
        if current is not None and current != value and not options.replace:
            print(
                f"secret-load: {destination} holds a different value; use --replace to rotate it",
                file=sys.stderr,
            )
        elif options.dry_run:
            action = (
                "already holds this value"
                if current == value
                else "would replace a different value"
                if current is not None
                else "would write a new key"
            )
            print(f"dry run: {destination}: {action}, length {len(value)}")
            result = 0
        elif current == value:
            print(f"{destination}: already holds this value, length {len(value)}")
            result = 0
        else:
            merged = {**data, key: value}
            write_status, write_answer = _request(
                "POST", route, token, {"options": {"cas": version}, "data": merged}
            )
            if (
                write_status == 400
                and isinstance(write_answer, dict)
                and "check-and-set parameter did not match the current version"
                in write_answer.get("errors", [])
            ):
                print(
                    f"secret-load: {destination} changed while loading; nothing written",
                    file=sys.stderr,
                )
            elif write_status != 200:
                print(f"{destination}: write {write_status}")
            else:
                read_status, read_data, read_version = _read(route, token)
                matches = read_data.get(key) == value
                print(
                    f"{destination}: write {write_status}, read back {read_status}, matches {matches}, length {len(value)}, version {read_version}"
                )
                result = 0 if matches else 1
    except BaoError as error:
        print(f"secret-load: {error}", file=sys.stderr)
    finally:
        try:
            revoke_status, _ = _request("POST", "/v1/auth/token/revoke-self", token)
            print(f"revoke: {revoke_status}")
            if revoke_status != 204:
                result = 1
        except BaoError as error:
            print(f"secret-load: {error}", file=sys.stderr)
            result = 1
    if result == 0 and options.remove_source:
        if options.dry_run:
            action = (
                f"would remove line {line_number} of {options.source}"
                if line_number is not None
                else f"would delete {options.source}"
            )
            print(f"dry run: {action}")
        else:
            try:
                _remove_source(options.source, original, line_number)
            except OSError as error:
                print(
                    f"secret-load: cannot remove {options.source}: {error.strerror or error}",
                    file=sys.stderr,
                )
                return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
