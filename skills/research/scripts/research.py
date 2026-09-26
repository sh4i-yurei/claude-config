"""Run and check the versioned research workflow.

Usage: python3 research.py import-logs
       python3 research.py verify-log
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from common import (
    LOCK_PATH,
    LOG_FIELDS,
    gateway_lock,
    redact_url,
    vault_root,
    verify_log,
)

LOG_NAME = re.compile(r"^(?P<host>.+)-(?P<month>\d{4}-\d{2})\.jsonl$")


def timestamp_epoch(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    raise ValueError(f"invalid log timestamp: {value!r}")


def legacy_records(gateway_path: Path, fetch_path: Path) -> list[dict]:
    """Translate both retired logs without inventing fields they did not record."""
    records: list[dict] = []
    if gateway_path.exists():
        for raw in gateway_path.read_text(encoding="utf-8").splitlines():
            old = json.loads(raw)
            records.append(
                {
                    "ts": old["ts"],
                    "via": "gw",
                    "host": old.get("host", ""),
                    "url": old.get("url", ""),
                    "status": int(old.get("code", 0)),
                    "duration_s": old.get("dur"),
                    "attempt": old.get("attempt", 1),
                    "run": None,
                    "repo": None,
                    "archive": None,
                }
            )
    if fetch_path.exists():
        for raw in fetch_path.read_text(encoding="utf-8").splitlines():
            old = json.loads(raw)
            tool = old.get("tool", "")
            url = old.get("url", "")
            duration_ms = old.get("duration_ms")
            records.append(
                {
                    "ts": old["ts"],
                    "via": (
                        "firecrawl-connector"
                        if "firecrawl" in tool.lower()
                        else "webfetch"
                    ),
                    "host": urlsplit(url).hostname or old.get("domain", ""),
                    "url": url,
                    "status": None,
                    "duration_s": (
                        duration_ms / 1000
                        if isinstance(duration_ms, (int, float))
                        else None
                    ),
                    "attempt": 1,
                    "run": None,
                    "repo": None,
                    "archive": None,
                }
            )
    return records


def canonical(record: dict) -> dict:
    line = {field: record.get(field) for field in LOG_FIELDS}
    line["url"] = redact_url(str(line["url"] or ""))
    return line


def fingerprint(record: dict) -> str:
    return json.dumps(canonical(record), ensure_ascii=False, separators=(",", ":"))


def write_history(root: Path, hostname: str, records: list[dict]) -> None:
    """Rewrite this machine's monthly files in timestamp order with one chain."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in sorted(records, key=lambda item: timestamp_epoch(item["ts"])):
        month = datetime.fromtimestamp(
            timestamp_epoch(record["ts"]), timezone.utc
        ).strftime("%Y-%m")
        groups[month].append(canonical(record))

    previous = ""
    log_root = root / "70_Research" / "_log"
    log_root.mkdir(parents=True, exist_ok=True)
    for month in sorted(groups):
        target = log_root / f"{hostname}-{month}.jsonl"
        temporary = target.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            for record in groups[month]:
                serialized = json.dumps(
                    record, ensure_ascii=False, separators=(",", ":")
                )
                previous = hashlib.sha256((previous + serialized).encode()).hexdigest()[
                    :16
                ]
                stream.write(
                    json.dumps(
                        {**record, "h": previous},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        temporary.replace(target)


def import_logs(
    *,
    root: Path | None = None,
    gateway_path: Path | None = None,
    fetch_path: Path | None = None,
    hostname: str | None = None,
    lock_path: Path | None = None,
) -> int:
    root = root or vault_root()
    hostname = hostname or socket.gethostname()
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    gateway_path = gateway_path or config / "research-gw-log.jsonl"
    fetch_path = fetch_path or config / "research-fetches.log"
    lock_path = lock_path or LOCK_PATH
    log_root = root / "70_Research" / "_log"

    with gateway_lock(lock_path):
        current: list[dict] = []
        paths = sorted(log_root.glob(f"{hostname}-????-??.jsonl"))
        previous = ""
        for path in paths:
            previous = verify_log(path, previous)
        for path in paths:
            for raw in path.read_text(encoding="utf-8").splitlines():
                record = json.loads(raw)
                record.pop("h", None)
                current.append(canonical(record))
        seen = {fingerprint(record) for record in current}
        added = 0
        for record in legacy_records(gateway_path, fetch_path):
            identity = fingerprint(record)
            if identity not in seen:
                current.append(record)
                seen.add(identity)
                added += 1
        write_history(root, hostname, current)
    print(f"imported {added} legacy records; {len(current)} total")
    return 0


def verify_all(root: Path | None = None, lock_path: Path | None = None) -> int:
    log_root = (root or vault_root()) / "70_Research" / "_log"
    with gateway_lock(lock_path or LOCK_PATH):
        groups: dict[str, list[Path]] = defaultdict(list)
        for path in log_root.glob("*.jsonl"):
            match = LOG_NAME.match(path.name)
            if not match:
                raise ValueError(f"unexpected research log filename: {path.name}")
            groups[match.group("host")].append(path)

        files = lines = 0
        for paths in groups.values():
            previous = ""
            for path in sorted(paths):
                previous = verify_log(path, previous)
                files += 1
                lines += len(path.read_text(encoding="utf-8").splitlines())
    print(f"verified {lines} records across {files} files")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["import-logs"]:
        return import_logs()
    if argv == ["verify-log"]:
        return verify_all()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
