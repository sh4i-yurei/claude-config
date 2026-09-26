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
        self.assertEqual(config["gateway"]["default_backoff_base_s"], 2)
        self.assertIn("gw.py", config["gateway"]["default_backoff_source"])
        self.assertEqual(config["providers"]["export.arxiv.org"]["backoff_base_s"], 3)
        self.assertIn(
            "gw.py", config["providers"]["export.arxiv.org"]["backoff_source"]
        )
        self.assertEqual(config["providers"]["api.core.ac.uk"]["backoff_base_s"], 6)
        self.assertIn("gw.py", config["providers"]["api.core.ac.uk"]["backoff_source"])
        self.assertEqual(
            config["providers"]["api.openalex.org"]["daily_budget_usd"], 1.0
        )
        self.assertIn(
            "known-apis.md", config["providers"]["api.openalex.org"]["budget_source"]
        )
        self.assertIn("contact_email", config["gateway"])
        self.assertNotIn("contact_email", config["agent"])
        self.assertEqual(config["presets"]["deep"]["rounds"], 3)
        self.assertEqual(
            config["providers"]["services.nvd.nist.gov"]["window_count"], 50
        )
        self.assertTrue(config["providers"]["api.crossref.org"]["contact_user_agent"])

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
            release_started = time.monotonic()
        child.join(timeout=2)
        self.assertEqual(child.exitcode, 0)
        self.assertFalse(queue.empty())
        self.assertGreaterEqual(queue.get(), release_started)

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
        self.assertNotIn('"Set-Cookie": "secret"', path.read_text())
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
        self.assertEqual(large["body_omitted"], "over 5242880 bytes")

    def test_envelope_uses_configured_body_limit(self):
        path = self.root / "response.json"
        result = write_envelope(
            path,
            url="https://example.org",
            method="GET",
            requested_at="2026-09-26T00:00:00Z",
            status=200,
            duration_s=0.1,
            attempts=1,
            headers={"Content-Type": "text/plain"},
            body=b"four",
            max_body_bytes=3,
        )
        self.assertEqual(result["body_size"], 4)
        self.assertEqual(result["body_omitted"], "over 3 bytes")

    def test_semicolon_separated_key_is_redacted(self):
        log = self.root / "testhost-2026-09.jsonl"
        entry = append_log(
            self.entry("https://example.org/?q=ok;api_key=SECRET"),
            path=log,
            lock_path=self.lock,
        )
        self.assertIn("q=ok;api_key=REDACTED", entry["url"])
        self.assertNotIn("SECRET", log.read_text())

    def test_url_redaction_keeps_nonsecret_query_bytes(self):
        log = self.root / "testhost-2026-09.jsonl"
        url = "https://example.org/?keywords=ansible%20roles&q=a;b&flag&api_key=SECRET"
        entry = append_log(self.entry(url), path=log, lock_path=self.lock)
        self.assertEqual(
            entry["url"],
            "https://example.org/?keywords=ansible%20roles&q=a;b&flag&api_key=REDACTED",
        )
        self.assertNotIn("SECRET", log.read_text())

    def test_semicolon_query_after_secret_keeps_search_term(self):
        log = self.root / "testhost-2026-09.jsonl"
        entry = append_log(
            self.entry("https://example.org/?api_key=PRIVATE;q=ansible"),
            path=log,
            lock_path=self.lock,
        )
        self.assertEqual(
            entry["url"], "https://example.org/?api_key=REDACTED;q=ansible"
        )
        self.assertNotIn("PRIVATE", log.read_text())

    def test_semantic_scholar_paging_token_is_redacted_from_request_records(self):
        url = (
            "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
            "?query=research&token=PAGE_CURSOR"
        )
        expected_url = url.replace("PAGE_CURSOR", "REDACTED")
        log = self.root / "testhost-2026-09.jsonl"
        entry = append_log(self.entry(url), path=log, lock_path=self.lock)
        self.assertEqual(entry["url"], expected_url)
        self.assertNotIn("PAGE_CURSOR", log.read_text())

        envelope = self.root / "response.json"
        body = b'{"token":"NEXT_PAGE_CURSOR","data":[]}'
        saved = write_envelope(
            envelope,
            url=url,
            method="GET",
            requested_at="2026-09-26T00:00:00Z",
            status=200,
            duration_s=0.1,
            attempts=1,
            headers={"Content-Type": "application/json"},
            body=body,
        )
        self.assertEqual(saved["url"], expected_url)
        self.assertEqual(saved["body"], body.decode())
        self.assertEqual(json.loads(envelope.read_text())["url"], expected_url)

    def test_quoted_header_credential_is_fully_redacted(self):
        path = self.root / "response.json"
        result = write_envelope(
            path,
            url="https://example.org",
            method="GET",
            requested_at="2026-09-26T00:00:00Z",
            status=200,
            duration_s=0.1,
            attempts=1,
            headers={
                "Content-Type": "text/plain",
                "Link": 'token="abc def"; rel="next"',
            },
            body=b"ok",
        )
        self.assertEqual(result["headers"]["Link"], 'token=REDACTED; rel="next"')
        self.assertNotIn("abc def", path.read_text())

    def test_envelope_redacts_url_credentials_and_keeps_declared_charset(self):
        path = self.root / "response.json"
        result = write_envelope(
            path,
            url="https://user:secret@example.org/?client_secret=hidden#token=more",
            method="GET",
            requested_at="2026-09-26T00:00:00Z",
            status=200,
            duration_s=0.2,
            attempts=1,
            headers={"Content-Type": "text/plain; charset=iso-8859-1"},
            body=b"caf\xe9",
        )
        self.assertEqual(result["body"], "café")
        self.assertEqual(result["url"], "https://example.org/?client_secret=REDACTED")
        self.assertNotIn("user:secret", path.read_text())
        self.assertNotIn("hidden", path.read_text())
        self.assertNotIn("token=more", path.read_text())

    def test_envelope_redacts_credentials_in_response_header_urls(self):
        path = self.root / "response.json"
        result = write_envelope(
            path,
            url="https://example.org",
            method="GET",
            requested_at="2026-09-26T00:00:00Z",
            status=302,
            duration_s=0.2,
            attempts=1,
            headers={
                "Content-Type": "text/plain",
                "Location": "https://user:pass@example.org/next?access_token=SECRET",
                "Link": '<https://example.org/more?api_key=HIDDEN>; rel="next"',
            },
            body=b"",
        )
        self.assertEqual(
            result["headers"]["Location"],
            "https://example.org/next?access_token=REDACTED",
        )
        self.assertIn("api_key=REDACTED", result["headers"]["Link"])
        self.assertNotIn("SECRET", path.read_text())
        self.assertNotIn("HIDDEN", path.read_text())
        self.assertNotIn("user:pass", path.read_text())

    def test_signed_request_url_credentials_are_removed_from_log_and_envelope(self):
        url = "https://example.org/object?part=7&X-Amz-Credential=PRIVATE&X-Amz-Signature=SIGNED&sig=AZURE"
        log = self.root / "testhost-2026-09.jsonl"
        appended = append_log(self.entry(url), path=log, lock_path=self.lock)
        envelope = self.root / "response.json"
        saved = write_envelope(
            envelope,
            url=url,
            method="GET",
            requested_at="2026-09-26T00:00:00Z",
            status=200,
            duration_s=0.2,
            attempts=1,
            headers={"Content-Type": "text/plain"},
            body=b"ok",
        )
        self.assertIn("part=7", saved["url"])
        self.assertIn("X-Amz-Credential=REDACTED", appended["url"])
        self.assertIn("X-Amz-Signature=REDACTED", saved["url"])
        self.assertIn("sig=REDACTED", saved["url"])
        for path in (log, envelope):
            self.assertNotIn("PRIVATE", path.read_text())
            self.assertNotIn("SIGNED", path.read_text())
            self.assertNotIn("AZURE", path.read_text())

    def test_token_bearing_response_header_is_redacted(self):
        path = self.root / "response.json"
        result = write_envelope(
            path,
            url="https://example.org",
            method="GET",
            requested_at="2026-09-26T00:00:00Z",
            status=200,
            duration_s=0.1,
            attempts=1,
            headers={
                "Content-Type": "text/plain",
                "X-Auth-Token": "PRIVATE",
                "X-Access-Token": "SECRET",
            },
            body=b"ok",
        )
        self.assertEqual(result["headers"]["X-Auth-Token"], "REDACTED")
        self.assertEqual(result["headers"]["X-Access-Token"], "REDACTED")
        self.assertNotIn("PRIVATE", path.read_text())
        self.assertNotIn("SECRET", path.read_text())


if __name__ == "__main__":
    unittest.main()
