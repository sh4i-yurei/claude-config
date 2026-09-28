#!/usr/bin/env python3
"""Return one sourced fact through a fixed, inspectable lookup route.

Usage: python3 lookup.py <kind> <arguments> [--fresh] [--text]
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlsplit

from common import append_log, load_config, repository_name, vault_root
from gw import credential_item_id, normalize_url, public_address, session_token

EXIT_STATUS = {"found": 0, "not found": 3, "refused": 4, "error": 1}
LOCAL_KINDS = {"vault", "ansible", "help", "doctor"}
VAULT_SEARCH_ROOTS = (
    "70_Research",
    "10_Projects",
    "40_Reference",
    "60_Operational_Manual",
)
HELP_NAME = re.compile(r"^[A-Za-z0-9._+-]+$")
FRESHNESS_DAYS = {
    "eol": 7,
    "pkg": 1,
    "vuln": 1,
    "cve": 1,
    "repo": 1,
    "rfc": 30,
    "paper": 30,
    "cites": 7,
    "fulltext": 90,
    "search": 1,
    "page": 7,
    "cert": 1,
    "ip": 1,
    "domain": 7,
    "docs": 7,
}
BUILD_KINDS = set(FRESHNESS_DAYS)


class BadArguments(ValueError):
    """The caller supplied a kind or arguments outside the command contract."""


@dataclass
class RemoteResponse:
    """One gateway response or a refusal that produced no envelope."""

    source_name: str
    url: str
    path: Path | None
    envelope: dict[str, Any] | None
    cached: bool
    failure: str | None = None
    reason: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


def lookup_key(parts: list[str]) -> str:
    """Make the stable, bounded key used in lookup archive filenames."""
    key = re.sub(r"[^a-z0-9]+", "-", " ".join(parts).lower()).strip("-")[:60]
    return key or "lookup"


def lookup_identity(
    kind: str, parts: list[str], *, subject: str | None = None
) -> dict[str, Any]:
    """Return the exact identity that prevents lossy filename-key cache collisions."""
    identity: dict[str, Any] = {"kind": kind, "arguments": parts}
    if subject is not None:
        identity["subject"] = subject
    return identity


def archive_path(
    kind: str,
    parts: list[str],
    *,
    root: Path | None = None,
    at: datetime | None = None,
    run: str | None = None,
) -> Path:
    """Return the path for one future gateway envelope without creating it."""
    root = root or vault_root()
    at = at or utc_now()
    key = lookup_key(parts)
    run = os.environ.get("RESEARCH_RUN") if run is None else run
    if run:
        relative_run = Path(run)
        if relative_run.is_absolute() or ".." in relative_run.parts:
            raise BadArguments("RESEARCH_RUN must name a topic inside 70_Research")
        directory = root / "70_Research" / relative_run / "sources" / "raw"
        name = f"{kind}-{key}--{at:%Y%m%dT%H%M%S}.json"
    else:
        directory = root / "70_Research" / "_lookups" / f"{at:%Y-%m}" / kind
        name = f"{key}--{at:%Y%m%dT%H%M%S}.json"
    return directory / name


def newest_cached_envelope(
    kind: str,
    parts: list[str],
    freshness_days: float,
    *,
    root: Path | None = None,
    now: datetime | None = None,
    url: str | None = None,
    validator: Callable[[dict[str, Any]], bool] | None = None,
    subject: str | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    """Read the newest unexpired default lookup envelope for a kind and key."""
    root = root or vault_root()
    now = now or utc_now()
    key = lookup_key(parts)
    run = os.environ.get("RESEARCH_RUN")
    if run:
        relative_run = Path(run)
        if relative_run.is_absolute() or ".." in relative_run.parts:
            raise BadArguments("RESEARCH_RUN must name a topic inside 70_Research")
        patterns = [
            f"70_Research/{relative_run.as_posix()}/sources/raw/{kind}-{key}--*.json"
        ]
    else:
        patterns = [f"70_Research/_lookups/????-??/{kind}/{key}--*.json"]
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    paths = (path for pattern in patterns for path in root.glob(pattern))
    for path in paths:
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            retrieved = datetime.fromisoformat(
                str(envelope["requested_at"]).replace("Z", "+00:00")
            )
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            continue
        if envelope.get("lookup") != lookup_identity(kind, parts, subject=subject):
            continue
        if url is not None and envelope.get("url") != url:
            continue
        http = envelope.get("status")
        if not isinstance(http, int) or (not 200 <= http < 300 and http != 404):
            continue
        if validator is not None and not validator(envelope):
            continue
        if now - retrieved <= timedelta(days=freshness_days):
            candidates.append((retrieved, path, envelope))
    if not candidates:
        return None
    _retrieved, path, envelope = max(candidates, key=lambda item: item[0])
    return path, envelope


def reserve_archive_path(
    kind: str,
    parts: list[str],
    *,
    root: Path | None = None,
    at: datetime | None = None,
) -> Path:
    """Atomically reserve a whole-second archive name for one request."""
    at = at or utc_now()
    while True:
        path = archive_path(kind, parts, root=root, at=at)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.touch(exist_ok=False)
        except FileExistsError:
            at += timedelta(seconds=1)
        else:
            return path


def log_cached_response(response: RemoteResponse, *, root: Path) -> None:
    """Record each cache read, including one rung of a partly cached chain."""
    envelope = response.envelope or {}
    archive = None
    if response.path is not None:
        try:
            archive = str(response.path.resolve().relative_to(root.resolve()))
        except ValueError:
            archive = str(response.path)
    append_log(
        {
            "ts": timestamp(),
            "via": "lookup",
            "host": urlsplit(response.url).hostname or "",
            "url": response.url,
            "status": envelope.get("status"),
            "duration_s": 0.0,
            "attempt": 0,
            "run": os.environ.get("RESEARCH_RUN"),
            "repo": repository_name(),
            "archive": archive,
        }
    )


def gateway_response(
    kind: str,
    parts: list[str],
    source_name: str,
    url: str,
    *,
    curl_args: list[str] | None = None,
    fresh: bool = False,
    root: Path | None = None,
    cache_validator: Callable[[dict[str, Any]], bool] | None = None,
    subject: str | None = None,
) -> RemoteResponse:
    """Read a fresh envelope or make exactly one request through gw.py."""
    root = root or vault_root()
    if not fresh:
        cached = newest_cached_envelope(
            kind,
            parts,
            FRESHNESS_DAYS[kind],
            root=root,
            url=url,
            validator=cache_validator,
            subject=subject,
        )
        if cached is not None:
            path, envelope = cached
            response = RemoteResponse(source_name, url, path, envelope, True)
            log_cached_response(response, root=root)
            return response

    path = reserve_archive_path(kind, parts, root=root)
    command = [
        sys.executable,
        str(Path(__file__).with_name("gw.py")),
        str(path),
        "--",
        url,
        *(curl_args or []),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    envelope: dict[str, Any] | None = None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            envelope = loaded
    except (OSError, json.JSONDecodeError):
        if path.exists() and path.stat().st_size == 0:
            path.unlink()
    if envelope is None:
        not_configured = completed.returncode == 2 and any(
            marker in completed.stderr
            for marker in (
                "item unavailable",
                "Vaultwarden session unavailable; run vu",
                "contact email unavailable",
                "contact email is not configured",
            )
        )
        failure = (
            "not configured"
            if not_configured
            else "refused"
            if completed.returncode in {2, 3, 4}
            else "error"
        )
        reason = (
            "\n".join(
                line.removeprefix("[gw]").lstrip()
                for raw in completed.stderr.splitlines()
                if (line := raw.strip())
            )
            or None
        )
        return RemoteResponse(source_name, url, None, None, False, failure, reason)
    envelope["lookup"] = lookup_identity(kind, parts, subject=subject)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    failure = "refused" if completed.returncode in {3, 4} else None
    return RemoteResponse(source_name, url, path, envelope, False, failure)


def response_archive(response: RemoteResponse) -> str | None:
    if response.path is None or response.envelope is None:
        return None
    try:
        return str(response.path.resolve().relative_to(vault_root().resolve()))
    except ValueError:
        return str(response.path)


def remote_attempt(response: RemoteResponse, status: str, http: Any) -> dict[str, Any]:
    attempt = {"source": response.source_name, "status": status, "http": http}
    if response.reason is not None:
        attempt["reason"] = response.reason
    archive = response_archive(response)
    if archive is not None:
        attempt["archive"] = archive
    return attempt


def remote_json(response: RemoteResponse) -> tuple[Any | None, dict[str, Any]]:
    """Decode a gateway envelope and return its preliminary tried record."""
    if response.failure:
        return None, remote_attempt(
            response, response.failure, (response.envelope or {}).get("status")
        )
    envelope = response.envelope or {}
    http = envelope.get("status")
    if http == 404:
        return None, remote_attempt(response, "not found", http)
    if not isinstance(http, int) or not 200 <= http < 300:
        return None, remote_attempt(response, "error", http)
    try:
        payload = json.loads(envelope["body"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None, remote_attempt(response, "error", http)
    return payload, remote_attempt(response, "found", http)


def remote_text(response: RemoteResponse) -> tuple[str | None, dict[str, Any]]:
    if response.failure:
        return None, remote_attempt(
            response, response.failure, (response.envelope or {}).get("status")
        )
    envelope = response.envelope or {}
    http = envelope.get("status")
    if http == 404:
        return None, remote_attempt(response, "not found", http)
    body = envelope.get("body")
    if not isinstance(http, int) or not 200 <= http < 300 or not isinstance(body, str):
        return None, remote_attempt(response, "error", http)
    if not body.strip():
        return None, remote_attempt(response, "not found", http)
    return body, remote_attempt(response, "found", http)


def source_from_response(response: RemoteResponse) -> dict[str, Any] | None:
    archive = response_archive(response)
    if archive is None:
        return None
    return {
        "name": response.source_name,
        "url": response.envelope.get("url", response.url),
        "retrieved": response.envelope.get("requested_at"),
        "archive": archive,
    }


def final_status(tried: list[dict[str, Any]]) -> str:
    statuses = [attempt["status"] for attempt in tried]
    if statuses and all(status == "refused" for status in statuses):
        return "refused"
    if "not found" in statuses:
        return "not found"
    return "error"


def mark_attempt(attempt: dict[str, Any], status: str) -> dict[str, Any]:
    attempt["status"] = status
    return attempt


def source(name: str, url: str, *, archive: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "url": url,
        "retrieved": timestamp(),
        "archive": archive,
    }


def result(
    kind: str,
    query: dict[str, Any],
    status: str,
    answer: Any,
    source_value: dict[str, Any] | None,
    tried: list[dict[str, Any]],
    *,
    cached: bool = False,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "query": query,
        "status": status,
        "cached": cached,
        "answer": answer,
        "source": source_value,
        "tried": tried,
    }


def local_status_code(status: str) -> int:
    return {"found": 200, "not found": 404, "refused": 403, "error": 500}[status]


def log_local(outcome: dict[str, Any], locator: str) -> None:
    source_value = outcome.get("source") or {}
    parsed = urlsplit(locator) if locator.startswith("https://") else None
    append_log(
        {
            "ts": timestamp(),
            "via": "lookup",
            "host": parsed.hostname if parsed else "",
            "url": locator,
            "status": local_status_code(outcome["status"]),
            "duration_s": 0.0,
            "attempt": 0,
            "run": os.environ.get("RESEARCH_RUN"),
            "repo": repository_name(),
            "archive": source_value.get("archive"),
        }
    )


def vault_lookup(arguments: list[str], *, root: Path | None = None) -> dict[str, Any]:
    if not arguments:
        raise BadArguments("vault needs one or more search words")
    root = root or vault_root()
    words = [word.casefold() for word in arguments]
    matches: list[dict[str, Any]] = []
    for folder in VAULT_SEARCH_ROOTS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(
            candidate for candidate in base.rglob("*") if candidate.is_file()
        ):
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            folded = text.casefold()
            if not all(word in folded for word in words):
                continue
            lines = text.splitlines()
            number, snippet = max(
                enumerate(lines, 1),
                key=lambda item: sum(word in item[1].casefold() for word in words),
                default=(1, ""),
            )
            matches.append(
                {
                    "file": str(path.relative_to(root)),
                    "line": number,
                    "snippet": snippet.strip()[:300],
                }
            )
            if len(matches) == 20:
                break
        if len(matches) == 20:
            break
    status = "found" if matches else "not found"
    return result(
        "vault",
        {"words": arguments},
        status,
        {"matches": matches},
        source("vault", "vault:" + " ".join(arguments)) if matches else None,
        [{"source": "vault", "status": status, "http": None}],
    )


def description(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return "" if value is None else str(value)


def ansible_lookup(arguments: list[str]) -> dict[str, Any]:
    if len(arguments) != 1:
        raise BadArguments("ansible needs exactly one module name")
    module = arguments[0]
    completed = subprocess.run(
        ["ansible-doc", "-j", module], capture_output=True, text=True, check=False
    )
    try:
        payload = json.loads(completed.stdout) if completed.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    document = (
        payload.get(module) or next(iter(payload.values()), None)
        if isinstance(payload, dict)
        else None
    )
    if completed.returncode != 0 or not isinstance(document, dict):
        status = "not found" if completed.returncode else "error"
        return result(
            "ansible",
            {"module": module},
            status,
            None,
            None,
            [{"source": "ansible-doc", "status": status, "http": None}],
        )
    options = []
    for name, option in sorted((document.get("doc", {}).get("options") or {}).items()):
        options.append(
            {
                "name": name,
                "type": option.get("type"),
                "default": option.get("default"),
                "required": bool(option.get("required", False)),
                "description": description(option.get("description")),
            }
        )
    return result(
        "ansible",
        {"module": module},
        "found",
        {"module": module, "options": options},
        source("ansible-doc", f"ansible-doc:{module}"),
        [{"source": "ansible-doc", "status": "found", "http": None}],
    )


def help_lookup(arguments: list[str]) -> dict[str, Any]:
    if len(arguments) != 1 or not HELP_NAME.fullmatch(arguments[0]):
        raise BadArguments(
            "help needs one command name containing only letters, digits, ._+-"
        )
    command = arguments[0]
    executable = shutil.which(command)
    if not executable:
        return result(
            "help",
            {"command": command},
            "not found",
            None,
            None,
            [{"source": "PATH", "status": "not found", "http": None}],
        )
    attempts: list[dict[str, Any]] = []
    try:
        man = subprocess.run(
            ["man", "-P", "cat", command],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        man = subprocess.CompletedProcess(
            ["man", "-P", "cat", command], 127, stdout="", stderr="man unavailable"
        )
    attempts.append(
        {
            "source": "man",
            "status": "found" if man.returncode == 0 and man.stdout else "not found",
            "http": None,
        }
    )
    selected = man.stdout if man.returncode == 0 and man.stdout else ""
    selected_source = "man"
    if not selected:
        help_result = subprocess.run(
            [executable, "--help"], capture_output=True, text=True, check=False
        )
        selected = help_result.stdout or help_result.stderr
        selected_source = f"{command} --help"
        attempts.append(
            {
                "source": selected_source,
                "status": "found" if selected else "error",
                "http": None,
            }
        )
    if not selected:
        return result("help", {"command": command}, "error", None, None, attempts)
    lines = selected.splitlines()[:200]
    return result(
        "help",
        {"command": command},
        "found",
        {"lines": lines},
        source(selected_source, f"command:{command}"),
        attempts,
    )


def credential_statuses(
    config: dict[str, Any], *, bw_available: bool = True
) -> tuple[bool, dict[str, dict[str, Any]]]:
    items = sorted(
        {
            provider["key_item"]
            for provider in config["providers"].values()
            if provider.get("key_item")
        }
    )
    if not bw_available:
        return False, {
            item: {"available": False, "reason": "bw unavailable"} for item in items
        }
    try:
        token = session_token()
    except ValueError:
        return False, {
            item: {"available": False, "reason": "session unavailable"}
            for item in items
        }
    env = {**os.environ, "BW_SESSION": token, "BW_NOINTERACTION": "true"}
    status = subprocess.run(
        ["bw", "status"], env=env, capture_output=True, text=True, check=False
    )
    try:
        status_payload = json.loads(status.stdout)
        unlocked = (
            status.returncode == 0
            and isinstance(status_payload, dict)
            and status_payload.get("status") == "unlocked"
        )
    except json.JSONDecodeError:
        unlocked = False
    if not unlocked:
        return False, {
            item: {"available": False, "reason": "session unavailable"}
            for item in items
        }
    statuses = {}
    for item in items:
        try:
            item_id = credential_item_id(item, env)
        except ValueError:
            statuses[item] = {"available": False, "reason": "item unavailable"}
            continue
        completed = subprocess.run(
            ["bw", "get", "password", item_id],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        available = completed.returncode == 0 and bool(completed.stdout.strip())
        statuses[item] = {
            "available": available,
            "reason": None if available else "item unavailable",
        }
    return True, statuses


def doctor_lookup(arguments: list[str], *, root: Path | None = None) -> dict[str, Any]:
    if arguments:
        raise BadArguments("doctor takes no arguments")
    root = root or vault_root()
    tools = {
        name: {"available": shutil.which(name) is not None}
        for name in ("python3", "curl", "bw", "ansible-doc")
    }
    session_available, keys = credential_statuses(
        load_config(), bw_available=tools["bw"]["available"]
    )
    answer = {
        "tools": tools,
        "vault": {"available": root.is_dir(), "path": str(root)},
        "vaultwarden_session": {"available": session_available},
        "keys": keys,
    }
    return result(
        "doctor",
        {},
        "found",
        answer,
        source("machine", "machine:doctor"),
        [{"source": "machine", "status": "found", "http": None}],
    )


def eol_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) not in {1, 2}:
        raise BadArguments("eol needs a product and an optional cycle")
    product = arguments[0].lower()
    cycle = arguments[1] if len(arguments) == 2 else None
    url = f"https://endoflife.date/api/{quote(product, safe='')}.json"
    response = gateway_response(
        "eol", arguments, "endoflife.date", url, fresh=fresh, root=root
    )
    payload, attempt = remote_json(response)
    tried = [attempt]
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
        if cycle is not None:
            rows = [row for row in rows if str(row.get("cycle")) == cycle]
        answer_rows = [
            {
                "cycle": row.get("cycle"),
                "release": row.get("releaseDate"),
                "support": row.get("support"),
                "eol": row.get("eol"),
                "latest": row.get("latest"),
            }
            for row in rows
        ]
        if answer_rows:
            answer: Any = answer_rows[0] if cycle is not None else answer_rows
            return result(
                "eol",
                {"product": product, "cycle": cycle},
                "found",
                answer,
                source_from_response(response),
                tried,
                cached=response.cached,
            )
        mark_attempt(attempt, "not found")
    return result(
        "eol",
        {"product": product, "cycle": cycle},
        final_status(tried),
        None,
        None,
        tried,
        cached=response.cached,
    )


def package_answer(
    registry: str, payload: Any, version: str | None
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if registry == "pypi":
        info = payload.get("info")
        if not isinstance(info, dict):
            return None
        selected = version or info.get("version")
        if version is not None and str(info.get("version")) != version:
            return None
        releases = (
            payload.get("releases") if isinstance(payload.get("releases"), dict) else {}
        )
        files = releases.get(str(selected), []) if isinstance(releases, dict) else []
        if not files and isinstance(payload.get("urls"), list):
            files = payload["urls"]
        release = next(
            (
                item.get("upload_time_iso_8601") or item.get("upload_time")
                for item in files
                if isinstance(item, dict)
            ),
            None,
        )
        urls = (
            info.get("project_urls")
            if isinstance(info.get("project_urls"), dict)
            else {}
        )
        return {
            "name": info.get("name"),
            "version": selected,
            "release": release,
            "license": info.get("license") or info.get("license_expression"),
            "homepage": info.get("home_page") or urls.get("Homepage"),
            "repository": urls.get("Repository") or urls.get("Source"),
        }
    if registry == "npm":
        versions = payload.get("versions")
        tags = payload.get("dist-tags")
        if not isinstance(versions, dict) or not isinstance(tags, dict):
            return None
        selected = version or tags.get("latest")
        info = versions.get(str(selected))
        if not isinstance(info, dict):
            return None
        repository = info.get("repository")
        if isinstance(repository, dict):
            repository = repository.get("url")
        times = payload.get("time") if isinstance(payload.get("time"), dict) else {}
        return {
            "name": info.get("name"),
            "version": selected,
            "release": times.get(str(selected)),
            "license": info.get("license"),
            "homepage": info.get("homepage"),
            "repository": repository,
        }
    crate = payload.get("crate")
    versions = payload.get("versions")
    if not isinstance(crate, dict) or not isinstance(versions, list):
        return None
    selected = version or crate.get("newest_version") or crate.get("max_version")
    release = next(
        (
            item.get("created_at")
            for item in versions
            if isinstance(item, dict) and str(item.get("num")) == str(selected)
        ),
        None,
    )
    if not any(
        isinstance(item, dict) and str(item.get("num")) == str(selected)
        for item in versions
    ):
        return None
    return {
        "name": crate.get("name"),
        "version": selected,
        "release": release,
        "license": next(
            (
                item.get("license")
                for item in versions
                if isinstance(item, dict) and str(item.get("num")) == str(selected)
            ),
            None,
        ),
        "homepage": crate.get("homepage"),
        "repository": crate.get("repository"),
    }


def pkg_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) not in {2, 3} or arguments[0] not in {"pypi", "npm", "crates"}:
        raise BadArguments(
            "pkg needs pypi, npm or crates; a name; and an optional version"
        )
    registry, name = arguments[:2]
    version = arguments[2] if len(arguments) == 3 else None
    encoded = quote(name, safe="")
    urls = {
        "pypi": (
            f"https://pypi.org/pypi/{encoded}/{quote(version, safe='')}/json"
            if version
            else f"https://pypi.org/pypi/{encoded}/json"
        ),
        "npm": f"https://registry.npmjs.org/{encoded}",
        "crates": f"https://crates.io/api/v1/crates/{encoded}",
    }
    response = gateway_response(
        "pkg", arguments, registry, urls[registry], fresh=fresh, root=root
    )
    payload, attempt = remote_json(response)
    answer = package_answer(registry, payload, version)
    if answer is not None:
        return result(
            "pkg",
            {"registry": registry, "name": name, "version": version},
            "found",
            answer,
            source_from_response(response),
            [attempt],
            cached=response.cached,
        )
    if payload is not None:
        mark_attempt(attempt, "not found")
    return result(
        "pkg",
        {"registry": registry, "name": name, "version": version},
        final_status([attempt]),
        None,
        None,
        [attempt],
        cached=response.cached,
    )


def normalize_osv(vulnerabilities: Any) -> list[dict[str, Any]]:
    if not isinstance(vulnerabilities, list):
        return []
    return [
        {
            "id": item.get("id"),
            "summary": item.get("summary"),
            "severity": item.get("severity", []),
            "affected": item.get("affected", [])
            if isinstance(item.get("affected"), list)
            else [],
            "fixed": [
                event.get("fixed")
                for affected in (
                    item.get("affected", [])
                    if isinstance(item.get("affected"), list)
                    else []
                )
                if isinstance(affected, dict)
                for value_range in (
                    affected.get("ranges", [])
                    if isinstance(affected.get("ranges"), list)
                    else []
                )
                if isinstance(value_range, dict)
                for event in (
                    value_range.get("events", [])
                    if isinstance(value_range.get("events"), list)
                    else []
                )
                if isinstance(event, dict) and event.get("fixed")
            ],
        }
        for item in vulnerabilities
        if isinstance(item, dict)
    ]


def normalize_github_advisories(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    return [
        {
            "id": item.get("ghsa_id") or item.get("cve_id"),
            "summary": item.get("summary"),
            "severity": item.get("severity"),
            "affected": item.get("vulnerabilities", []),
            "fixed": [
                vulnerability.get("first_patched_version", {}).get("identifier")
                for vulnerability in (
                    item.get("vulnerabilities", [])
                    if isinstance(item.get("vulnerabilities"), list)
                    else []
                )
                if isinstance(vulnerability, dict)
                and isinstance(vulnerability.get("first_patched_version"), dict)
            ],
        }
        for item in payload
        if isinstance(item, dict)
    ]


def vuln_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) not in {2, 3}:
        raise BadArguments("vuln needs an ecosystem, package and optional version")
    ecosystem, package = arguments[:2]
    version = arguments[2] if len(arguments) == 3 else None
    query: dict[str, Any] = {"package": {"ecosystem": ecosystem, "name": package}}
    if version:
        query["version"] = version
    osv_url = "https://api.osv.dev/v1/query"
    osv = gateway_response(
        "vuln",
        arguments,
        "OSV",
        osv_url,
        curl_args=["--json", json.dumps(query, separators=(",", ":"))],
        fresh=fresh,
        root=root,
    )
    payload, attempt = remote_json(osv)
    tried = [attempt]
    advisories = (
        normalize_osv(payload.get("vulns")) if isinstance(payload, dict) else []
    )
    if advisories:
        return result(
            "vuln",
            {"ecosystem": ecosystem, "package": package, "version": version},
            "found",
            {"advisories": advisories},
            source_from_response(osv),
            tried,
            cached=osv.cached,
        )
    if payload is not None:
        mark_attempt(attempt, "not found")

    github_ecosystems = {
        "PyPI": "pip",
        "npm": "npm",
        "crates.io": "rust",
        "Rust": "rust",
    }
    params = {
        "ecosystem": github_ecosystems.get(ecosystem, ecosystem.lower()),
        "per_page": 100,
    }
    params["affects"] = f"{package}@{version}" if version else package
    github_url = "https://api.github.com/advisories?" + urlencode(params)
    github = gateway_response(
        "vuln", arguments, "GitHub advisories", github_url, fresh=fresh, root=root
    )
    github_payload, github_attempt = remote_json(github)
    tried.append(github_attempt)
    advisories = normalize_github_advisories(github_payload)
    if advisories:
        return result(
            "vuln",
            {"ecosystem": ecosystem, "package": package, "version": version},
            "found",
            {"advisories": advisories},
            source_from_response(github),
            tried,
            cached=osv.cached and github.cached,
        )
    if github_payload is not None:
        mark_attempt(github_attempt, "not found")
    return result(
        "vuln",
        {"ecosystem": ecosystem, "package": package, "version": version},
        final_status(tried),
        None,
        None,
        tried,
        cached=osv.cached and github.cached,
    )


def nvd_cve(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not isinstance(
        payload.get("vulnerabilities"), list
    ):
        return None
    item = next(
        (
            entry.get("cve")
            for entry in payload["vulnerabilities"]
            if isinstance(entry, dict) and isinstance(entry.get("cve"), dict)
        ),
        None,
    )
    if not isinstance(item, dict):
        return None
    descriptions = (
        item.get("descriptions") if isinstance(item.get("descriptions"), list) else []
    )
    description_value = next(
        (
            entry.get("value")
            for entry in descriptions
            if isinstance(entry, dict) and entry.get("lang") == "en"
        ),
        None,
    )
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    metric = next(
        (
            row.get("cvssData")
            for rows in metrics.values()
            if isinstance(rows, list)
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("cvssData"), dict)
        ),
        {},
    )
    return {
        "id": item.get("id"),
        "description": description_value,
        "severity": metric.get("baseSeverity"),
        "score": metric.get("baseScore"),
        "published": item.get("published"),
        "modified": item.get("lastModified"),
        "references": [
            entry.get("url")
            for entry in item.get("references", [])
            if isinstance(entry, dict) and entry.get("url")
        ],
    }


def osv_cve(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not payload.get("id"):
        return None
    return {
        "id": payload.get("id"),
        "description": payload.get("details") or payload.get("summary"),
        "severity": payload.get("severity", []),
        "score": None,
        "published": payload.get("published"),
        "modified": payload.get("modified"),
        "references": [
            entry.get("url")
            for entry in payload.get("references", [])
            if isinstance(entry, dict) and entry.get("url")
        ],
    }


def cve_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) != 1 or not re.fullmatch(
        r"CVE-\d{4}-\d{4,}", arguments[0], re.IGNORECASE
    ):
        raise BadArguments("cve needs one CVE identifier")
    identifier = arguments[0].upper()
    key_parts = [identifier]
    nvd_url = "https://services.nvd.nist.gov/rest/json/cves/2.0?" + urlencode(
        {"cveId": identifier}
    )
    primary = gateway_response("cve", key_parts, "NVD", nvd_url, fresh=fresh, root=root)
    responses = [primary]
    payload, attempt = remote_json(primary)
    tried = [attempt]
    answer = nvd_cve(payload)
    if answer is None:
        if payload is not None:
            mark_attempt(attempt, "not found")
        osv_url = f"https://api.osv.dev/v1/vulns/{quote(identifier, safe='')}"
        fallback = gateway_response(
            "cve", key_parts, "OSV", osv_url, fresh=fresh, root=root
        )
        responses.append(fallback)
        osv_payload, osv_attempt = remote_json(fallback)
        tried.append(osv_attempt)
        answer = osv_cve(osv_payload)
        if answer is None and osv_payload is not None:
            mark_attempt(osv_attempt, "not found")
        if answer is not None:
            primary = fallback
    if answer is None:
        return result(
            "cve",
            {"id": identifier},
            final_status(tried),
            None,
            None,
            tried,
            cached=all(response.cached for response in responses),
        )

    epss_url = "https://api.first.org/data/v1/epss?" + urlencode({"cve": identifier})
    epss = gateway_response(
        "cve", key_parts, "FIRST EPSS", epss_url, fresh=fresh, root=root
    )
    responses.append(epss)
    epss_payload, epss_attempt = remote_json(epss)
    tried.append(epss_attempt)
    epss_row = (
        epss_payload.get("data", [None])[0]
        if isinstance(epss_payload, dict)
        and isinstance(epss_payload.get("data"), list)
        and epss_payload.get("data")
        else None
    )
    if isinstance(epss_row, dict):
        answer["epss"] = epss_row.get("epss")
        answer["epss_percentile"] = epss_row.get("percentile")
    else:
        answer["epss"] = None
        answer["epss_percentile"] = None
        if epss_payload is not None:
            mark_attempt(epss_attempt, "not found")
    return result(
        "cve",
        {"id": identifier},
        "found",
        answer,
        source_from_response(primary),
        tried,
        cached=all(response.cached for response in responses),
    )


REPOSITORY_QUERY = """
query RepositoryLookup($owner: String!, $name: String!, $expression: String!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner
    description
    url
    latestRelease { tagName publishedAt url }
    readme: object(expression: "HEAD:README.md") { ... on Blob { text byteSize } }
    target: object(expression: $expression) {
      ... on Blob { text byteSize }
      ... on Tree { entries { name type path } }
    }
  }
}
""".strip()


def repo_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) not in {1, 2} or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", arguments[0]
    ):
        raise BadArguments("repo needs owner/name and an optional repository path")
    owner, name = arguments[0].split("/", 1)
    path = arguments[1].strip("/") if len(arguments) == 2 else ""
    body = {
        "query": REPOSITORY_QUERY,
        "variables": {
            "owner": owner,
            "name": name,
            "expression": f"HEAD:{path}" if path else "HEAD:",
        },
    }
    url = "https://api.github.com/graphql"
    response = gateway_response(
        "repo",
        arguments,
        "GitHub GraphQL",
        url,
        curl_args=["--json", json.dumps(body, separators=(",", ":"))],
        fresh=fresh,
        root=root,
    )
    payload, attempt = remote_json(response)
    repository = (
        payload.get("data", {}).get("repository")
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict)
        else None
    )
    if isinstance(repository, dict):
        target = repository.get("target")
        if path and target is None:
            mark_attempt(attempt, "not found")
        else:
            answer = {
                "repository": repository.get("nameWithOwner"),
                "description": repository.get("description"),
                "url": repository.get("url"),
                "latest_release": repository.get("latestRelease"),
                "path": path or None,
                "content": target,
                "readme": repository.get("readme"),
            }
            return result(
                "repo",
                {"repository": arguments[0], "path": path or None},
                "found",
                answer,
                source_from_response(response),
                [attempt],
                cached=response.cached,
            )
    elif payload is not None:
        has_errors = isinstance(payload, dict) and bool(payload.get("errors"))
        mark_attempt(attempt, "error" if has_errors else "not found")
    return result(
        "repo",
        {"repository": arguments[0], "path": path or None},
        final_status([attempt]),
        None,
        None,
        [attempt],
        cached=response.cached,
    )


def docs_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) == 1:
        library_id = None
        question = arguments[0].strip()
        endpoint = "https://context7.com/api/v3/search"
        query = {"query": question, "type": "json"}
        source_name = "Context7 search"
    elif len(arguments) == 2 and arguments[0].startswith("/"):
        library_id = arguments[0].strip()
        question = arguments[1].strip()
        endpoint = "https://context7.com/api/v2/context"
        query = {"libraryId": library_id, "query": question, "type": "json"}
        source_name = "Context7 context"
    else:
        raise BadArguments("docs needs a question, or /library/id and a question")
    if not question or (library_id is not None and not library_id.strip("/")):
        raise BadArguments("docs needs a non-empty question and library ID")
    url = endpoint + "?" + urlencode(query)
    response = gateway_response(
        "docs",
        arguments,
        source_name,
        url,
        fresh=fresh,
        root=root,
    )
    payload, attempt = remote_json(response)
    if isinstance(payload, dict):
        snippets: list[dict[str, Any]] = []
        library_ids: list[str] = []
        for item in payload.get("codeSnippets", []):
            if not isinstance(item, dict):
                continue
            item_library = item.get("libraryId") or library_id
            if isinstance(item_library, str) and item_library not in library_ids:
                library_ids.append(item_library)
            snippets.append(
                {
                    "library_id": item_library,
                    "type": "code",
                    "title": item.get("codeTitle"),
                    "content": item.get("codeList", []),
                }
            )
        for item in payload.get("infoSnippets", []):
            if not isinstance(item, dict):
                continue
            item_library = item.get("libraryId") or library_id
            if isinstance(item_library, str) and item_library not in library_ids:
                library_ids.append(item_library)
            snippets.append(
                {
                    "library_id": item_library,
                    "type": "information",
                    "title": item.get("title"),
                    "content": item.get("content"),
                }
            )
        if snippets:
            return result(
                "docs",
                {"question": question, "library_id": library_id},
                "found",
                {"library_ids": library_ids, "snippets": snippets},
                source_from_response(response),
                [attempt],
                cached=response.cached,
            )
        mark_attempt(attempt, "not found")
    return result(
        "docs",
        {"question": question, "library_id": library_id},
        final_status([attempt]),
        None,
        source_from_response(response),
        [attempt],
        cached=response.cached,
    )


def datatracker_resource(
    name: str,
    path: str,
    label: str,
    *,
    fresh: bool,
    root: Path | None,
) -> tuple[str | None, RemoteResponse | None, dict[str, Any]]:
    if not path.startswith("/api/") or ".." in Path(path).parts:
        return None, None, {"source": label, "status": "error", "http": None}
    url = "https://datatracker.ietf.org" + path
    response = gateway_response("rfc", [name], label, url, fresh=fresh, root=root)
    payload, attempt = remote_json(response)
    if not isinstance(payload, dict):
        return None, response, attempt
    if label.endswith("state"):
        value = payload.get("desc") or payload.get("slug") or payload.get("name")
    else:
        value = payload.get("acronym") or payload.get("name")
    if not isinstance(value, str) or not value.strip():
        mark_attempt(attempt, "error")
        return None, response, attempt
    return value.strip(), response, attempt


def rfc_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) != 1 or not re.fullmatch(
        r"(?:rfc\d+|draft-[A-Za-z0-9._-]+)", arguments[0], re.IGNORECASE
    ):
        raise BadArguments("rfc needs rfcNNNN or a draft name")
    name = arguments[0].lower()
    url = "https://datatracker.ietf.org/api/v1/doc/document/?" + urlencode(
        {"format": "json", "name__iexact": name}
    )
    response = gateway_response(
        "rfc", [name], "IETF Datatracker", url, fresh=fresh, root=root
    )
    payload, attempt = remote_json(response)
    objects = payload.get("objects") if isinstance(payload, dict) else None
    document = (
        next((item for item in objects if isinstance(item, dict)), None)
        if isinstance(objects, list)
        else None
    )
    if document is not None:
        tried = [attempt]
        responses = [response]
        states = (
            document.get("states", [])
            if isinstance(document.get("states"), list)
            else []
        )
        status_values = []
        for state_path in states:
            if not isinstance(state_path, str):
                tried.append(
                    {
                        "source": "IETF Datatracker state",
                        "status": "error",
                        "http": None,
                    }
                )
                continue
            value, state_response, state_attempt = datatracker_resource(
                name,
                state_path,
                "IETF Datatracker state",
                fresh=fresh,
                root=root,
            )
            tried.append(state_attempt)
            if state_response is not None:
                responses.append(state_response)
            if value is not None:
                status_values.append(value)
        group_path = document.get("group")
        group_value = None
        if isinstance(group_path, str) and group_path:
            group_value, group_response, group_attempt = datatracker_resource(
                name,
                group_path,
                "IETF Datatracker group",
                fresh=fresh,
                root=root,
            )
            tried.append(group_attempt)
            if group_response is not None:
                responses.append(group_response)
        if any(item["status"] != "found" for item in tried):
            return result(
                "rfc",
                {"name": name},
                "error",
                None,
                None,
                tried,
                cached=all(item.cached for item in responses),
            )
        answer = {
            "name": document.get("name"),
            "title": document.get("title"),
            "status": status_values,
            "abstract": document.get("abstract"),
            "revision": document.get("rev"),
            "working_group": group_value,
        }
        return result(
            "rfc",
            {"name": name},
            "found",
            answer,
            source_from_response(response),
            tried,
            cached=all(item.cached for item in responses),
        )
    if payload is not None:
        mark_attempt(attempt, "not found")
    return result(
        "rfc",
        {"name": name},
        final_status([attempt]),
        None,
        None,
        [attempt],
        cached=response.cached,
    )


def paper_identifier(value: str) -> tuple[str, str, str]:
    raw = value.strip()
    arxiv = re.fullmatch(
        r"arXiv:((?:\d{4}\.\d{4,5}|[A-Za-z][A-Za-z0-9.-]*/\d{7})(?:v\d+)?)",
        raw,
        re.IGNORECASE,
    )
    if arxiv:
        identifier = arxiv.group(1)
        return "arxiv", identifier, f"arXiv:{identifier}"
    raw = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^doi:", "", raw, flags=re.IGNORECASE)
    if re.fullmatch(r"10\.\d{4,9}/\S+", raw, re.IGNORECASE):
        doi = raw.lower()
        return "doi", doi, f"DOI:{doi}"
    raise BadArguments("paper identifier must be a DOI or arXiv:ID")


def semantic_scholar_paper(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not payload.get("title"):
        return None
    return {
        "title": payload.get("title"),
        "year": payload.get("year"),
        "venue": payload.get("venue"),
        "authors": [
            author.get("name")
            for author in payload.get("authors", [])
            if isinstance(author, dict) and author.get("name")
        ],
        "abstract": payload.get("abstract"),
        "identifiers": payload.get("externalIds", {}),
        "open_access": (payload.get("openAccessPdf") or {}).get("url")
        if isinstance(payload.get("openAccessPdf"), dict)
        else None,
        "citations": payload.get("citationCount"),
    }


def openalex_paper(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not payload.get("title"):
        return None
    authorships = (
        payload.get("authorships")
        if isinstance(payload.get("authorships"), list)
        else []
    )
    location = payload.get("primary_location")
    source_value = location.get("source") if isinstance(location, dict) else None
    best_oa = payload.get("best_oa_location")
    return {
        "title": payload.get("title"),
        "year": payload.get("publication_year"),
        "venue": source_value.get("display_name")
        if isinstance(source_value, dict)
        else None,
        "authors": [
            author.get("author", {}).get("display_name")
            for author in authorships
            if isinstance(author, dict) and isinstance(author.get("author"), dict)
        ],
        "abstract": None,
        "identifiers": payload.get("ids", {}),
        "open_access": best_oa.get("pdf_url") if isinstance(best_oa, dict) else None,
        "citations": payload.get("cited_by_count"),
    }


def crossref_paper(payload: Any) -> dict[str, Any] | None:
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        return None
    titles = message.get("title") if isinstance(message.get("title"), list) else []
    title = next((item for item in titles if isinstance(item, str) and item), None)
    if title is None:
        return None
    date_parts = (
        message.get("published", {}).get("date-parts", [])
        if isinstance(message.get("published"), dict)
        else []
    )
    year = (
        date_parts[0][0]
        if date_parts and isinstance(date_parts[0], list) and date_parts[0]
        else None
    )
    containers = message.get("container-title")
    return {
        "title": title,
        "year": year,
        "venue": containers[0] if isinstance(containers, list) and containers else None,
        "authors": [
            " ".join(filter(None, (author.get("given"), author.get("family"))))
            for author in message.get("author", [])
            if isinstance(author, dict)
        ],
        "abstract": message.get("abstract"),
        "identifiers": {"DOI": message.get("DOI")},
        "open_access": next(
            (
                link.get("URL")
                for link in message.get("link", [])
                if isinstance(link, dict) and link.get("URL")
            ),
            None,
        ),
        "citations": message.get("is-referenced-by-count"),
    }


def arxiv_paper(body: str) -> dict[str, Any] | None:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    atom = "{http://www.w3.org/2005/Atom}"
    entry = root.find(f"{atom}entry")
    if entry is None:
        return None
    title = entry.findtext(f"{atom}title")
    if not title:
        return None
    published = entry.findtext(f"{atom}published") or ""
    identifier_url = entry.findtext(f"{atom}id") or ""
    identifier = (
        identifier_url.partition("/abs/")[2] or identifier_url.rsplit("/", 1)[-1]
    )
    links = [node.attrib for node in entry.findall(f"{atom}link")]
    return {
        "title": " ".join(title.split()),
        "year": int(published[:4]) if published[:4].isdigit() else None,
        "venue": "arXiv",
        "authors": [
            node.findtext(f"{atom}name")
            for node in entry.findall(f"{atom}author")
            if node.findtext(f"{atom}name")
        ],
        "abstract": " ".join((entry.findtext(f"{atom}summary") or "").split()),
        "identifiers": {"ArXiv": identifier},
        "open_access": next(
            (
                link.get("href")
                for link in links
                if link.get("type") == "application/pdf"
            ),
            None,
        ),
        "citations": None,
    }


def paper_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) != 1:
        raise BadArguments("paper needs one DOI or arXiv identifier")
    kind, identifier, semantic_id = paper_identifier(arguments[0])
    fields = "title,year,venue,authors,abstract,externalIds,openAccessPdf,citationCount"
    semantic_url = (
        f"https://api.semanticscholar.org/graph/v1/paper/{quote(semantic_id, safe='')}?"
        + urlencode({"fields": fields})
    )
    semantic = gateway_response(
        "paper", arguments, "Semantic Scholar", semantic_url, fresh=fresh, root=root
    )
    payload, attempt = remote_json(semantic)
    tried = [attempt]
    answer = semantic_scholar_paper(payload)
    if answer is not None:
        return result(
            "paper",
            {"identifier": arguments[0]},
            "found",
            answer,
            source_from_response(semantic),
            tried,
            cached=semantic.cached,
        )
    if payload is not None:
        mark_attempt(attempt, "not found")

    if kind == "doi":
        openalex_url = "https://api.openalex.org/works/" + quote(
            f"https://doi.org/{identifier}", safe=""
        )
        openalex = gateway_response(
            "paper", arguments, "OpenAlex", openalex_url, fresh=fresh, root=root
        )
        openalex_payload, openalex_attempt = remote_json(openalex)
        tried.append(openalex_attempt)
        answer = openalex_paper(openalex_payload)
        if answer is not None:
            return result(
                "paper",
                {"identifier": arguments[0]},
                "found",
                answer,
                source_from_response(openalex),
                tried,
                cached=semantic.cached and openalex.cached,
            )
        if openalex_payload is not None:
            mark_attempt(openalex_attempt, "not found")
        crossref_url = f"https://api.crossref.org/works/{quote(identifier, safe='')}"
        crossref = gateway_response(
            "paper", arguments, "Crossref", crossref_url, fresh=fresh, root=root
        )
        crossref_payload, crossref_attempt = remote_json(crossref)
        tried.append(crossref_attempt)
        answer = crossref_paper(crossref_payload)
        if answer is not None:
            return result(
                "paper",
                {"identifier": arguments[0]},
                "found",
                answer,
                source_from_response(crossref),
                tried,
                cached=semantic.cached and openalex.cached and crossref.cached,
            )
        if crossref_payload is not None:
            mark_attempt(crossref_attempt, "not found")
        responses = [semantic, openalex, crossref]
    else:
        arxiv_url = "https://export.arxiv.org/api/query?" + urlencode(
            {"id_list": identifier}
        )
        arxiv = gateway_response(
            "paper", arguments, "arXiv API", arxiv_url, fresh=fresh, root=root
        )
        body, arxiv_attempt = remote_text(arxiv)
        tried.append(arxiv_attempt)
        answer = arxiv_paper(body) if body is not None else None
        if answer is not None:
            return result(
                "paper",
                {"identifier": arguments[0]},
                "found",
                answer,
                source_from_response(arxiv),
                tried,
                cached=semantic.cached and arxiv.cached,
            )
        if body is not None:
            mark_attempt(arxiv_attempt, "not found")
        responses = [semantic, arxiv]
    return result(
        "paper",
        {"identifier": arguments[0]},
        final_status(tried),
        None,
        None,
        tried,
        cached=all(response.cached for response in responses),
    )


def citation_rows(payload: Any, *, references: bool) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return []
    field = "citedPaper" if references else "citingPaper"
    return [
        {
            "id": paper.get("paperId"),
            "title": paper.get("title"),
            "identifiers": paper.get("externalIds", {}),
        }
        for row in payload["data"]
        if isinstance(row, dict) and isinstance(row.get(field), dict)
        for paper in [row[field]]
    ]


def opencitations_rows(payload: Any, *, references: bool) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    field = "cited" if references else "citing"
    return [
        {"id": row.get(field), "title": None, "identifiers": {"DOI": row.get(field)}}
        for row in payload
        if isinstance(row, dict) and row.get(field)
    ]


def cites_lookup(
    arguments: list[str],
    *,
    references: bool = False,
    fresh: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    if len(arguments) != 1:
        raise BadArguments("cites needs one DOI or arXiv identifier")
    kind, identifier, semantic_id = paper_identifier(arguments[0])
    direction = "references" if references else "citations"
    semantic_url = (
        f"https://api.semanticscholar.org/graph/v1/paper/{quote(semantic_id, safe='')}/"
        f"{direction}?"
        + urlencode({"fields": "paperId,title,externalIds", "limit": 100})
    )
    semantic = gateway_response(
        "cites",
        arguments + (["refs"] if references else []),
        "Semantic Scholar",
        semantic_url,
        fresh=fresh,
        root=root,
    )
    payload, attempt = remote_json(semantic)
    tried = [attempt]
    rows = citation_rows(payload, references=references)
    if rows:
        return result(
            "cites",
            {"identifier": arguments[0], "direction": direction},
            "found",
            {"papers": rows},
            source_from_response(semantic),
            tried,
            cached=semantic.cached,
        )
    if payload is not None:
        mark_attempt(attempt, "not found")
    if kind == "doi":
        endpoint = "references" if references else "citations"
        open_url = (
            f"https://opencitations.net/index/api/v1/{endpoint}/"
            f"{quote(identifier, safe='')}"
        )
        open_response = gateway_response(
            "cites",
            arguments + (["refs"] if references else []),
            "OpenCitations",
            open_url,
            fresh=fresh,
            root=root,
        )
        open_payload, open_attempt = remote_json(open_response)
        tried.append(open_attempt)
        rows = opencitations_rows(open_payload, references=references)
        if rows:
            return result(
                "cites",
                {"identifier": arguments[0], "direction": direction},
                "found",
                {"papers": rows},
                source_from_response(open_response),
                tried,
                cached=semantic.cached and open_response.cached,
            )
        if open_payload is not None:
            mark_attempt(open_attempt, "not found")
        responses = [semantic, open_response]
    else:
        responses = [semantic]
    return result(
        "cites",
        {"identifier": arguments[0], "direction": direction},
        final_status(tried),
        None,
        None,
        tried,
        cached=all(response.cached for response in responses),
    )


def firecrawl_credits(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    metadata = data.get("metadata") if isinstance(data, dict) else None
    for container in (payload, data, metadata):
        if isinstance(container, dict) and isinstance(
            container.get("creditsUsed"), int
        ):
            return container["creditsUsed"]
    return None


def firecrawl_search_cacheable(envelope: dict[str, Any]) -> bool:
    try:
        payload = json.loads(envelope["body"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("success", True) is not False
        and isinstance(payload.get("data"), list)
    )


def search_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if not arguments:
        raise BadArguments("search needs one or more words")
    query = " ".join(arguments)
    url = "https://api.firecrawl.dev/v2/search"
    response = gateway_response(
        "search",
        arguments,
        "Firecrawl search",
        url,
        curl_args=[
            "--json",
            json.dumps({"query": query, "limit": 10}, separators=(",", ":")),
        ],
        fresh=fresh,
        root=root,
        cache_validator=firecrawl_search_cacheable,
    )
    payload, attempt = remote_json(response)
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = (
        [
            {
                "title": row.get("title"),
                "url": row.get("url"),
                "description": row.get("description"),
            }
            for row in data
            if isinstance(row, dict) and row.get("url")
        ]
        if isinstance(data, list)
        else []
    )
    if rows:
        return result(
            "search",
            {"words": arguments},
            "found",
            {"results": rows, "credits_used": firecrawl_credits(payload)},
            source_from_response(response),
            [attempt],
            cached=response.cached,
        )
    if payload is not None:
        status = (
            "not found"
            if isinstance(payload, dict) and payload.get("success", True)
            else "error"
        )
        mark_attempt(attempt, status)
    return result(
        "search",
        {"words": arguments},
        final_status([attempt]),
        None,
        None,
        [attempt],
        cached=response.cached,
    )


def page_redirect(url: str, *, allow_arxiv_pdf: bool = False) -> str | None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host in {"github.com", "docs.github.com", "raw.githubusercontent.com"}:
        return "repo"
    if host == "docs.ansible.com":
        return "ansible"
    if host == "arxiv.org":
        if allow_arxiv_pdf and parsed.path.startswith("/pdf/"):
            return None
        return "paper or fulltext"
    if host == "api.semanticscholar.org":
        return "paper"
    if host == "developer.hashicorp.com":
        return "help"
    return None


def page_lookup(
    arguments: list[str],
    *,
    fresh: bool = False,
    root: Path | None = None,
    allow_arxiv_pdf: bool = False,
    cache_kind: str = "page",
    subject: str | None = None,
) -> dict[str, Any]:
    if len(arguments) != 1:
        raise BadArguments("page needs one HTTPS URL")
    try:
        target = normalize_url(arguments[0])
    except ValueError as error:
        return result(
            "page",
            {"url": arguments[0]},
            "refused",
            {"reason": str(error)},
            None,
            [{"source": "routing", "status": "refused", "http": None}],
        )
    redirect = page_redirect(target, allow_arxiv_pdf=allow_arxiv_pdf)
    if redirect:
        return result(
            "page",
            {"url": target},
            "refused",
            {"use": redirect},
            None,
            [
                {
                    "source": "routing",
                    "status": "refused",
                    "http": None,
                    "reason": f"use {redirect}",
                }
            ],
        )
    try:
        public_address(urlsplit(target).hostname or "")
    except (ValueError, socket.gaierror) as error:
        return result(
            "page",
            {"url": target},
            "refused",
            {"reason": str(error)},
            None,
            [{"source": "routing", "status": "refused", "http": None}],
        )

    firecrawl_url = "https://api.firecrawl.dev/v2/scrape"
    firecrawl = gateway_response(
        cache_kind,
        [target],
        "Firecrawl scrape",
        firecrawl_url,
        curl_args=[
            "--json",
            json.dumps(
                {"url": target, "formats": ["markdown"], "onlyMainContent": True},
                separators=(",", ":"),
            ),
        ],
        fresh=fresh,
        root=root,
        subject=subject,
    )
    payload, attempt = remote_json(firecrawl)
    tried = [attempt]
    data = payload.get("data") if isinstance(payload, dict) else None
    markdown = data.get("markdown") if isinstance(data, dict) else None
    if isinstance(markdown, str) and markdown.strip():
        return result(
            "page",
            {"url": target},
            "found",
            {
                "length": len(markdown),
                "archive": (source_from_response(firecrawl) or {}).get("archive"),
                "title": (data.get("metadata") or {}).get("title")
                if isinstance(data.get("metadata"), dict)
                else None,
                "credits_used": firecrawl_credits(payload),
            },
            source_from_response(firecrawl),
            tried,
            cached=firecrawl.cached,
        )
    if payload is not None:
        mark_attempt(attempt, "error")

    bright_url = "https://api.brightdata.com/request"
    bright = gateway_response(
        cache_kind,
        [target],
        "Bright Data",
        bright_url,
        curl_args=[
            "--json",
            json.dumps(
                {"zone": "bright_data_agent", "url": target, "format": "raw"},
                separators=(",", ":"),
            ),
        ],
        fresh=fresh,
        root=root,
        subject=subject,
    )
    body, bright_attempt = remote_text(bright)
    tried.append(bright_attempt)
    if body is not None:
        return result(
            "page",
            {"url": target},
            "found",
            {
                "length": len(body),
                "archive": (source_from_response(bright) or {}).get("archive"),
                "title": None,
                "credits_used": None,
            },
            source_from_response(bright),
            tried,
            cached=firecrawl.cached and bright.cached,
        )
    return result(
        "page",
        {"url": target},
        final_status(tried),
        None,
        None,
        tried,
        cached=firecrawl.cached and bright.cached,
    )


DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalized_domain(value: str) -> str:
    """Return one canonical DNS name or reject non-domain input."""
    domain = value.strip().lower().rstrip(".")
    if not domain or len(domain) > 253 or "." not in domain:
        raise BadArguments("a public domain name is required")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise BadArguments("a domain name, not an IP address, is required")
    if any(not DOMAIN_LABEL.fullmatch(label) for label in domain.split(".")):
        raise BadArguments("invalid domain name")
    return domain


def json_envelope_matches(
    envelope: dict[str, Any], predicate: Callable[[Any], bool]
) -> bool:
    if envelope.get("status") == 404:
        return True
    try:
        payload = json.loads(envelope["body"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return False
    return predicate(payload)


def cert_cacheable(envelope: dict[str, Any]) -> bool:
    optional_fields = ("issuer_name", "not_before", "not_after", "serial_number")
    return json_envelope_matches(
        envelope,
        lambda payload: (
            isinstance(payload, list)
            and all(
                isinstance(row, dict)
                and isinstance(row.get("name_value"), str)
                and all(
                    row.get(field) is None or isinstance(row.get(field), str)
                    for field in optional_fields
                )
                for row in payload
            )
        ),
    )


def shodan_cacheable(envelope: dict[str, Any]) -> bool:
    fields = {"ports", "vulns", "hostnames", "cpes", "tags"}
    return json_envelope_matches(
        envelope,
        lambda payload: (
            isinstance(payload, dict)
            and bool(fields.intersection(payload))
            and all(
                field not in payload or isinstance(payload.get(field), list)
                for field in fields
            )
        ),
    )


def greynoise_cacheable(envelope: dict[str, Any]) -> bool:
    return json_envelope_matches(
        envelope,
        lambda payload: (
            isinstance(payload, dict)
            and isinstance(payload.get("noise"), bool)
            and isinstance(payload.get("riot"), bool)
            and all(
                payload.get(field) is None or isinstance(payload.get(field), str)
                for field in (
                    "classification",
                    "name",
                    "last_seen",
                    "message",
                    "link",
                )
            )
        ),
    )


def cert_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) != 1:
        raise BadArguments("cert needs one domain")
    domain = normalized_domain(arguments[0])
    url = "https://crt.sh/?" + urlencode({"q": domain, "output": "json"})
    response = gateway_response(
        "cert",
        [domain],
        "crt.sh",
        url,
        fresh=fresh,
        root=root,
        cache_validator=cert_cacheable,
    )
    payload, attempt = remote_json(response)
    certificates = (
        [
            {
                "id": row.get("id"),
                "issuer": row.get("issuer_name"),
                "names": sorted(
                    {
                        name.strip()
                        for name in str(row.get("name_value", "")).splitlines()
                        if name.strip()
                    }
                ),
                "not_before": row.get("not_before"),
                "not_after": row.get("not_after"),
                "serial_number": row.get("serial_number"),
            }
            for row in payload
            if isinstance(row, dict)
        ]
        if isinstance(payload, list)
        else []
    )
    if certificates:
        return result(
            "cert",
            {"domain": domain},
            "found",
            {"certificates": certificates},
            source_from_response(response),
            [attempt],
            cached=response.cached,
        )
    if payload is not None:
        mark_attempt(attempt, "not found" if isinstance(payload, list) else "error")
    return result(
        "cert",
        {"domain": domain},
        final_status([attempt]),
        None,
        None,
        [attempt],
        cached=response.cached,
    )


def ip_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) != 1:
        raise BadArguments("ip needs one public IP address")
    try:
        address = ipaddress.ip_address(arguments[0])
    except ValueError as error:
        raise BadArguments("ip needs one valid IP address") from error
    if not address.is_global or address.is_multicast:
        raise BadArguments("ip refuses non-public addresses")
    canonical = str(address)
    shodan_url = f"https://internetdb.shodan.io/{quote(canonical, safe=':')}"
    shodan = gateway_response(
        "ip",
        [canonical],
        "Shodan InternetDB",
        shodan_url,
        fresh=fresh,
        root=root,
        cache_validator=shodan_cacheable,
    )
    shodan_payload, shodan_attempt = remote_json(shodan)
    greynoise_url = (
        f"https://api.greynoise.io/v3/community/{quote(canonical, safe=':')}"
    )
    greynoise = gateway_response(
        "ip",
        [canonical],
        "GreyNoise community",
        greynoise_url,
        fresh=fresh,
        root=root,
        cache_validator=greynoise_cacheable,
    )
    greynoise_payload, greynoise_attempt = remote_json(greynoise)
    tried = [shodan_attempt, greynoise_attempt]
    shodan_data = shodan_payload if isinstance(shodan_payload, dict) else None
    greynoise_data = greynoise_payload if isinstance(greynoise_payload, dict) else None
    if shodan_payload is not None and shodan_data is None:
        mark_attempt(shodan_attempt, "error")
    if greynoise_payload is not None and greynoise_data is None:
        mark_attempt(greynoise_attempt, "error")
    if shodan_data is not None or greynoise_data is not None:
        primary = shodan if shodan_data is not None else greynoise
        return result(
            "ip",
            {"address": canonical},
            "found",
            {
                "open_ports": (shodan_data or {}).get("ports", []),
                "known_issues": (shodan_data or {}).get("vulns", []),
                "hostnames": (shodan_data or {}).get("hostnames", []),
                "cpes": (shodan_data or {}).get("cpes", []),
                "tags": (shodan_data or {}).get("tags", []),
                "scanning": {
                    key: (greynoise_data or {}).get(key)
                    for key in (
                        "noise",
                        "riot",
                        "classification",
                        "name",
                        "last_seen",
                        "message",
                        "link",
                    )
                },
            },
            source_from_response(primary),
            tried,
            cached=shodan.cached and greynoise.cached,
        )
    return result(
        "ip",
        {"address": canonical},
        final_status(tried),
        None,
        None,
        tried,
        cached=shodan.cached and greynoise.cached,
    )


def rdap_registrar(payload: dict[str, Any]) -> str | None:
    for entity in payload.get("entities", []):
        if not isinstance(entity, dict) or "registrar" not in entity.get("roles", []):
            continue
        card = entity.get("vcardArray")
        rows = card[1] if isinstance(card, list) and len(card) > 1 else []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, list) and len(row) > 3 and row[0] == "fn":
                return str(row[3])
        if entity.get("handle"):
            return str(entity["handle"])
    return None


def rdap_cacheable(envelope: dict[str, Any]) -> bool:
    try:
        payload = json.loads(envelope["body"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and any(
        key in payload for key in ("ldhName", "unicodeName", "handle", "entities")
    )


def domain_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) != 1:
        raise BadArguments("domain needs one domain")
    domain = normalized_domain(arguments[0])
    root = root or vault_root()
    response: RemoteResponse | None = None
    tried: list[dict[str, Any]] = []
    responses: list[RemoteResponse] = []
    if not fresh:
        cached = newest_cached_envelope(
            "domain",
            [domain],
            FRESHNESS_DAYS["domain"],
            root=root,
            validator=rdap_cacheable,
        )
        if cached is not None:
            path, envelope = cached
            cached_url = str(envelope.get("url", "https://rdap.org/"))
            response = RemoteResponse("RDAP", cached_url, path, envelope, True)
            log_cached_response(response, root=root)
    if response is None:
        bootstrap_url = f"https://rdap.org/domain/{quote(domain, safe='')}"
        bootstrap = gateway_response(
            "domain",
            [domain],
            "RDAP bootstrap",
            bootstrap_url,
            fresh=True,
            root=root,
        )
        responses.append(bootstrap)
        envelope = bootstrap.envelope or {}
        status = envelope.get("status")
        headers = envelope.get("headers")
        location = (
            next(
                (
                    value
                    for key, value in headers.items()
                    if isinstance(key, str) and key.lower() == "location"
                ),
                None,
            )
            if isinstance(headers, dict)
            else None
        )
        if (
            isinstance(status, int)
            and 300 <= status < 400
            and isinstance(location, str)
        ):
            try:
                target = normalize_url(urljoin(bootstrap_url, location))
                public_address(urlsplit(target).hostname or "")
            except (ValueError, socket.gaierror) as error:
                tried.append(
                    {
                        "source": "RDAP redirect",
                        "status": "refused",
                        "http": None,
                        "reason": str(error),
                    }
                )
                return result(
                    "domain",
                    {"domain": domain},
                    "refused",
                    {"reason": str(error)},
                    None,
                    tried,
                )
            tried.append(
                {"source": "RDAP bootstrap", "status": "redirected", "http": status}
            )
            response = gateway_response(
                "domain",
                [domain],
                "RDAP",
                target,
                fresh=True,
                root=root,
                cache_validator=rdap_cacheable,
            )
            responses.append(response)
        else:
            response = bootstrap
    payload, attempt = remote_json(response)
    tried.append(attempt)
    if isinstance(payload, dict) and rdap_cacheable(response.envelope or {}):
        events = {
            str(row.get("eventAction")): row.get("eventDate")
            for row in payload.get("events", [])
            if isinstance(row, dict) and row.get("eventAction")
        }
        nameservers = [
            row.get("ldhName") or row.get("unicodeName")
            for row in payload.get("nameservers", [])
            if isinstance(row, dict) and (row.get("ldhName") or row.get("unicodeName"))
        ]
        return result(
            "domain",
            {"domain": domain},
            "found",
            {
                "registrar": rdap_registrar(payload),
                "dates": events,
                "name_servers": nameservers,
                "status": payload.get("status", []),
            },
            source_from_response(response),
            tried,
            cached=response.cached and all(item.cached for item in responses),
        )
    if payload is not None:
        mark_attempt(attempt, "error")
    return result(
        "domain",
        {"domain": domain},
        final_status(tried),
        None,
        None,
        tried,
        cached=response.cached and all(item.cached for item in responses),
    )


def fulltext_answer(response: RemoteResponse, text: str) -> dict[str, Any]:
    source_value = source_from_response(response) or {}
    return {"length": len(text), "archive": source_value.get("archive")}


def fulltext_lookup(
    arguments: list[str], *, fresh: bool = False, root: Path | None = None
) -> dict[str, Any]:
    if len(arguments) != 1:
        raise BadArguments("fulltext needs one DOI or arXiv identifier")
    kind, identifier, semantic_id = paper_identifier(arguments[0])
    semantic_url = (
        f"https://api.semanticscholar.org/graph/v1/paper/{quote(semantic_id, safe='')}?"
        + urlencode({"fields": "title,externalIds,openAccessPdf"})
    )
    semantic = gateway_response(
        "fulltext",
        arguments,
        "Semantic Scholar open-access link",
        semantic_url,
        fresh=fresh,
        root=root,
    )
    payload, semantic_attempt = remote_json(semantic)
    tried = [semantic_attempt]
    responses = [semantic]
    title = payload.get("title") if isinstance(payload, dict) else None
    external = payload.get("externalIds") if isinstance(payload, dict) else None
    doi = identifier if kind == "doi" else None
    if doi is None and isinstance(external, dict):
        doi = external.get("DOI")
    page_cached = True
    if kind == "arxiv":
        doi = doi or f"10.48550/arXiv.{identifier}"
    open_pdf = payload.get("openAccessPdf") if isinstance(payload, dict) else None
    open_url = open_pdf.get("url") if isinstance(open_pdf, dict) else None
    arxiv_pdf_tried = False
    if isinstance(open_url, str) and open_url.startswith("https://"):
        open_parts = urlsplit(open_url)
        arxiv_pdf_tried = (
            open_parts.hostname or ""
        ).lower() == "arxiv.org" and open_parts.path.startswith("/pdf/")
        open_page = page_lookup(
            [open_url],
            fresh=fresh,
            root=root,
            allow_arxiv_pdf=arxiv_pdf_tried,
            cache_kind="fulltext",
            subject=arguments[0],
        )
        page_cached = page_cached and open_page["cached"]
        tried.extend(open_page["tried"])
        if open_page["status"] == "found":
            return result(
                "fulltext",
                {"identifier": arguments[0]},
                "found",
                {
                    "length": open_page["answer"]["length"],
                    "archive": open_page["answer"]["archive"],
                },
                open_page["source"],
                tried,
                cached=all(response.cached for response in responses) and page_cached,
            )
    elif payload is not None:
        mark_attempt(semantic_attempt, "not found")

    arxiv_doi = isinstance(doi, str) and doi.lower().startswith("10.48550/arxiv.")
    if arxiv_doi:
        tried.append(
            {
                "source": "Unpaywall",
                "status": "skipped",
                "http": None,
                "reason": "arXiv DOI is skipped by rule",
            }
        )
    elif isinstance(doi, str):
        unpaywall_url = f"https://api.unpaywall.org/v2/{quote(doi, safe='')}"
        unpaywall = gateway_response(
            "fulltext", arguments, "Unpaywall", unpaywall_url, fresh=fresh, root=root
        )
        responses.append(unpaywall)
        unpaywall_payload, unpaywall_attempt = remote_json(unpaywall)
        tried.append(unpaywall_attempt)
        location = (
            unpaywall_payload.get("best_oa_location")
            if isinstance(unpaywall_payload, dict)
            else None
        )
        unpaywall_link = (
            location.get("url_for_pdf") if isinstance(location, dict) else None
        )
        if isinstance(unpaywall_link, str) and unpaywall_link.startswith("https://"):
            linked_page = page_lookup(
                [unpaywall_link],
                fresh=fresh,
                root=root,
                allow_arxiv_pdf=(
                    (urlsplit(unpaywall_link).hostname or "").lower() == "arxiv.org"
                    and urlsplit(unpaywall_link).path.startswith("/pdf/")
                ),
                cache_kind="fulltext",
                subject=arguments[0],
            )
            page_cached = page_cached and linked_page["cached"]
            tried.extend(linked_page["tried"])
            if linked_page["status"] == "found":
                return result(
                    "fulltext",
                    {"identifier": arguments[0]},
                    "found",
                    {
                        "length": linked_page["answer"]["length"],
                        "archive": linked_page["answer"]["archive"],
                    },
                    linked_page["source"],
                    tried,
                    cached=all(response.cached for response in responses)
                    and page_cached,
                )
        elif unpaywall_payload is not None:
            mark_attempt(unpaywall_attempt, "not found")
    else:
        tried.append(
            {
                "source": "Unpaywall",
                "status": "not found",
                "http": None,
                "reason": "no DOI",
            }
        )

    core_queries = []
    if isinstance(doi, str):
        core_queries.append(("CORE (DOI)", f'doi:"{doi}"'))
    if isinstance(title, str) and title:
        core_queries.append(("CORE (exact title)", f'title:"{title}"'))
    if not core_queries:
        core_queries.append(("CORE (exact title)", f'title:"{identifier}"'))
    for core_source, query_value in core_queries:
        core_url = "https://api.core.ac.uk/v3/search/works/?" + urlencode(
            {"q": query_value, "limit": 10}
        )
        core = gateway_response(
            "fulltext", arguments, core_source, core_url, fresh=fresh, root=root
        )
        responses.append(core)
        core_payload, core_attempt = remote_json(core)
        tried.append(core_attempt)
        core_results = (
            core_payload.get("results") if isinstance(core_payload, dict) else None
        )
        matched = (
            next(
                (
                    row
                    for row in core_results
                    if isinstance(row, dict)
                    and isinstance(row.get("fullText"), str)
                    and row["fullText"].strip()
                    and (
                        (
                            isinstance(doi, str)
                            and str(row.get("doi", "")).lower() == doi.lower()
                        )
                        or (
                            isinstance(title, str)
                            and str(row.get("title", "")).casefold() == title.casefold()
                        )
                    )
                ),
                None,
            )
            if isinstance(core_results, list)
            else None
        )
        if isinstance(matched, dict):
            text = matched["fullText"]
            return result(
                "fulltext",
                {"identifier": arguments[0]},
                "found",
                fulltext_answer(core, text),
                source_from_response(core),
                tried,
                cached=all(response.cached for response in responses),
            )
        if core_payload is not None:
            mark_attempt(core_attempt, "not found")

    if kind == "arxiv" and not arxiv_pdf_tried:
        arxiv_url = f"https://arxiv.org/pdf/{quote(identifier, safe='/')}"
        page_outcome = page_lookup(
            [arxiv_url],
            fresh=fresh,
            root=root,
            allow_arxiv_pdf=True,
            cache_kind="fulltext",
            subject=arguments[0],
        )
        page_cached = page_cached and page_outcome["cached"]
        tried.extend(page_outcome["tried"])
        if page_outcome["status"] == "found":
            return result(
                "fulltext",
                {"identifier": arguments[0]},
                "found",
                {
                    "length": page_outcome["answer"]["length"],
                    "archive": page_outcome["answer"]["archive"],
                },
                page_outcome["source"],
                tried,
                cached=all(response.cached for response in responses)
                and page_outcome["cached"],
            )
    return result(
        "fulltext",
        {"identifier": arguments[0]},
        final_status(tried),
        None,
        None,
        tried,
        cached=all(response.cached for response in responses) and page_cached,
    )


def dispatch(
    kind: str, arguments: list[str], *, fresh: bool = False, references: bool = False
) -> tuple[dict[str, Any], str]:
    if references and kind != "cites":
        raise BadArguments("--refs is only valid for cites")
    if kind == "vault":
        return vault_lookup(arguments), "vault:" + " ".join(arguments)
    if kind == "ansible":
        return ansible_lookup(arguments), "ansible-doc:" + " ".join(arguments)
    if kind == "help":
        return help_lookup(arguments), "command:" + " ".join(arguments)
    if kind == "doctor":
        return doctor_lookup(arguments), "machine:doctor"
    remote_handlers = {
        "eol": eol_lookup,
        "pkg": pkg_lookup,
        "vuln": vuln_lookup,
        "cve": cve_lookup,
        "repo": repo_lookup,
        "rfc": rfc_lookup,
        "search": search_lookup,
        "page": page_lookup,
        "cert": cert_lookup,
        "ip": ip_lookup,
        "domain": domain_lookup,
        "docs": docs_lookup,
    }
    if kind in remote_handlers:
        outcome = remote_handlers[kind](arguments, fresh=fresh)
        locator = (outcome.get("source") or {}).get("url") or outcome.get(
            "query", {}
        ).get("url", f"lookup:{kind}")
        return outcome, locator
    if kind == "paper":
        outcome = paper_lookup(arguments, fresh=fresh)
    elif kind == "cites":
        outcome = cites_lookup(arguments, references=references, fresh=fresh)
    elif kind == "fulltext":
        outcome = fulltext_lookup(arguments, fresh=fresh)
    else:
        outcome = None
    if outcome is not None:
        locator = (outcome.get("source") or {}).get("url", f"lookup:{kind}")
        return outcome, locator
    if kind not in LOCAL_KINDS | BUILD_KINDS:
        raise BadArguments(f"unknown or not-yet-built lookup kind: {kind}")
    raise AssertionError(kind)


def print_text(value: Any, prefix: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            label = f"{prefix}.{key}" if prefix else key
            print_text(child, label)
    elif isinstance(value, list):
        for index, child in enumerate(value, 1):
            print_text(child, f"{prefix}[{index}]")
    else:
        print(f"{prefix}: {value}")


def json_output(outcome: dict[str, Any], limit: int) -> str:
    """Render lookup JSON without letting a large answer fill the caller's context."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("lookup.max_output_chars must be a positive integer")
    content_limit = limit - 1
    full = json.dumps(outcome, ensure_ascii=False)
    source_value = outcome.get("source")
    source_value = source_value if isinstance(source_value, dict) else None
    answer = outcome.get("answer")
    archives: list[str] = []
    for value in [
        (source_value or {}).get("archive"),
        answer.get("archive") if isinstance(answer, dict) else None,
        *(
            attempt.get("archive")
            for attempt in outcome.get("tried", [])
            if isinstance(attempt, dict)
        ),
    ]:
        if isinstance(value, str) and value not in archives:
            archives.append(value)
    archive = archives[0] if archives else None
    if len(full) <= content_limit or archive is None:
        return full
    answer_json = json.dumps(answer, ensure_ascii=False)
    summary = {
        "status": outcome.get("status"),
        "source": source_value,
        "cached": outcome.get("cached"),
        "archive": archive,
        "answer": "",
        "cut": True,
        "full_size": len(full),
    }
    if len(archives) > 1:
        summary["archives"] = archives

    def with_prefix(length: int) -> str:
        summary["answer"] = answer_json[:length]
        return json.dumps(summary, ensure_ascii=False)

    if len(with_prefix(0)) > content_limit:
        raise ValueError("lookup.max_output_chars is too small for result metadata")
    low, high = 0, len(answer_json)
    while low < high:
        middle = (low + high + 1) // 2
        if len(with_prefix(middle)) <= content_limit:
            low = middle
        else:
            high = middle - 1
    return with_prefix(low)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise BadArguments(message)


def parser() -> argparse.ArgumentParser:
    value = JsonArgumentParser(add_help=True, allow_abbrev=False)
    value.add_argument("kind")
    value.add_argument("arguments", nargs="*")
    value.add_argument("--fresh", action="store_true")
    value.add_argument("--text", action="store_true")
    value.add_argument("--refs", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    try:
        options = parser().parse_args(argv)
        if os.environ.get("RESEARCH_RUN") and options.kind in LOCAL_KINDS:
            raise BadArguments(
                f"{options.kind} is unavailable inside a research gather run"
            )
        outcome, locator = dispatch(
            options.kind,
            options.arguments,
            fresh=options.fresh,
            references=options.refs,
        )
        no_request = bool(outcome["tried"]) and all(
            attempt.get("http") is None for attempt in outcome["tried"]
        )
        if options.kind in LOCAL_KINDS or no_request:
            log_local(outcome, locator)
    except BadArguments as error:
        print(json.dumps({"status": "bad arguments", "error": str(error)}))
        return 2
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        return 1
    if options.text:
        print_text(outcome)
    else:
        try:
            rendered = json_output(outcome, load_config()["lookup"]["max_output_chars"])
        except (KeyError, OSError, TypeError, ValueError) as error:
            print(json.dumps({"status": "error", "error": str(error)}))
            return 1
        print(rendered)
    return EXIT_STATUS[outcome["status"]]


if __name__ == "__main__":
    sys.exit(main())
