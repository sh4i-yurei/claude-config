#!/usr/bin/python3
"""Load one staged secret into OpenBao without displaying its value."""

import argparse
import json
import os
from pathlib import Path
import re
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


def _parser():
    parser = argparse.ArgumentParser(prog="secret-load")
    parser.add_argument("--from", dest="source", required=True, metavar="FILE")
    parser.add_argument("--label", metavar="LABEL")
    parser.add_argument("--to", required=True, metavar="openbao:PATH[#KEY]")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace a different existing value. OpenBao keeps the old version; Vaultwarden keeps no history for a custom field, so its old value is lost.",
    )
    parser.add_argument(
        "--remove-source",
        action="store_true",
        help="After a verified match, remove the label's line, or the whole file. Removal does not scrub the old data from a btrfs disk.",
    )
    return parser


def _destination(text):
    if text.startswith("vaultwarden:"):
        raise SourceError("vaultwarden: destinations are not built yet")
    if not text.startswith("openbao:"):
        raise SourceError("--to must be openbao:PATH[#KEY]")
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
    endings = re.findall(rb"\r\n|\r|\n", original)
    remaining = b"".join(
        line + (endings[index - 1] if index <= len(endings) else b"")
        for index, line in enumerate(original.splitlines(), 1)
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
