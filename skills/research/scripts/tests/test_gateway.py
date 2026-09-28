"""Offline checks for the research gateway's request boundary."""

import fcntl
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gw
from common import verify_log

PUBLIC_ADDRESS = gw.public_address


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.state = self.root / "state.json"
        self.lock = self.root / "gateway.lock"
        self.out = self.vault / "70_Research" / "_lookups" / "reply.json"
        self.patches = [
            patch.object(gw, "STATE", self.state),
            patch.object(gw, "LOCK", self.lock),
            patch.object(gw, "public_address", return_value="140.82.112.6"),
            patch.object(gw, "credential", return_value="TEST_ONLY_SECRET"),
            patch.dict(os.environ, {"SECOND_BRAIN": str(self.vault)}),
        ]
        for change in self.patches:
            change.start()
            self.addCleanup(change.stop)
        self.calls = []
        self.statuses = [200]
        self.returncodes = [0]
        self.remaining = 4000
        self.rate_headers = True
        self.usd_remaining = None
        self.retry_after = None
        self.expect_key = True

    def test_credential_resolves_exact_item_name_before_password(self):
        self.patches[3].stop()
        self.addCleanup(self.patches[3].start)
        listed = subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                [
                    {"id": "exact-id", "name": "Firecrawl API key"},
                    {"id": "notes-match", "name": "Bright Data API key"},
                ]
            ),
            stderr="",
        )
        password = subprocess.CompletedProcess(
            [], 0, stdout="TEST_ONLY_FIRECRAWL_SECRET\n", stderr=""
        )
        with (
            patch.object(gw, "session_token", return_value="session"),
            patch.object(gw.subprocess, "run", side_effect=[listed, password]) as run,
        ):
            value = gw.credential("Firecrawl API key")
        self.assertEqual(value, "TEST_ONLY_FIRECRAWL_SECRET")
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["bw", "list", "items", "--search", "Firecrawl API key"],
        )
        self.assertEqual(
            run.call_args_list[1].args[0], ["bw", "get", "password", "exact-id"]
        )

    def test_context7_uses_exact_key_name_and_bearer_header(self):
        self.expect_key = False
        with patch.object(
            gw,
            "credential",
            side_effect=lambda item: (
                self.assertEqual(item, "Context7 API key")
                or "TEST_ONLY_CONTEXT7_SECRET"
            ),
        ):
            self.assertEqual(
                self.run_gateway("https://context7.com/api/v3/search?query=test"), 0
            )
        _command, curl_input = self.calls[0]
        self.assertIn("Authorization: Bearer TEST_ONLY_CONTEXT7_SECRET", curl_input)
        self.assertNotIn("TEST_ONLY_CONTEXT7_SECRET", self.out.read_text())

    def test_firecrawl_uses_reported_credit_cost(self):
        self.assertEqual(gw.request_cost("api.firecrawl.dev", b'{"creditsUsed":2}'), 2)
        self.assertEqual(
            gw.request_cost(
                "api.firecrawl.dev", b'{"data":{"metadata":{"creditsUsed":3}}}'
            ),
            3,
        )
        self.assertEqual(gw.request_cost("api.firecrawl.dev", b"not json"), 1)
        self.assertEqual(gw.request_cost("api.github.com", b'{"creditsUsed":9}'), 1)

    def test_firecrawl_cycle_and_authoritative_seed_match_account(self):
        at = datetime(2026, 9, 26, 12, tzinfo=timezone.utc).timestamp()
        provider = gw.load_config()["providers"]["api.firecrawl.dev"]
        entry = {"window_used": 70, "window_end": at + 100}
        gw.seed_window(entry, provider, at)
        self.assertEqual(entry["window_used"], 211)
        self.assertEqual(
            datetime.fromtimestamp(entry["window_end"], timezone.utc),
            datetime(2026, 10, 19, tzinfo=timezone.utc),
        )
        gw.seed_window(entry, provider, at)
        self.assertEqual(entry["window_used"], 211)
        self.assertEqual(
            datetime.fromtimestamp(gw.window_end(at, provider), timezone.utc),
            datetime(2026, 10, 19, tzinfo=timezone.utc),
        )

    def fake_curl(self, command, *, input, capture_output, text, check):
        self.assertTrue(capture_output)
        self.assertTrue(text)
        self.assertFalse(check)
        self.assertNotIn("TEST_ONLY_SECRET", " ".join(command))
        if self.expect_key:
            self.assertIn("TEST_ONLY_SECRET", input)
        self.assertFalse(any(part.startswith("https://") for part in command))
        self.assertEqual(input.count("url = "), 1)
        with self.lock.open("a+b") as stream, self.assertRaises(BlockingIOError):
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = self.statuses[len(self.calls)]
        Path(command[command.index("--output") + 1]).write_bytes(b'{"ok":true}')
        headers = f"HTTP/2 {status}\r\nContent-Type: application/json\r\n"
        if self.rate_headers:
            headers += (
                f"X-RateLimit-Limit: 5000\r\nX-RateLimit-Remaining: {self.remaining}\r\n"
                "X-RateLimit-Reset: 2000000000\r\n"
            )
        if self.usd_remaining is not None:
            headers += f"X-RateLimit-Remaining-USD: {self.usd_remaining}\r\n"
        if self.retry_after is not None:
            headers += f"Retry-After: {self.retry_after}\r\n"
        Path(command[command.index("--dump-header") + 1]).write_bytes(
            (headers + "\r\n").encode()
        )
        self.calls.append((command, input))
        size = len(b'{"ok":true}')
        return type(
            "Result",
            (),
            {
                "stdout": f"{status} 0.2 {size}",
                "returncode": self.returncodes[-1],
            },
        )()

    def run_gateway(self, *args):
        with patch.object(gw.subprocess, "run", side_effect=self.fake_curl):
            return gw.main([str(self.out), "--", *args])

    def log_records(self):
        path = next((self.vault / "70_Research" / "_log").glob("*.jsonl"))
        verify_log(path)
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_key_injection_lock_envelope_and_chained_log(self):
        code = self.run_gateway("https://api.github.com/repos/openai/openai-python")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls), 1)
        command, curl_input = self.calls[0]
        self.assertEqual(command[0], "/usr/bin/curl")
        self.assertEqual(command[1], "-q")
        self.assertEqual(command[command.index("--connect-timeout") + 1], "10")
        self.assertEqual(command[command.index("--max-time") + 1], "120")
        self.assertIn("--globoff", command)
        self.assertIn("Authorization: Bearer TEST_ONLY_SECRET", curl_input)
        self.assertIn("keepbreath.ing-research/1.0", curl_input)
        saved = json.loads(self.out.read_text())
        self.assertEqual(saved["status"], 200)
        self.assertEqual(saved["body"], '{"ok":true}')
        self.assertEqual(saved["attempts"], 1)
        self.assertNotIn("TEST_ONLY_SECRET", self.out.read_text())
        records = self.log_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["via"], "gw")
        self.assertEqual(records[0]["status"], 200)
        self.assertEqual(records[0]["archive"], "70_Research/_lookups/reply.json")
        self.assertNotIn("TEST_ONLY_SECRET", json.dumps(records))
        self.assertEqual(
            json.loads(self.state.read_text())["api.github.com"]["code"], 200
        )

    def test_backoff_retries_and_records_each_attempt(self):
        self.statuses = [429, 200]
        with patch.object(gw.time, "sleep") as sleep:
            self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 0)
        sleep.assert_called_once_with(4)
        self.assertEqual(
            [record["status"] for record in self.log_records()], [429, 200]
        )
        self.assertEqual(json.loads(self.out.read_text())["attempts"], 2)

    def test_retry_after_extends_exponential_backoff(self):
        self.statuses = [429, 200]
        self.retry_after = "9"
        with patch.object(gw.time, "sleep") as sleep:
            self.assertEqual(
                self.run_gateway("https://context7.com/api/v3/search?query=test"), 0
            )
        sleep.assert_called_once_with(9.0)

    def test_retry_after_over_ceiling_refuses_without_sleep(self):
        self.statuses = [429]
        self.retry_after = "86400"
        with patch.object(gw.time, "sleep") as sleep:
            self.assertEqual(
                self.run_gateway("https://context7.com/api/v3/search?query=test"), 4
            )
        sleep.assert_not_called()

    def test_retry_stops_when_reported_margin_is_reached(self):
        self.statuses = [429, 200]
        self.remaining = 500
        with patch.object(gw.time, "sleep") as sleep:
            self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 4)
        sleep.assert_not_called()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(json.loads(self.out.read_text())["status"], 429)
        self.assertEqual(len(self.log_records()), 1)

    def test_pacing_waits_before_request(self):
        self.state.write_text(
            json.dumps(
                {
                    "api.github.com": {
                        "end": time.time() + 5,
                        "dur": 0.1,
                    }
                }
            )
        )
        with patch.object(gw.time, "sleep") as sleep:
            self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 0)
        self.assertEqual(sleep.call_count, 1)
        self.assertGreater(sleep.call_args.args[0], 4)

    def test_key_refusal_and_private_address_refusal_make_no_request(self):
        for args in (
            (
                "-H",
                "Authorization: Bearer supplied",
                "https://api.github.com/rate_limit",
            ),
            ("https://api.github.com/rate_limit?api_key=supplied",),
            ("-uuser:password", "https://api.github.com/rate_limit"),
            ("-Aother-agent", "https://api.github.com/rate_limit"),
            ("-H", "@/tmp/headers", "https://api.github.com/rate_limit"),
            ("-H", "User-Agent;", "https://api.github.com/rate_limit"),
            ("-H", "Authorization;", "https://api.github.com/rate_limit"),
            (
                "-H",
                "X-Test: ok\r\nAuthorization: Bearer CALLER_SECRET",
                "https://api.github.com/rate_limit",
            ),
            ("https://api.github.com/rate_limit?apiKey=supplied",),
            ("https://api.github.com/rate_limit?token=PAGE_CURSOR",),
            ("https://api.github.com/rate_limit?q=x;api_key=CALLER_SECRET",),
            ("--retry", "3", "https://api.github.com/rate_limit"),
            ("--compressed", "https://api.github.com/rate_limit"),
            ("--trace-ascii", "/tmp/trace", "https://api.github.com/rate_limit"),
            ("--libcurl", "/tmp/repro.c", "https://api.github.com/rate_limit"),
            (
                "--data-urlencode",
                "session@/run/user/1000/bw-session",
                "https://api.github.com/rate_limit",
            ),
            (
                "--data-urlencode",
                "api_key=CALLER_SECRET",
                "https://api.github.com/rate_limit",
            ),
            ("--data", "token=CALLER_SECRET", "https://api.github.com/rate_limit"),
            (
                "--json",
                '{"client_secret":"CALLER_SECRET"}',
                "https://api.github.com/rate_limit",
            ),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.run_gateway(*args), 2)
                self.assertFalse(self.calls)
        with patch.object(
            gw, "public_address", side_effect=ValueError("private address")
        ):
            self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 2)
        self.assertFalse(self.calls)
        self.assertFalse(self.out.exists())

    def test_attached_options_record_the_effective_method(self):
        url = "https://api.github.com/graphql"
        for args in (
            ("-XPOST",),
            ("-dfoo",),
            ('--json={"query":"test"}',),
        ):
            with self.subTest(args=args):
                self.assertEqual(gw.parse_call([*args, url])[2], "POST")

    def test_head_refuses_a_conflicting_effective_method(self):
        url = "https://api.github.com/rate_limit"
        for args in (("-I", "-XPOST", url), ("--head", "-dfoo", url)):
            with self.subTest(args=args):
                self.assertEqual(self.run_gateway(*args), 2)
                self.assertFalse(self.calls)

    def test_core_get_fields_are_encoded_into_one_gateway_url(self):
        url, args, method = gw.parse_call(
            [
                "-G",
                "--data-urlencode",
                "q=adversarial examples",
                "--data-urlencode",
                "limit=3",
                "https://api.core.ac.uk/v3/search/works/",
            ]
        )
        self.assertEqual(method, "GET")
        self.assertEqual(args, [])
        self.assertEqual(
            url,
            "https://api.core.ac.uk/v3/search/works/?q=adversarial%20examples&limit=3",
        )
        self.rate_headers = False
        self.assertEqual(
            self.run_gateway(
                "-G",
                "--data-urlencode",
                "q=adversarial examples",
                "--data-urlencode",
                "limit=3",
                "https://api.core.ac.uk/v3/search/works/",
            ),
            0,
        )
        self.assertEqual(len(self.calls), 1)
        self.assertIn("q=adversarial%20examples", self.log_records()[0]["url"])

    def test_internal_paging_url_keeps_cursor_off_argv_and_redacts_records(self):
        url = "https://api.semanticscholar.org/graph/v1/paper/search/bulk?token=PAGE_CURSOR"
        with patch.object(gw.subprocess, "run", side_effect=self.fake_curl):
            self.assertEqual(gw.request(self.out, url, [], "GET"), 0)
        self.assertIn("token=PAGE_CURSOR", self.calls[0][1])
        self.assertNotIn("PAGE_CURSOR", " ".join(self.calls[0][0]))
        self.assertIn("token=REDACTED", self.out.read_text())
        self.assertIn("token=REDACTED", json.dumps(self.log_records()))

    def test_incomplete_transfer_is_recorded_as_error(self):
        self.returncodes = [28]
        self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 1)
        self.assertEqual(json.loads(self.out.read_text())["status"], 0)
        self.assertEqual(self.log_records()[0]["status"], 0)
        self.assertEqual(
            json.loads(self.state.read_text())["api.github.com"]["errors"], 1
        )

    def test_oversize_transfer_is_bounded_and_omitted(self):
        self.returncodes = [63]
        self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 1)
        command = self.calls[0][0]
        self.assertEqual(
            command[command.index("--max-filesize") + 1], str(5 * 1024 * 1024 + 1)
        )
        saved = json.loads(self.out.read_text())
        self.assertNotIn("body", saved)
        self.assertEqual(saved["body_size"], len(b'{"ok":true}'))
        self.assertEqual(
            saved["sha256"],
            hashlib.sha256(b'{"ok":true}').hexdigest(),
        )

    def test_head_envelope_has_empty_body(self):
        self.assertEqual(self.run_gateway("-I", "https://api.github.com/rate_limit"), 0)
        saved = json.loads(self.out.read_text())
        self.assertEqual(saved["method"], "HEAD")
        self.assertEqual(saved["body"], "")

    def test_url_fragment_does_not_hide_gateway_query_key(self):
        config = gw.load_config()
        curl_input = gw.request_config(
            "https://api.openalex.org/works#fragment",
            config["providers"]["api.openalex.org"],
            config,
        )
        self.assertIn("api_key=TEST_ONLY_SECRET", curl_input)
        self.assertNotIn("#fragment", curl_input)

    def test_usage_includes_configured_provider_with_zero_calls(self):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 26, 18, 0, tzinfo=timezone.utc)

            def astimezone(self, tz=None):
                return super().astimezone(timezone.utc)

        log = self.vault / "70_Research" / "_log" / "test.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text(
            "\n".join(
                json.dumps(
                    {
                        "via": "gw",
                        "host": "api.github.com",
                        "ts": stamp,
                    }
                )
                for stamp in (
                    "2026-09-26T12:00:00Z",
                    "2026-09-03T12:00:00Z",
                    "2026-08-31T12:00:00Z",
                )
            )
            + "\n"
        )
        self.state.write_text(
            json.dumps(
                {
                    "api.github.com": {"remaining": 4000.0},
                    "api.firecrawl.dev": {
                        "window_used": 37,
                        "window_end": 4_000_000_000,
                    },
                }
            )
        )
        before_state = self.state.read_bytes()
        before_log = log.read_bytes()
        output = io.StringIO()
        with (
            patch.object(gw, "datetime", FixedDateTime),
            patch.object(gw, "request", side_effect=AssertionError("request made")),
            patch.object(
                gw.subprocess, "run", side_effect=AssertionError("subprocess started")
            ),
            patch.object(gw, "save_state", side_effect=AssertionError("state written")),
            patch.object(gw, "append_log", side_effect=AssertionError("log written")),
            redirect_stdout(output),
        ):
            self.assertEqual(gw.main(["--usage"]), 0)
        self.assertIn("api.github.com: today=1 month=2", output.getvalue())
        self.assertIn("remaining=4000.0 margin=10%", output.getvalue())
        self.assertIn(
            "api.firecrawl.dev: today=0 month=0 remaining=unknown margin=10% "
            "local_used=211/1000 local_remaining=789 local_margin=100",
            output.getvalue(),
        )
        self.assertIn("crt.sh: today=0 month=0", output.getvalue())
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assertEqual(log.read_bytes(), before_log)

    def test_reported_and_local_margins_refuse_before_request(self):
        self.state.write_text(
            json.dumps(
                {
                    "api.github.com": {
                        "limit": 5000,
                        "remaining": 500,
                        "reset": time.time() + 600,
                    }
                }
            )
        )
        self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 4)
        self.assertFalse(self.calls)
        self.state.write_text(
            json.dumps(
                {
                    "api.brightdata.com": {
                        "window_used": 4500,
                        "window_end": time.time() + 600,
                    }
                }
            )
        )
        self.assertEqual(self.run_gateway("https://api.brightdata.com/request"), 4)
        self.assertFalse(self.calls)

    def test_local_count_reaches_margin_after_first_request(self):
        self.rate_headers = False
        self.state.write_text(
            json.dumps(
                {
                    "api.brightdata.com": {
                        "window_used": 4499,
                        "window_end": time.time() + 600,
                    }
                }
            )
        )
        self.assertEqual(self.run_gateway("https://api.brightdata.com/request"), 0)
        self.out = self.out.with_name("reply-2.json")
        self.assertEqual(self.run_gateway("https://api.brightdata.com/request"), 4)
        self.assertEqual(len(self.calls), 1)

    def test_reported_quota_takes_precedence_over_local_counter(self):
        self.state.write_text(
            json.dumps(
                {
                    "api.github.com": {
                        "limit": 5000,
                        "remaining": 4000,
                        "reset": time.time() + 600,
                        "window_used": 4500,
                        "window_end": time.time() + 600,
                    }
                }
            )
        )
        self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 0)

    def test_openalex_usd_margin_uses_reported_remaining(self):
        self.rate_headers = False
        self.usd_remaining = 0.05
        self.assertEqual(self.run_gateway("https://api.openalex.org/works"), 0)
        self.out = self.out.with_name("reply-2.json")
        self.assertEqual(self.run_gateway("https://api.openalex.org/works"), 4)
        self.assertEqual(len(self.calls), 1)
        entry = json.loads(self.state.read_text())["api.openalex.org"]
        self.assertEqual(entry["remaining_usd"], 0.05)

    def test_expired_report_restarts_local_count_when_headers_disappear(self):
        self.rate_headers = False
        self.state.write_text(
            json.dumps(
                {
                    "api.github.com": {
                        "limit": 5000,
                        "remaining": 4000,
                        "reset": time.time() - 1,
                        "window_used": 4500,
                        "window_end": time.time() + 600,
                    }
                }
            )
        )
        self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 0)
        entry = json.loads(self.state.read_text())["api.github.com"]
        self.assertNotIn("limit", entry)
        self.assertEqual(entry["window_used"], 1)

    def test_daily_cap_uses_local_calendar_day(self):
        instant = datetime(2026, 9, 26, 0, 30, tzinfo=timezone.utc).timestamp()
        local_day = time.strptime("2026-09-25", "%Y-%m-%d")
        self.state.write_text(
            json.dumps({"api.github.com": {"day": "2026-09-25", "count": 300}})
        )
        with (
            patch.object(gw.time, "time", return_value=instant),
            patch.object(gw.time, "localtime", return_value=local_day),
        ):
            self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 3)
        self.assertFalse(self.calls)

    def test_pacing_across_midnight_resets_daily_count_before_request(self):
        before_midnight = 100.0
        after_midnight = 200.0
        old_day = time.strptime("2026-09-25", "%Y-%m-%d")
        new_day = time.strptime("2026-09-26", "%Y-%m-%d")
        self.state.write_text(
            json.dumps(
                {
                    "api.github.com": {
                        "day": "2026-09-25",
                        "count": 299,
                        "end": before_midnight + 2,
                        "dur": 0.1,
                    }
                }
            )
        )
        with (
            patch.object(
                gw.time,
                "time",
                side_effect=[
                    before_midnight,
                    after_midnight,
                    after_midnight,
                    after_midnight,
                ],
            ),
            patch.object(
                gw.time,
                "localtime",
                side_effect=lambda at: old_day if at < after_midnight else new_day,
            ),
            patch.object(gw.time, "sleep") as sleep,
        ):
            self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 0)
        sleep.assert_called_once()
        entry = json.loads(self.state.read_text())["api.github.com"]
        self.assertEqual(entry["day"], "2026-09-26")
        self.assertEqual(entry["count"], 1)

    def test_trailing_dot_uses_configured_provider_and_shared_host_state(self):
        self.expect_key = False
        self.state.write_text(
            json.dumps({"export.arxiv.org": {"end": time.time() + 0.1, "dur": 0.01}})
        )
        with patch.object(gw.time, "sleep") as sleep:
            self.assertEqual(self.run_gateway("https://export.arxiv.org./api/query"), 0)
        self.assertGreater(sleep.call_args.args[0], 3)
        self.assertIn("export.arxiv.org", json.loads(self.state.read_text()))
        self.assertNotIn("export.arxiv.org.", json.loads(self.state.read_text()))
        self.assertIn("https://export.arxiv.org/api/query", self.calls[0][1])

    def test_public_ipv6_literal_uses_bracketed_resolve_host(self):
        self.expect_key = False
        address = "2606:4700:4700::1111"
        with patch.object(gw, "public_address", return_value=f"[{address}]"):
            self.assertEqual(self.run_gateway(f"https://[{address}]/"), 0)
        command = self.calls[0][0]
        self.assertIn(f"[{address}]:443:[{address}]", command)

    def test_error_cooldown_and_daily_cap_refuse_before_request(self):
        self.state.write_text(
            json.dumps({"api.github.com": {"errors": 5, "end": time.time()}})
        )
        self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 3)
        self.assertFalse(self.calls)
        self.state.write_text(
            json.dumps(
                {
                    "api.github.com": {
                        "day": time.strftime("%Y-%m-%d", time.localtime()),
                        "count": 300,
                    }
                }
            )
        )
        self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 3)
        self.assertFalse(self.calls)

    def test_public_address_rejects_private_and_tailnet_results(self):
        for address in (
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.0.1",
            "100.100.100.100",
            "169.254.1.1",
            "::1",
            "fe80::1",
            "fd7a:115c:a1e0::1",
        ):
            with (
                self.subTest(address=address),
                patch.object(
                    gw.socket,
                    "getaddrinfo",
                    return_value=[(0, 0, 0, "", (address, 443))],
                ),
                self.assertRaisesRegex(ValueError, "private or non-public"),
            ):
                PUBLIC_ADDRESS("example.org")

    def test_public_address_prefers_ipv4_when_both_families_are_public(self):
        with patch.object(
            gw.socket,
            "getaddrinfo",
            return_value=[
                (0, 0, 0, "", ("2606:4700:4700::1111", 443)),
                (0, 0, 0, "", ("91.199.212.73", 443)),
            ],
        ):
            self.assertEqual(PUBLIC_ADDRESS("crt.sh"), "91.199.212.73")

    def test_public_address_rejects_multicast_even_with_public_unicast(self):
        with (
            patch.object(
                gw.socket,
                "getaddrinfo",
                return_value=[
                    (0, 0, 0, "", ("224.0.0.1", 443)),
                    (0, 0, 0, "", ("2606:4700:4700::1111", 443)),
                ],
            ),
            self.assertRaisesRegex(ValueError, "private or non-public"),
        ):
            PUBLIC_ADDRESS("example.org")

    def test_gateway_refuses_to_overwrite_a_note_or_existing_envelope(self):
        note = self.vault / "10_Projects" / "note.md"
        note.parent.mkdir(parents=True)
        note.write_text("keep me")
        self.assertEqual(
            gw.main([str(note), "--", "https://api.github.com/rate_limit"]), 2
        )
        self.assertEqual(note.read_text(), "keep me")

        existing = self.vault / "70_Research" / "_lookups" / "existing.json"
        existing.parent.mkdir(parents=True)
        existing.write_text("keep this too")
        self.assertEqual(
            gw.main([str(existing), "--", "https://api.github.com/rate_limit"]), 2
        )
        self.assertEqual(existing.read_text(), "keep this too")
        self.assertFalse(self.calls)

    def test_research_curl_environment_cannot_replace_curl(self):
        with patch.dict(os.environ, {"RESEARCH_CURL": "/tmp/capture-keys"}):
            self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 0)
        self.assertEqual(self.calls[0][0][0], "/usr/bin/curl")

    def test_caller_cannot_override_gateway_timeouts(self):
        for option in ("--max-time", "--connect-timeout"):
            with self.subTest(option=option):
                self.assertEqual(
                    self.run_gateway(
                        option, "999", "https://api.github.com/rate_limit"
                    ),
                    2,
                )
        self.assertFalse(self.calls)

    def test_dns_failure_is_request_error(self):
        with patch.object(
            gw,
            "public_address",
            side_effect=socket.gaierror(-2, "Name or service not known"),
        ):
            self.assertEqual(self.run_gateway("https://missing.example/rate_limit"), 1)
        self.assertFalse(self.calls)


if __name__ == "__main__":
    unittest.main()
