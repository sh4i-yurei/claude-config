"""Shared storage and locking primitives for the research commands."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit, urlunsplit

import tomllib

SCRIPT_DIR = Path(__file__).resolve().parent
LOCK_PATH = Path.home() / ".claude" / "research-gw.lock"
LOG_FIELDS = (
    "ts",
    "via",
    "host",
    "url",
    "status",
    "duration_s",
    "attempt",
    "run",
    "repo",
    "archive",
)
SENSITIVE_QUERY = {
    "api_key",
    "apikey",
    "key",
    "token",
    "access_token",
    "email",
    "mailto",
    "password",
    "client_secret",
    "secret",
}
SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
    "apikey",
}


def load_config(path: Path | None = None) -> dict:
    """Read the versioned research configuration with the standard TOML parser."""
    with (path or SCRIPT_DIR / "research.toml").open("rb") as stream:
        return tomllib.load(stream)


def vault_root() -> Path:
    """Return the configured vault path without creating any directories."""
    return Path(
        os.environ.get("SECOND_BRAIN", Path.home() / "Documents/Second_Brain")
    ).expanduser()


@contextmanager
def gateway_lock(path: Path = LOCK_PATH):
    """Hold the machine-wide exclusive gateway lock until the context exits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    authority = parts.netloc.rsplit("@", 1)[-1]
    segments = re.split(r"([&;])", parts.query)
    for index in range(0, len(segments), 2):
        segment = segments[index]
        name, equals, _value = segment.partition("=")
        if equals and sensitive_parameter(unquote_plus(name)):
            segments[index] = f"{name}=REDACTED"
    query = "".join(segments)
    return urlunsplit((parts.scheme, authority, parts.path, query, ""))


def sensitive_parameter(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return (
        name.lower() in SENSITIVE_QUERY
        or normalized
        in {
            "sig",
            "signature",
            "credential",
            "authorization",
            "awsaccesskeyid",
            "session",
        }
        or normalized.endswith(
            (
                "signature",
                "credential",
                "token",
                "secret",
                "password",
                "apikey",
                "accesskeyid",
            )
        )
    )


def redact_header_value(value: str) -> str:
    """Remove credentials from URLs and key-value fields in response headers."""
    urls_redacted = re.sub(
        r"https?://[^\s<>\"']+",
        lambda match: redact_url(match.group(0)),
        value,
    )
    return re.sub(
        r"(?i)\b([a-z][a-z0-9_-]*)=(?:\"[^\"]*\"|'[^']*'|[^&;,\s]+)",
        lambda match: (
            f"{match.group(1)}=REDACTED"
            if sensitive_parameter(match.group(1))
            else match.group(0)
        ),
        urls_redacted,
    )


def repository_name(cwd: Path | None = None) -> str:
    """Use the closest .git directory, or the working directory outside Git."""
    current = (cwd or Path.cwd()).resolve()
    for path in (current, *current.parents):
        if (path / ".git").exists():
            return path.name
    return str(current)


def log_path(
    at: datetime | None = None, root: Path | None = None, hostname: str | None = None
) -> Path:
    at = at or datetime.now(timezone.utc)
    return (
        (root or vault_root())
        / "70_Research"
        / "_log"
        / f"{hostname or socket.gethostname()}-{at:%Y-%m}.jsonl"
    )


def _previous_hash(path: Path) -> str:
    """Find the preceding monthly file for this host, including skipped months."""
    stem = path.stem
    prefix = stem[:-7]
    previous = sorted(
        candidate
        for candidate in path.parent.glob(f"{prefix}????-??.jsonl")
        if candidate.name < path.name
    )
    if not previous:
        return ""
    lines = previous[-1].read_text().splitlines()
    return json.loads(lines[-1])["h"] if lines else ""


def _last_hash(path: Path) -> str:
    if not path.exists():
        return _previous_hash(path)
    lines = path.read_text().splitlines()
    return json.loads(lines[-1])["h"] if lines else _previous_hash(path)


def append_log(
    entry: dict,
    *,
    path: Path | None = None,
    lock_path: Path = LOCK_PATH,
    lock_held: bool = False,
) -> dict:
    """Append a canonical JSON line whose hash extends the prior line's hash."""
    target = path or log_path()
    missing = set(LOG_FIELDS) - entry.keys()
    if missing:
        raise ValueError(f"log entry missing fields: {', '.join(sorted(missing))}")
    line = {key: entry[key] for key in LOG_FIELDS}
    line["url"] = redact_url(line["url"])

    def write() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(line, ensure_ascii=False, separators=(",", ":"))
        line["h"] = hashlib.sha256(
            (_last_hash(target) + serialized).encode()
        ).hexdigest()[:16]
        with target.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

    if lock_held:
        write()
    else:
        with gateway_lock(lock_path):
            write()
    return line


def verify_log(path: Path, previous_hash: str = "") -> str:
    """Verify a monthly file and return its final hash for the next file."""
    current = previous_hash
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = json.loads(raw)
        observed = line.pop("h")
        serialized = json.dumps(line, ensure_ascii=False, separators=(",", ":"))
        expected = hashlib.sha256((current + serialized).encode()).hexdigest()[:16]
        if observed != expected:
            raise ValueError(f"{path}:{number}: hash chain mismatch")
        current = observed
    return current


def write_envelope(
    path: Path,
    *,
    url: str,
    method: str,
    requested_at: str,
    status: int,
    duration_s: float,
    attempts: int,
    headers: dict[str, str],
    body: bytes,
    max_body_bytes: int | None = None,
) -> dict:
    """Save one JSON envelope; keep textual response bytes when valid UTF-8."""
    safe_headers = {
        name: (
            "REDACTED"
            if name.lower() in SENSITIVE_HEADERS or sensitive_parameter(name)
            else redact_header_value(value)
        )
        for name, value in headers.items()
    }
    result = {
        "url": redact_url(url),
        "method": method.upper(),
        "requested_at": requested_at,
        "status": status,
        "duration_s": duration_s,
        "attempts": attempts,
        "headers": safe_headers,
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    content_type = next(
        (value for name, value in headers.items() if name.lower() == "content-type"),
        "",
    )
    media_type = content_type.split(";", 1)[0].lower().strip()
    is_text = (
        media_type.startswith("text/")
        or media_type
        in {
            "application/json",
            "application/xml",
            "application/atom+xml",
            "application/rss+xml",
        }
        or media_type.endswith(("+json", "+xml"))
    )
    limit = (
        max_body_bytes
        if max_body_bytes is not None
        else load_config()["gateway"]["max_body_bytes"]
    )
    if len(body) > limit:
        result.update(body_omitted=f"over {limit} bytes", body_size=len(body))
    elif not is_text:
        result.update(body_omitted="non-text Content-Type", body_size=len(body))
    else:
        try:
            charset = next(
                (
                    part.split("=", 1)[1].strip().strip('"')
                    for part in content_type.split(";")[1:]
                    if part.strip().lower().startswith("charset=")
                ),
                "utf-8",
            )
            result["body"] = body.decode(charset)
        except (UnicodeDecodeError, LookupError):
            result.update(
                body_omitted="body cannot be decoded as declared text",
                body_size=len(body),
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
