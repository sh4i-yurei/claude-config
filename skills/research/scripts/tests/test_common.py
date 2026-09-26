"""Offline checks for B1's shared storage contract."""

import json
import multiprocessing
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import (
    append_log,
    gateway_lock,
    load_config,
    verify_log,
    write_envelope,
)


def wait_for_lock(lock_path: str, started, queue):
    started.set()
    with gateway_lock(Path(lock_path)):
        queue.put(time.monotonic())


class CommonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = self.root / "gateway.lock"

    def entry(self, url="https://api.example.org/?api_key=secret"):
        return {
            "ts": "2026-09-26T00:00:00Z",
            "via": "gw",
            "host": "api.example.org",
            "url": url,
            "status": 200,
            "duration_s": 0.1,
            "attempt": 1,
            "run": None,
            "repo": "claude-config",
            "archive": "70_Research/_lookups/test.json",
        }

    def test_config_has_presets_and_documented_provider_settings(self):
        config = load_config()
        self.assertEqual(config["gateway"]["margin"], 0.1)
        self.assertEqual(config["presets"]["deep"]["rounds"], 3)
        self.assertEqual(
            config["providers"]["services.nvd.nist.gov"]["window_count"], 50
        )

    def test_chain_continues_across_month_and_detects_tamper(self):
        logs = self.root / "70_Research" / "_log"
        first = logs / "testhost-2026-08.jsonl"
        second = logs / "testhost-2026-09.jsonl"
        a = append_log(self.entry(), path=first, lock_path=self.lock)
        b = append_log(
            self.entry("https://api.example.org/next"), path=second, lock_path=self.lock
        )
        self.assertEqual(a["url"], "https://api.example.org/?api_key=REDACTED")
        self.assertNotIn("secret", first.read_text())
        self.assertEqual(verify_log(first), a["h"])
        self.assertEqual(verify_log(second, a["h"]), b["h"])
        changed = json.loads(second.read_text())
        changed["status"] = 500
        second.write_text(json.dumps(changed) + "\n")
        with self.assertRaisesRegex(ValueError, "hash chain mismatch"):
            verify_log(second, a["h"])

    def test_lock_blocks_second_process_until_release(self):
        queue = multiprocessing.Queue()
        started = multiprocessing.Event()
        with gateway_lock(self.lock):
            child = multiprocessing.Process(
                target=wait_for_lock, args=(str(self.lock), started, queue)
            )
            child.start()
            self.assertTrue(started.wait(2))
            time.sleep(0.1)
            self.assertTrue(queue.empty())
        child.join(timeout=2)
        self.assertEqual(child.exitcode, 0)
        self.assertFalse(queue.empty())

    def test_envelope_preserves_text_and_omits_binary_and_oversize(self):
        path = self.root / "response.json"
        text = "café\n".encode()
        result = write_envelope(
            path,
            url="https://example.org/?email=private@example.org",
            method="GET",
            requested_at="2026-09-26T00:00:00Z",
            status=200,
            duration_s=0.2,
            attempts=1,
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Set-Cookie": "secret",
            },
            body=text,
        )
        self.assertEqual(result["body"], "café\n")
        self.assertEqual(json.loads(path.read_text()), result)
        self.assertNotIn("private@example.org", path.read_text())
        self.assertNotIn("secret", path.read_text())
        binary = write_envelope(
            path,
            url="https://example.org",
            method="GET",
            requested_at="2026-09-26T00:00:00Z",
            status=200,
            duration_s=0.2,
            attempts=1,
            headers={"Content-Type": "image/png"},
            body=b"\x89PNG",
        )
        self.assertNotIn("body", binary)
        self.assertEqual(binary["body_size"], 4)
        large = write_envelope(
            path,
            url="https://example.org",
            method="GET",
            requested_at="2026-09-26T00:00:00Z",
            status=200,
            duration_s=0.2,
            attempts=1,
            headers={"Content-Type": "text/plain"},
            body=b"a" * (5 * 1024 * 1024 + 1),
        )
        self.assertEqual(large["body_omitted"], "over 5 MB")


if __name__ == "__main__":
    unittest.main()
