"""Paced, logged gateway for one HTTPS research request at a time.

Usage: python3 gw.py OUTFILE -- <curl arguments including one https:// URL>
       python3 gw.py --usage
"""

from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit

from common import (
    append_log,
    gateway_lock,
    load_config,
    repository_name,
    sensitive_parameter,
    vault_root,
    write_envelope,
)

STATE = Path.home() / ".claude" / "research-gw-state.json"
LOCK = Path.home() / ".claude" / "research-gw.lock"
CURL = "/usr/bin/curl"
VALUE_OPTIONS = {
    "-H",
    "--header",
    "-X",
    "--request",
    "-d",
    "--data",
    "--data-raw",
    "--data-binary",
    "--data-urlencode",
    "--json",
    "--url",
}
FLAG_OPTIONS = {
    "-I",
    "--head",
    "-s",
    "--silent",
    "-S",
    "--show-error",
    "-G",
    "--get",
}
DATA_OPTIONS = {
    "-d",
    "--data",
    "--data-raw",
    "--data-binary",
    "--data-urlencode",
    "--json",
}
KEY_HEADERS = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "apikey",
    "key",
    "user-agent",
    "host",
}
RATE_HEADERS = {
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "x-ratelimit-remaining-usd",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
    ):
        raise ValueError("URL needs a public HTTPS host without login information")
    host = parts.hostname.rstrip(".").lower()
    if not host:
        raise ValueError("URL needs a public HTTPS host")
    authority = f"[{host}]" if ":" in host else host
    return urlunsplit(("https", authority, parts.path, parts.query, parts.fragment))


def sensitive_body(value: str) -> bool:
    """Recognize credential field names in JSON and form-style body arguments."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None

    def contains(item: object) -> bool:
        if isinstance(item, dict):
            return any(
                sensitive_parameter(str(key)) or contains(child)
                for key, child in item.items()
            )
        if isinstance(item, list):
            return any(contains(child) for child in item)
        return False

    if parsed is not None and contains(parsed):
        return True
    names = [
        unquote_plus(segment.partition("=")[0])
        for segment in re.split(r"[&;]", value)
        if "=" in segment
    ]
    return any(sensitive_parameter(name) for name in names)


def parse_call(args: list[str]) -> tuple[str, list[str], str]:
    """Accept one URL and only curl options that preserve gateway controls."""
    urls: list[str] = []
    kept: list[str] = []
    explicit_method: str | None = None
    implicit_method = "GET"
    get_mode = False
    head_mode = False
    encoded_fields: list[str] = []
    other_data = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg.startswith("https://"):
            urls.append(arg)
        elif arg in FLAG_OPTIONS:
            if arg in {"-I", "--head"}:
                implicit_method = "HEAD"
                head_mode = True
            if arg in {"-G", "--get"}:
                get_mode = True
            else:
                kept.append(arg)
        else:
            option = arg.split("=", 1)[0]
            if arg in VALUE_OPTIONS:
                option = arg
                index += 1
                if index >= len(args):
                    raise ValueError(f"{option} needs a value")
                value = args[index]
                assembled = [option, value]
            elif option in VALUE_OPTIONS and arg.startswith("--") and "=" in arg:
                value = arg.split("=", 1)[1]
                assembled = [arg]
            elif arg.startswith(("-H", "-X", "-d")) and len(arg) > 2:
                option, value = arg[:2], arg[2:]
                assembled = [arg]
            else:
                raise ValueError(f"curl option {arg} is not supported by the gateway")
            if option == "--url":
                urls.append(value)
            else:
                if option in {"-H", "--header"}:
                    if "\r" in value or "\n" in value:
                        raise ValueError(
                            "header newlines are not allowed by the gateway"
                        )
                    if value.startswith("@"):
                        raise ValueError("header files are not allowed by the gateway")
                    if (
                        value.partition(":")[0].partition(";")[0].strip().lower()
                        in KEY_HEADERS
                    ):
                        raise ValueError("keys are added by the gateway")
                if option in DATA_OPTIONS:
                    file_backed = value.startswith("@") or (
                        option == "--data-urlencode" and "@" in value.split("=", 1)[0]
                    )
                    if file_backed:
                        raise ValueError("data files are not allowed by the gateway")
                    if sensitive_body(value):
                        raise ValueError("keys are added by the gateway")
                    implicit_method = "POST"
                    if option != "--data-urlencode":
                        other_data = True
                if option in {"-X", "--request"}:
                    explicit_method = value.upper()
                if option == "--data-urlencode":
                    encoded_fields.append(value)
                else:
                    kept.extend(assembled)
        index += 1
    if len(urls) != 1 or not urls[0].startswith("https://"):
        raise ValueError("exactly one https:// URL is required")
    if get_mode:
        if other_data:
            raise ValueError("GET accepts only --data-urlencode query fields")
        parts = urlsplit(urls[0])
        encoded: list[str] = []
        for field in encoded_fields:
            name, separator, value = field.partition("=")
            if not separator or not name:
                raise ValueError("GET query fields need name=value")
            encoded.append(f"{quote(name, safe='')}={quote(value, safe='')}")
        query = "&".join(filter(None, (parts.query, *encoded)))
        urls[0] = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, query, parts.fragment)
        )
        implicit_method = "GET"
    else:
        for field in encoded_fields:
            kept.extend(("--data-urlencode", field))
    urls[0] = normalize_url(urls[0])
    parts = urlsplit(urls[0])
    query_names = [
        unquote_plus(segment.partition("=")[0])
        for segment in re.split(r"[&;]", parts.query)
        if "=" in segment
    ]
    if any(sensitive_parameter(name) for name in query_names):
        raise ValueError("keys are added by the gateway")
    method = explicit_method or implicit_method
    if method not in {"GET", "POST", "HEAD", "PUT", "PATCH", "DELETE"}:
        raise ValueError("unsupported request method")
    if head_mode and method != "HEAD":
        raise ValueError("HEAD cannot be combined with a different request method")
    return urls[0], kept, method


def public_address(host: str) -> str:
    """Resolve before curl and pin it to a checked public address."""
    addresses = {
        result[4][0]
        for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    }
    if not addresses or any(
        not ipaddress.ip_address(value).is_global
        or ipaddress.ip_address(value).is_multicast
        for value in addresses
    ):
        raise ValueError(f"private or non-public address refused for {host}")
    chosen = min(
        addresses, key=lambda value: (ipaddress.ip_address(value).version, value)
    )
    return f"[{chosen}]" if ":" in chosen else chosen


def archive_relative_path(out: Path) -> str:
    """Validate that an envelope stays in one of the two decided raw-text trees."""
    resolved = out.expanduser().resolve()
    relative = resolved.relative_to(vault_root().resolve())
    parts = relative.parts
    in_lookups = len(parts) >= 3 and parts[:2] == ("70_Research", "_lookups")
    in_topic_raw = (
        len(parts) >= 5
        and parts[0] == "70_Research"
        and parts[-3:-1] == ("sources", "raw")
    )
    if resolved.suffix != ".json" or not (in_lookups or in_topic_raw):
        raise ValueError("archive must be a JSON file in _lookups or topic sources/raw")
    if resolved.exists() and resolved.stat().st_size:
        raise ValueError("archive path already contains data")
    return relative.as_posix()


def session_token() -> str:
    token = os.environ.get("BW_SESSION", "")
    if token:
        return token
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    path = runtime / "bw-session"
    if not path.exists():
        raise ValueError("Vaultwarden session unavailable; run vu")
    token = path.read_text().strip()
    if not token:
        raise ValueError("Vaultwarden session unavailable; run vu")
    return token


def credential_item_id(item: str, env: dict[str, str]) -> str:
    """Resolve one Vaultwarden item by exact name before reading its password."""
    result = subprocess.run(
        ["bw", "list", "items", "--search", item],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        items = None
    matches = (
        [
            entry.get("id")
            for entry in items
            if isinstance(entry, dict) and entry.get("name") == item
        ]
        if isinstance(items, list)
        else []
    )
    if result.returncode != 0 or len(matches) != 1 or not isinstance(matches[0], str):
        raise ValueError(
            f"Vaultwarden item unavailable: {item}; run vu if the session expired"
        )
    return matches[0]


def credential(item: str) -> str:
    env = {**os.environ, "BW_SESSION": session_token(), "BW_NOINTERACTION": "true"}
    item_id = credential_item_id(item, env)
    result = subprocess.run(
        ["bw", "get", "password", item_id],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError(
            f"Vaultwarden item unavailable: {item}; run vu if the session expired"
        )
    return result.stdout.strip()


def curl_quote(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError("credential contains a newline")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def request_config(url: str, provider: dict, config: dict) -> str:
    """Pass credentials to curl through stdin, never its argument list."""
    lines: list[str] = []
    parts = urlsplit(url)
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    key = credential(provider["key_item"]) if provider.get("key_item") else ""
    if provider.get("key_query"):
        separator = "&" if urlsplit(url).query else "?"
        url += separator + quote(provider["key_query"]) + "=" + quote(key, safe="")
    if provider.get("contact_query"):
        contact = config["gateway"].get("contact_email", "")
        if not contact:
            raise ValueError("contact email is not configured")
        separator = "&" if urlsplit(url).query else "?"
        url += (
            separator + quote(provider["contact_query"]) + "=" + quote(contact, safe="")
        )
    lines.append("url = " + curl_quote(url))
    if provider.get("key_header"):
        value = provider.get("key_format", "{key}").format(key=key)
        lines.append("header = " + curl_quote(f"{provider['key_header']}: {value}"))
    user_agent = config["gateway"]["user_agent"]
    if provider.get("contact_user_agent"):
        contact = config["gateway"].get("contact_email", "")
        if not contact:
            raise ValueError("contact email is not configured")
        user_agent += f" contact:{contact}"
    lines.append("user-agent = " + curl_quote(user_agent))
    return "\n".join(lines) + "\n"


def parse_headers(raw: bytes) -> dict[str, str]:
    for block in reversed(re.split(rb"\r?\n\r?\n", raw)):
        lines = block.decode("iso-8859-1", errors="replace").splitlines()
        if lines and lines[0].startswith("HTTP/"):
            headers: dict[str, str] = {}
            for line in lines[1:]:
                name, separator, value = line.partition(":")
                if separator:
                    headers[name.strip()] = value.strip()
            return headers
    return {}


def rate_headers(
    headers: dict[str, str], entry: dict, at: float, provider: dict
) -> None:
    values = {name.lower(): value for name, value in headers.items()}
    for name in RATE_HEADERS:
        if name in values:
            entry.setdefault("reported", {})[name] = values[name]
    if provider.get("daily_budget_usd") and "x-ratelimit-remaining-usd" in values:
        try:
            entry["remaining_usd"] = float(values["x-ratelimit-remaining-usd"])
            next_day = datetime.fromtimestamp(at, timezone.utc).date().toordinal() + 1
            entry["usd_reset"] = (
                datetime.fromordinal(next_day).replace(tzinfo=timezone.utc).timestamp()
            )
        except ValueError:
            pass
    prefix = "x-ratelimit" if "x-ratelimit-remaining" in values else "ratelimit"
    try:
        limit = float(values[f"{prefix}-limit"])
        remaining = float(values[f"{prefix}-remaining"])
        reset = float(values[f"{prefix}-reset"])
    except (KeyError, ValueError):
        return
    entry["limit"] = limit
    entry["remaining"] = remaining
    entry["reset"] = reset if reset > 1_000_000_000 else at + reset


def retry_after_seconds(headers: dict[str, str], at: float) -> float:
    value = next(
        (value for name, value in headers.items() if name.lower() == "retry-after"),
        "",
    )
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - at)
        except (TypeError, ValueError, OverflowError):
            return 0.0


def request_cost(host: str, body: bytes) -> int:
    """Return provider-reported credits for one request, defaulting to one."""
    if host != "api.firecrawl.dev":
        return 1
    try:
        payload = json.loads(body)
        data = payload.get("data") if isinstance(payload, dict) else None
        metadata = data.get("metadata") if isinstance(data, dict) else None
        credits = (
            payload.get("creditsUsed")
            if isinstance(payload, dict) and payload.get("creditsUsed") is not None
            else data.get("creditsUsed")
            if isinstance(data, dict) and data.get("creditsUsed") is not None
            else metadata.get("creditsUsed")
            if isinstance(metadata, dict)
            else None
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        credits = None
    return credits if isinstance(credits, int) and credits > 0 else 1


def window_end(at: float, provider: dict) -> float:
    if isinstance(provider.get("window_cycle_day"), int):
        date = datetime.fromtimestamp(at, timezone.utc)
        day = provider["window_cycle_day"]
        if date.day < day:
            year, month = date.year, date.month
        else:
            year, month = (
                (date.year + 1, 1) if date.month == 12 else (date.year, date.month + 1)
            )
        return datetime(year, month, day, tzinfo=timezone.utc).timestamp()
    if provider.get("window_calendar") == "month":
        date = datetime.fromtimestamp(at, timezone.utc)
        year, month = (
            (date.year + 1, 1) if date.month == 12 else (date.year, date.month + 1)
        )
        return datetime(year, month, 1, tzinfo=timezone.utc).timestamp()
    return at + provider.get("window_seconds", 0)


def seed_window(entry: dict, provider: dict, at: float) -> None:
    """Apply a dated authoritative usage snapshot once, without double counting."""
    end_value = provider.get("window_initial_end")
    initial_used = provider.get("window_initial_used")
    if not isinstance(end_value, str) or not isinstance(initial_used, int):
        return
    try:
        end = datetime.fromisoformat(end_value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return
    if at >= end or entry.get("window_seed_end") == end:
        return
    current = entry.get("window_used", 0) if entry.get("window_end", 0) > at else 0
    entry["window_used"] = max(current, initial_used)
    entry["window_end"] = end
    entry["window_seed_end"] = end


def margin_refusal(entry: dict, provider: dict, margin: float, at: float) -> str | None:
    if entry.get("usd_reset", 0) <= at:
        entry.pop("remaining_usd", None)
        entry.pop("usd_reset", None)
    if entry.get("remaining_usd", float("inf")) <= margin * provider.get(
        "daily_budget_usd", 0
    ):
        reset = datetime.fromtimestamp(entry["usd_reset"], timezone.utc).isoformat()
        return f"USD quota margin reached; resets {reset}"
    if "limit" in entry and entry.get("reset", 0) <= at:
        for field in ("limit", "remaining", "reset"):
            entry.pop(field, None)
        entry["window_used"] = 0
        entry["window_end"] = 0
    if entry.get("reset", 0) > at and entry.get(
        "remaining", float("inf")
    ) <= margin * entry.get("limit", 0):
        reset = datetime.fromtimestamp(entry["reset"], timezone.utc).isoformat()
        return f"reported quota margin reached; resets {reset}"
    count = provider.get("window_count", 0) if "limit" not in entry else 0
    if (
        count
        and entry.get("window_end", 0) > at
        and entry.get("window_used", 0) >= count * (1 - margin)
    ):
        reset = datetime.fromtimestamp(entry["window_end"], timezone.utc).isoformat()
        return f"local quota margin reached; resets {reset}"
    return None


def save_state(state: dict, path: Path | None = None) -> None:
    path = path or STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, separators=(",", ":")))
    temporary.replace(path)


def request(out: Path, url: str, args: list[str], method: str) -> int:
    config = load_config()
    settings = config["gateway"]
    try:
        url = normalize_url(url)
        host = urlsplit(url).hostname or ""
        archive = archive_relative_path(out)
        address = public_address(host)
    except socket.gaierror as error:
        print(f"[gw] ERROR {host}: DNS resolution failed: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"[gw] REFUSED: {error}", file=sys.stderr)
        return 2
    provider = config["providers"].get(host, {})
    with gateway_lock(LOCK):
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        entry = state.get(host, {})
        at = time.time()
        seed_window(entry, provider, at)
        if (
            entry.get("errors", 0) >= settings["error_streak"]
            and at - entry.get("end", 0) < settings["error_cooldown_s"]
        ):
            print(f"[gw] REFUSED {host}: error cooldown", file=sys.stderr)
            return 3
        today = time.strftime("%Y-%m-%d", time.localtime(at))
        if (
            entry.get("day") == today
            and entry.get("count", 0) >= settings["daily_host_cap"]
        ):
            print(f"[gw] REFUSED {host}: daily cap", file=sys.stderr)
            return 3
        refusal = margin_refusal(entry, provider, settings["margin"], at)
        if refusal:
            print(f"[gw] REFUSED {host}: {refusal}", file=sys.stderr)
            return 4
        try:
            curl_input = request_config(url, provider, config)
        except (OSError, ValueError) as error:
            print(f"[gw] REFUSED {host}: {error}", file=sys.stderr)
            return 2
        if entry.get("end"):
            gap = max(
                provider.get("minimum_gap_s", 0),
                min(
                    settings["default_gap_ceiling_s"],
                    max(
                        settings["default_gap_floor_s"],
                        settings["default_gap_multiplier"] * entry.get("dur", 0),
                    ),
                ),
            )
            wait = entry["end"] + gap - at
            if wait > 0:
                print(f"[gw] pacing {host}: waiting {wait:.1f}s", file=sys.stderr)
                time.sleep(wait)
        requested_at = now_utc().isoformat().replace("+00:00", "Z")
        attempts = 0
        final_headers: dict[str, str] = {}
        body = b""
        body_omitted: str | None = None
        body_size: int | None = None
        status = 0
        total_duration = 0.0
        last_duration = 0.0
        retry_refusal = 0
        with tempfile.TemporaryDirectory() as directory:
            body_path = Path(directory) / "body"
            header_path = Path(directory) / "headers"
            resolve_host = f"[{host}]" if ":" in host else host
            for next_attempt in range(1, settings["max_attempts"] + 1):
                attempt_at = time.time()
                attempt_day = time.strftime("%Y-%m-%d", time.localtime(attempt_at))
                if entry.get("day") != attempt_day:
                    entry["day"] = attempt_day
                    entry["count"] = 0
                if entry["count"] >= settings["daily_host_cap"]:
                    print(
                        f"[gw] REFUSED {host}: daily cap before request",
                        file=sys.stderr,
                    )
                    if attempts == 0:
                        return 3
                    retry_refusal = 3
                    break
                attempts = next_attempt
                body_path.unlink(missing_ok=True)
                header_path.unlink(missing_ok=True)
                command = [
                    CURL,
                    "-q",
                    "--silent",
                    "--show-error",
                    "--connect-timeout",
                    str(settings["connect_timeout_s"]),
                    "--max-time",
                    str(settings["max_time_s"]),
                    "--proto",
                    "=https",
                    "--globoff",
                    "--noproxy",
                    "*",
                    "--resolve",
                    f"{resolve_host}:443:{address}",
                    "--output",
                    str(body_path),
                    "--max-filesize",
                    str(settings["max_body_bytes"] + 1),
                    "--dump-header",
                    str(header_path),
                    "--write-out",
                    "%{http_code} %{time_total} %{size_download}",
                    "--config",
                    "-",
                    *args,
                ]
                result = subprocess.run(
                    command,
                    input=curl_input,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                fields = result.stdout.split()
                try:
                    status = int(fields[0]) if fields else 0
                    duration = float(fields[1]) if len(fields) > 1 else 0.0
                    downloaded = int(float(fields[2])) if len(fields) > 2 else 0
                except ValueError:
                    status, duration, downloaded = 0, 0.0, 0
                if result.returncode != 0:
                    status = 0
                total_duration += duration
                last_duration = duration
                final_headers = (
                    parse_headers(header_path.read_bytes())
                    if header_path.exists()
                    else {}
                )
                if method == "HEAD" or not body_path.exists():
                    body = b""
                else:
                    with body_path.open("rb") as stream:
                        body = stream.read(settings["max_body_bytes"] + 1)
                if result.returncode == 63:
                    body_omitted = (
                        f"curl stopped response over {settings['max_body_bytes']} bytes"
                    )
                    body_size = max(len(body), downloaded)
                else:
                    body_omitted = None
                    body_size = None
                finished = time.time()
                rate_headers(final_headers, entry, finished, provider)
                if entry.get("window_end", 0) <= finished:
                    entry["window_end"] = window_end(finished, provider)
                    entry["window_used"] = 0
                entry["window_used"] = entry.get("window_used", 0) + request_cost(
                    host, body
                )
                entry["count"] += 1
                append_log(
                    {
                        "ts": now_utc().isoformat().replace("+00:00", "Z"),
                        "via": "gw",
                        "host": host,
                        "url": url,
                        "status": status,
                        "duration_s": duration,
                        "attempt": attempts,
                        "run": os.environ.get("RESEARCH_RUN"),
                        "repo": repository_name(),
                        "archive": archive,
                    },
                    lock_held=True,
                )
                print(f"[gw] {host} attempt {attempts} HTTP {status} {duration:.2f}s")
                if status != 429 or attempts == settings["max_attempts"]:
                    break
                refusal = margin_refusal(entry, provider, settings["margin"], finished)
                if refusal:
                    print(
                        f"[gw] REFUSED {host}: {refusal} before retry", file=sys.stderr
                    )
                    retry_refusal = 4
                    break
                retry_after = retry_after_seconds(final_headers, finished)
                if (
                    not math.isfinite(retry_after)
                    or retry_after > settings["default_gap_ceiling_s"]
                ):
                    print(
                        f"[gw] REFUSED {host}: Retry-After exceeds the bounded wait",
                        file=sys.stderr,
                    )
                    retry_refusal = 4
                    break
                backoff = provider.get(
                    "backoff_base_s", settings["default_backoff_base_s"]
                ) * (2**attempts)
                backoff = max(backoff, retry_after)
                print(
                    f"[gw] 429 from {host}: retry backoff {backoff:.0f}s",
                    file=sys.stderr,
                )
                time.sleep(backoff)
            error = status == 0 or (400 <= status <= 599 and status not in (404, 429))
            if not 200 <= status < 300:
                last_duration = max(last_duration, entry.get("dur", 0.0))
            entry.update(
                end=time.time(),
                dur=last_duration,
                code=status,
                errors=entry.get("errors", 0) + 1 if error else 0,
            )
            state[host] = entry
            save_state(state)
            write_envelope(
                out,
                url=url,
                method=method,
                requested_at=requested_at,
                status=status,
                duration_s=total_duration,
                attempts=attempts,
                headers=final_headers,
                body=body,
                max_body_bytes=settings["max_body_bytes"],
                body_omitted=body_omitted,
                body_size=body_size,
            )
    print(f"[gw] requests made: {attempts}")
    return retry_refusal or (1 if status == 0 else 0)


def usage() -> int:
    config = load_config()
    root = vault_root() / "70_Research" / "_log"
    with gateway_lock(LOCK):
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        lines = [
            line
            for path in root.glob("*.jsonl")
            for line in path.read_text().splitlines()
        ]
    today = datetime.now().astimezone().date().isoformat()
    month = today[:7]
    counts: dict[str, dict[str, int]] = {}
    for line in lines:
        record = json.loads(line)
        if record.get("via") != "gw":
            continue
        host = record.get("host", "")
        stamp = record.get("ts", "")
        if isinstance(stamp, (int, float)):
            day = (
                datetime.fromtimestamp(stamp, timezone.utc)
                .astimezone()
                .date()
                .isoformat()
            )
        else:
            day = (
                datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                .astimezone()
                .date()
                .isoformat()
            )
        counters = counts.setdefault(host, {"today": 0, "month": 0})
        if day[:7] == month:
            counters["month"] += 1
        if day == today:
            counters["today"] += 1
    for host in sorted(set(config["providers"]) | set(counts) | set(state)):
        entry = dict(state.get(host, {}))
        provider = config["providers"].get(host, {})
        seed_window(entry, provider, time.time())
        margin = config["gateway"]["margin"]
        remaining = entry.get("remaining", entry.get("remaining_usd", "unknown"))
        if "remaining_usd" in entry and "remaining" not in entry:
            remaining = f"${remaining}"
        quota_details = []
        if isinstance(entry.get("limit"), (int, float)):
            quota_details.append(f"reported_margin={entry['limit'] * margin:g}")
        if isinstance(entry.get("remaining_usd"), (int, float)) and isinstance(
            provider.get("daily_budget_usd"), (int, float)
        ):
            quota_details.append(
                f"usd_margin=${provider['daily_budget_usd'] * margin:g}"
            )
        if isinstance(provider.get("window_count"), int):
            window_used = (
                entry.get("window_used", 0)
                if entry.get("window_end", 0) > time.time()
                else 0
            )
            window_limit = provider["window_count"]
            quota_details.append(
                f"local_used={window_used}/{window_limit} "
                f"local_remaining={max(0, window_limit - window_used)} "
                f"local_margin={window_limit * margin:g}"
            )
        print(
            f"{host}: today={counts.get(host, {}).get('today', 0)} "
            f"month={counts.get(host, {}).get('month', 0)} remaining={remaining} "
            f"margin={margin:.0%} {' '.join(quota_details)}".rstrip()
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--usage"]:
        return usage()
    if len(argv) < 3 or argv[1] != "--":
        print(__doc__, file=sys.stderr)
        return 2
    try:
        url, args, method = parse_call(argv[2:])
    except ValueError as error:
        print(f"[gw] REFUSED: {error}", file=sys.stderr)
        return 2
    return request(Path(argv[0]), url, args, method)


if __name__ == "__main__":
    sys.exit(main())
