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
import threading
import time
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "mutants"
    if os.environ.get("MUTANT_UNDER_TEST") and ROOT.name != "mutants"
    else ROOT
)
sys.path.insert(0, str(SOURCE / "skills/research/scripts"))
sys.path.insert(0, str(SOURCE))

from skills.research.scripts import gw
from skills.research.scripts.common import verify_log

PUBLIC_ADDRESS = gw.public_address


def login(name, password, **extra):
    """One login item shaped as bw list items --search returns it."""
    return {
        "id": f"id-{name}",
        "name": name,
        "type": 1,
        "login": {"username": "research", "password": password},
        **extra,
    }


def search_answer(*items):
    """bw's answer to a search, as raw bytes on standard output."""
    return subprocess.CompletedProcess(
        ["bw"], 0, stdout=json.dumps(list(items)).encode(), stderr=b""
    )


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
        self.connect_times = [0.05]
        self.output_prefix = "reply"
        self.write_outs = None
        self.body_bytes = b'{"ok":true}'
        self.extra_headers = ""
        self.write_headers = True
        self.remaining = 4000
        self.rate_headers = True
        self.usd_remaining = None
        self.retry_after = None
        self.expect_key = True

    @contextmanager
    def bitwarden(self, answer, *, container=True):
        """Run gw.credential against a bw stand-in and yield the calls it got."""
        if not getattr(self, "credential_restored", False):
            self.patches[3].stop()
            self.addCleanup(self.patches[3].start)
            self.credential_restored = True
        marker = self.root / "containerenv"
        marker.unlink(missing_ok=True)
        if container:
            marker.write_text("")
        calls = []

        def run(command, **_kwargs):
            calls.append(command)
            return answer

        with (
            patch.object(gw.vault_item, "CONTAINER_MARKER", marker),
            patch.dict(os.environ, {"BW_SESSION": "dummy-session"}),
            patch.object(gw.subprocess, "run", side_effect=run),
        ):
            yield calls

    def test_credential_reads_the_exact_item_in_one_search(self):
        listed = search_answer(
            login("Firecrawl API key (old)", "TEST_ONLY_OLD"),
            login("Firecrawl API key", "TEST_ONLY_FIRECRAWL_SECRET"),
            login(
                "Bright Data API key",
                "TEST_ONLY_BRIGHT",
                notes="Firecrawl API key is the fallback",
            ),
        )
        with self.bitwarden(listed) as calls:
            value = gw.credential("Firecrawl API key")
        self.assertEqual(value, "TEST_ONLY_FIRECRAWL_SECRET")
        self.assertEqual(
            calls, [["bw", "list", "items", "--search", "Firecrawl API key"]]
        )

    def test_credential_refuses_no_exact_item_or_several(self):
        cases = {
            "none": (
                search_answer(login("Firecrawl API key (old)", "TEST_ONLY_OLD")),
                'Vaultwarden item unavailable: Firecrawl API key; no vault item is named exactly "Firecrawl API key"',
            ),
            "two": (
                search_answer(
                    login("Firecrawl API key", "TEST_ONLY_ONE"),
                    login("Firecrawl API key", "TEST_ONLY_TWO"),
                ),
                'Vaultwarden item unavailable: Firecrawl API key; 2 vault items are named exactly "Firecrawl API key"',
            ),
        }
        for label, (listed, message) in cases.items():
            with self.subTest(label):
                with (
                    self.bitwarden(listed),
                    self.assertRaises(ValueError) as raised,
                ):
                    gw.credential("Firecrawl API key")
                self.assertEqual(str(raised.exception), message)

    def test_credential_refuses_an_item_without_a_password(self):
        note = {
            "id": "id-note",
            "name": "Firecrawl API key",
            "type": 2,
            "notes": "kept as a secure note",
        }
        cases = {
            "empty password": search_answer(login("Firecrawl API key", "")),
            "secure note": search_answer(note),
        }
        for label, listed in cases.items():
            with self.subTest(label):
                with (
                    self.bitwarden(listed),
                    self.assertRaises(ValueError) as raised,
                ):
                    gw.credential("Firecrawl API key")
                self.assertEqual(
                    str(raised.exception),
                    "Vaultwarden item unavailable: Firecrawl API key; it has no password",
                )

    def test_credential_returns_the_password_exactly(self):
        listed = search_answer(login("Firecrawl API key", " TEST_ONLY_SPACED "))
        with self.bitwarden(listed):
            value = gw.credential("Firecrawl API key")
        self.assertEqual(value, " TEST_ONLY_SPACED ")

    def test_credential_refuses_outside_the_container_without_calling_bw(self):
        listed = search_answer(login("Firecrawl API key", "TEST_ONLY_FIRECRAWL"))
        with (
            self.bitwarden(listed, container=False) as calls,
            self.assertRaises(ValueError) as raised,
        ):
            gw.credential("Firecrawl API key")
        self.assertEqual(
            str(raised.exception),
            "Vaultwarden item unavailable: Firecrawl API key; "
            "bw runs only inside the dev container (distrobox enter dev)",
        )
        self.assertEqual(calls, [])

    def test_credential_refuses_a_locked_vault(self):
        locked = subprocess.CompletedProcess(
            ["bw"], 1, stdout=b"", stderr=b"Vault is locked."
        )
        with self.bitwarden(locked), self.assertRaises(ValueError) as raised:
            gw.credential("Firecrawl API key")
        self.assertEqual(
            str(raised.exception),
            "Vaultwarden item unavailable: Firecrawl API key; "
            'nothing from the vault for "Firecrawl API key". Is it unlocked? Run vu.',
        )

    def test_request_config_passes_a_credential_refusal_on_unchanged(self):
        config = gw.load_config()
        provider = config["providers"]["api.firecrawl.dev"]
        self.assertEqual(provider["key_item"], "Firecrawl API key")
        refusal = ValueError(
            "Vaultwarden item unavailable: Firecrawl API key; "
            'no vault item is named exactly "Firecrawl API key"'
        )
        with (
            patch.object(gw, "credential", side_effect=refusal),
            self.assertRaises(ValueError) as raised,
        ):
            gw.request_config("https://api.firecrawl.dev/v2/search", provider, config)
        self.assertIs(raised.exception, refusal)

    def test_gateway_runs_as_its_own_program(self):
        source_root = ROOT.parent if ROOT.name == "mutants" else ROOT
        with tempfile.TemporaryDirectory() as home:
            environment = {"PATH": "/usr/bin:/bin", "HOME": home}
            result = subprocess.run(
                [sys.executable, str(source_root / "skills/research/scripts/gw.py")],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue(
            result.stderr.startswith(
                "Paced, logged gateway for one HTTPS research request at a time."
            ),
            result.stderr,
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
        index = len(self.calls)
        status = self.statuses[min(index, len(self.statuses) - 1)]
        returncode = self.returncodes[min(index, len(self.returncodes) - 1)]
        if returncode in (7, 35) or (
            returncode == 28
            and self.connect_times[min(index, len(self.connect_times) - 1)] == 0
        ):
            status = 0
        Path(command[command.index("--output") + 1]).write_bytes(self.body_bytes)
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
        if isinstance(self.extra_headers, dict):
            for name, value in self.extra_headers.items():
                headers += f"{name}: {value}\r\n"
        else:
            headers += self.extra_headers
        if self.write_headers:
            Path(command[command.index("--dump-header") + 1]).write_bytes(
                (headers + "\r\n").encode()
            )
        self.calls.append((command, input))
        size = len(self.body_bytes)
        write_out = (
            self.write_outs[min(len(self.calls) - 1, len(self.write_outs) - 1)]
            if self.write_outs is not None
            else f"{status:03d} 0.2 {size} {self.connect_times[min(index, len(self.connect_times) - 1)]}"
        )
        return type(
            "Result",
            (),
            {
                "stdout": write_out,
                "returncode": returncode,
            },
        )()

    def run_gateway(self, *args):
        with patch.object(gw.subprocess, "run", side_effect=self.fake_curl):
            return gw.main([str(self.out), "--", *args])

    def request_site(self, site, *, host="api.brightdata.com"):
        self.out = self.out.with_name(
            f"{self.output_prefix}-{len(self.calls) + 1}.json"
        )
        body = json.dumps({"zone": "bright_data_agent", "url": site, "format": "raw"})
        with patch.object(gw.time, "sleep"):
            return self.run_gateway("--json", body, f"https://{host}/request")

    def gateway_entry(self, host="api.brightdata.com"):
        return json.loads(self.state.read_text())[host]

    def test_brightdata_failed_attempt_is_free_and_site_scoped(self):
        self.rate_headers = False
        self.statuses = [502]
        self.assertEqual(self.request_site("https://www.reddit.com/r/devops/"), 0)
        entry = self.gateway_entry()
        self.assertEqual(entry["window_used"], 0)
        self.assertEqual(entry["count"], 1)
        self.assertEqual(entry["errors"], 0)
        self.assertEqual(entry["targets"]["www.reddit.com"]["errors"], 1)

    def test_brightdata_success_is_billed_and_clears_site(self):
        self.statuses = [502, 200]
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        entry = self.gateway_entry()
        self.assertEqual(entry["window_used"], 1)
        self.assertEqual(entry.get("targets", {}), {})

    def test_brightdata_error_header_is_billed_and_site_scoped(self):
        self.extra_headers = {
            "x-brd-error": "Forbidden: Access to this site is restricted on the selected network type due to compliance policies. Please try switching to a different network type. In order to gain access with same network you may need to undergo a KYC process, you can do so by filling in the form: https://brightdata.com/cp/kyc If you have already completed the KYC approval, please contact your account manager for further details.",
            "x-brd-status-code": "502",
        }
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        entry = self.gateway_entry()
        self.assertEqual(entry["window_used"], 1)
        self.assertEqual(entry["targets"]["www.reddit.com"]["errors"], 1)
        self.assertEqual(entry["errors"], 0)

    def test_brightdata_header_name_is_case_insensitive(self):
        self.extra_headers = {"X-BRD-Error": "blocked"}
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        self.assertEqual(self.gateway_entry()["targets"]["www.reddit.com"]["errors"], 1)

    def test_different_sites_do_not_share_target_cooldown(self):
        self.statuses = [502]
        for index in range(6):
            self.assertEqual(self.request_site(f"https://site{index}.example.org/x"), 0)
        self.assertEqual(len(self.calls), 6)
        self.assertEqual(self.gateway_entry()["errors"], 0)
        self.assertEqual(len(self.gateway_entry()["targets"]), 6)

    def test_target_cooldown_stops_same_site_and_allows_another(self):
        self.statuses = [502]
        for _ in range(5):
            self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 3)
        self.assertEqual(
            stderr.getvalue().strip(),
            "[gw] REFUSED api.brightdata.com: error cooldown for www.reddit.com",
        )
        self.assertEqual(len(self.calls), 5)
        self.assertEqual(self.request_site("https://example.com/x"), 0)
        self.assertEqual(len(self.calls), 6)

    def test_other_site_success_does_not_reset_failing_site(self):
        self.statuses = [502, 200] * 5
        for _ in range(5):
            self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
            self.assertEqual(self.request_site("https://example.com/x"), 0)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 3)
        self.assertEqual(
            stderr.getvalue().strip(),
            "[gw] REFUSED api.brightdata.com: error cooldown for www.reddit.com",
        )
        self.assertEqual(len(self.calls), 10)

    def test_success_resets_target_streak(self):
        self.statuses = [502] * 4 + [200, 502]
        for _ in range(4):
            self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        self.assertEqual(self.gateway_entry()["targets"]["www.reddit.com"]["errors"], 1)

    def test_expired_target_streak_allows_request(self):
        self.state.write_text(
            json.dumps(
                {
                    "api.brightdata.com": {
                        "targets": {
                            "www.reddit.com": {"errors": 5, "end": time.time() - 14401}
                        }
                    }
                }
            )
        )
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.gateway_entry().get("targets", {}), {})

    def test_service_errors_share_host_cooldown(self):
        for host, status, returncode in (
            ("api.brightdata.com", 401, 0),
            ("api.brightdata.com", 403, 0),
            ("api.brightdata.com", 0, 7),
            ("api.brightdata.com", 0, 35),
            ("api.brightdata.com", 0, 28),
            ("api.firecrawl.dev", 402, 0),
        ):
            with self.subTest(host=host, status=status, returncode=returncode):
                self.state.unlink(missing_ok=True)
                self.calls.clear()
                self.output_prefix = f"reply-{host}-{status}-{returncode}"
                self.statuses = [status]
                self.returncodes = [returncode]
                self.connect_times = [0 if returncode == 28 else 0.05]
                for index in range(5):
                    self.assertEqual(
                        self.request_site(
                            f"https://site{index}.example.org/x", host=host
                        ),
                        1 if returncode else 0,
                    )
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    self.assertEqual(
                        self.request_site("https://sixth.example.org/x", host=host), 3
                    )
                self.assertEqual(
                    stderr.getvalue().strip(), f"[gw] REFUSED {host}: error cooldown"
                )
                self.assertEqual(len(self.calls), 5)
                entry = self.gateway_entry(host)
                self.assertEqual(entry["errors"], 5)
                self.assertEqual(entry.get("targets", {}), {})
                if host == "api.brightdata.com" and returncode:
                    self.assertEqual(entry["window_used"], 0)

    def test_timeout_after_connection_is_target_error(self):
        self.statuses = [0]
        self.returncodes = [28]
        self.connect_times = [0.05]
        for index in range(6):
            self.assertEqual(self.request_site(f"https://site{index}.example.org/x"), 1)
        entry = self.gateway_entry()
        self.assertEqual(entry["errors"], 0)
        self.assertEqual(entry["window_used"], 0)
        self.assertEqual(len(entry["targets"]), 6)

    def test_missing_connect_field_counts_as_connected(self):
        self.statuses = [0]
        self.returncodes = [28]
        original = self.fake_curl

        def three_fields(*args, **kwargs):
            result = original(*args, **kwargs)
            result.stdout = "000 0.2 0"
            return result

        with patch.object(self, "fake_curl", side_effect=three_fields):
            self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 1)
        self.assertEqual(self.gateway_entry()["targets"]["www.reddit.com"]["errors"], 1)
        self.assertEqual(self.gateway_entry()["errors"], 0)

    def test_attached_json_and_normalized_target_host(self):
        self.statuses = [502]
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        self.out = self.out.with_name("attached-with-header.json")
        body = '{"zone":"bright_data_agent","url":"https://WWW.Reddit.com./r/x","format":"raw"}'
        with patch.object(gw.time, "sleep"):
            self.assertEqual(
                self.run_gateway(
                    "-H",
                    "X-Test: harmless",
                    f"--json={body}",
                    "https://api.brightdata.com/request",
                ),
                0,
            )
        self.assertEqual(list(self.gateway_entry()["targets"]), ["www.reddit.com"])
        self.assertEqual(self.gateway_entry()["targets"]["www.reddit.com"]["errors"], 2)

    def test_malformed_curl_writeout_still_records_site_failure(self):
        self.returncodes = [28]
        original = self.fake_curl

        def malformed(*args, **kwargs):
            result = original(*args, **kwargs)
            result.stdout = "not-a-code 0.2 0 invalid-connect-time"
            return result

        with patch.object(self, "fake_curl", side_effect=malformed):
            self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 1)
        entry = self.gateway_entry()
        self.assertEqual(entry["errors"], 0)
        self.assertEqual(entry["targets"]["www.reddit.com"]["errors"], 1)
        self.assertEqual(entry["window_used"], 0)

    def test_service_error_keeps_target_streak_and_target_error_clears_host(self):
        self.statuses = [502] * 4 + [401, 502]
        for _ in range(4):
            self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        self.assertEqual(self.gateway_entry()["targets"]["www.reddit.com"]["errors"], 4)
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        self.assertEqual(self.gateway_entry()["targets"]["www.reddit.com"]["errors"], 5)
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 3)

    def test_target_error_clears_host_streak(self):
        self.statuses = [401] * 4 + [502, 401]
        for index in range(4):
            self.assertEqual(self.request_site(f"https://site{index}.example.org/x"), 0)
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 0)
        self.assertEqual(self.gateway_entry()["errors"], 0)
        self.assertEqual(self.request_site("https://example.org/x"), 0)
        self.assertEqual(self.request_site("https://next.example.org/x"), 0)

    def test_oversize_success_is_billed_and_target_error(self):
        self.statuses = [200]
        self.returncodes = [63]
        self.assertEqual(self.request_site("https://www.reddit.com/r/x"), 1)
        self.assertEqual(self.gateway_entry()["window_used"], 1)
        self.assertEqual(self.gateway_entry()["targets"]["www.reddit.com"]["errors"], 1)

    def test_no_usable_target_uses_host_streak(self):
        for body in (
            '{"query":"x","limit":10}',
            "not json",
            '{"url":9}',
            '{"url":"not a URL"}',
        ):
            with self.subTest(body=body):
                self.state.unlink(missing_ok=True)
                self.calls.clear()
                self.statuses = [502]
                for _ in range(5):
                    self.out = self.out.with_name(f"reply-{time.time_ns()}.json")
                    with patch.object(gw.time, "sleep"):
                        self.assertEqual(
                            self.run_gateway(
                                "--json", body, "https://api.firecrawl.dev/v2/search"
                            ),
                            0,
                        )
                self.out = self.out.with_name(f"reply-{time.time_ns()}.json")
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    self.assertEqual(
                        self.run_gateway(
                            "--json", body, "https://api.firecrawl.dev/v2/search"
                        ),
                        3,
                    )
                self.assertEqual(
                    stderr.getvalue().strip(),
                    "[gw] REFUSED api.firecrawl.dev: error cooldown",
                )
                self.assertEqual(
                    self.gateway_entry("api.firecrawl.dev")["window_used"], 5
                )
                self.assertNotIn("targets", self.gateway_entry("api.firecrawl.dev"))

    def test_other_providers_keep_host_streak_and_cost(self):
        self.statuses = [502]
        for _ in range(5):
            self.out = self.out.with_name(f"reply-{len(self.calls) + 1}.json")
            with patch.object(gw.time, "sleep"):
                self.assertEqual(
                    self.run_gateway("https://api.github.com/rate_limit"), 0
                )
        self.out = self.out.with_name("reply-6.json")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(self.run_gateway("https://api.github.com/rate_limit"), 3)
        self.assertEqual(
            stderr.getvalue().strip(), "[gw] REFUSED api.github.com: error cooldown"
        )
        self.assertEqual(self.gateway_entry("api.github.com")["window_used"], 5)
        self.assertNotIn("targets", self.gateway_entry("api.github.com"))

    def test_brightdata_without_json_keeps_host_streak(self):
        self.statuses = [502]
        for index in range(5):
            self.out = self.out.with_name(f"plain-{index}.json")
            with patch.object(gw.time, "sleep"):
                self.assertEqual(
                    self.run_gateway("https://api.brightdata.com/request"), 0
                )
        self.out = self.out.with_name("plain-sixth.json")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(self.run_gateway("https://api.brightdata.com/request"), 3)
        self.assertEqual(
            stderr.getvalue().strip(),
            "[gw] REFUSED api.brightdata.com: error cooldown",
        )
        entry = self.gateway_entry()
        self.assertEqual(entry["errors"], 5)
        self.assertEqual(entry["window_used"], 0)
        self.assertNotIn("targets", entry)

    def test_firecrawl_target_error_keeps_existing_billing(self):
        self.statuses = [502]
        self.assertEqual(
            self.request_site("https://example.org/x", host="api.firecrawl.dev"), 0
        )
        entry = self.gateway_entry("api.firecrawl.dev")
        self.assertEqual(entry["targets"]["example.org"]["errors"], 1)
        self.assertEqual(entry["window_used"], 1)

    def log_records(self):
        path = next((self.vault / "70_Research" / "_log").glob("*.jsonl"))
        verify_log(path)
        return [json.loads(line) for line in path.read_text().splitlines()]

    def observed_request(self, url="https://api.github.com/rate_limit", *args):
        self.out = self.out.with_name(f"reply-{len(self.calls) + 1}.json")
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = self.run_gateway(*args, url)
        return code, stdout.getvalue().splitlines(), stderr.getvalue().splitlines()

    def saved_entry(self, host="api.github.com"):
        return json.loads(self.state.read_text())[host]

    def put_entry(self, entry, host="api.github.com"):
        self.state.write_text(json.dumps({host: entry}))

    def test_request_address_refusals_print_exactly(self):
        for problem, code, message in (
            (
                socket.gaierror("lookup failed"),
                1,
                "[gw] ERROR api.github.com: DNS resolution failed: lookup failed",
            ),
            (ValueError("private address"), 2, "[gw] REFUSED: private address"),
        ):
            with (
                self.subTest(problem=problem),
                patch.object(gw, "public_address", side_effect=problem),
            ):
                self.assertEqual(self.observed_request(), (code, [], [message]))
                self.assertEqual(self.calls, [])

    def test_request_resolves_the_requested_host(self):
        def resolve(host, *_args, **_kwargs):
            if host != "api.github.com":
                raise socket.gaierror("unknown host")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.112.6", 443))]

        with (
            patch.object(gw, "public_address", PUBLIC_ADDRESS),
            patch.object(gw.socket, "getaddrinfo", side_effect=resolve),
        ):
            self.assertEqual(self.observed_request()[0], 0)
        self.assertEqual(
            self.calls[0][0][self.calls[0][0].index("--resolve") + 1],
            "api.github.com:443:140.82.112.6",
        )

    def test_request_cooldown_boundary_and_error_streak(self):
        settings = gw.load_config()["gateway"]
        instant = 2_000_000_000.0
        cases = (
            (settings["error_streak"], instant - settings["error_cooldown_s"] + 1, 3),
            (settings["error_streak"], instant - settings["error_cooldown_s"], 0),
            (
                settings["error_streak"] - 1,
                instant - settings["error_cooldown_s"] + 1,
                0,
            ),
        )
        for index, (errors, end, expected) in enumerate(cases):
            with (
                self.subTest(index=index),
                patch.object(gw.time, "time", return_value=instant),
                patch.object(gw.time, "sleep"),
            ):
                self.put_entry({"errors": errors, "end": end})
                code, stdout, stderr = self.observed_request()
                self.assertEqual(code, expected)
                self.assertEqual(
                    stderr,
                    ["[gw] REFUSED api.github.com: error cooldown"] if expected else [],
                )
                self.assertEqual(
                    stdout,
                    []
                    if expected
                    else [
                        "[gw] api.github.com attempt 1 HTTP 200 0.20s",
                        "[gw] requests made: 1",
                    ],
                )
                self.assertEqual(len(self.calls), index)

    def test_request_daily_cap_boundary_and_new_day(self):
        cap = gw.load_config()["gateway"]["daily_host_cap"]
        day = time.strptime("2026-09-26", "%Y-%m-%d")
        for index, (saved_day, count, code, final_count) in enumerate(
            (
                ("2026-09-26", cap, 3, None),
                ("2026-09-26", cap - 1, 0, cap),
                ("2026-09-25", cap, 0, 1),
            )
        ):
            with (
                self.subTest(index=index),
                patch.object(gw.time, "localtime", return_value=day),
                patch.object(gw.time, "sleep"),
            ):
                self.put_entry({"day": saved_day, "count": count})
                result, stdout, stderr = self.observed_request()
                self.assertEqual(result, code)
                self.assertEqual(
                    stderr, ["[gw] REFUSED api.github.com: daily cap"] if code else []
                )
                self.assertEqual(
                    stdout,
                    []
                    if code
                    else [
                        "[gw] api.github.com attempt 1 HTTP 200 0.20s",
                        "[gw] requests made: 1",
                    ],
                )
                if final_count is not None:
                    self.assertEqual(self.saved_entry()["count"], final_count)
                self.assertEqual(len(self.calls), index)

    def test_request_first_attempt_cap_after_day_changes(self):
        cap = gw.load_config()["gateway"]["daily_host_cap"]
        previous = time.strptime("2026-09-25", "%Y-%m-%d")
        current = time.strptime("2026-09-26", "%Y-%m-%d")
        self.put_entry({"day": "2026-09-26", "count": cap})
        with patch.object(gw.time, "localtime", side_effect=[previous, current]):
            code, stdout, stderr = self.observed_request()
        self.assertEqual(code, 3)
        self.assertEqual(stdout, [])
        self.assertEqual(
            stderr, ["[gw] REFUSED api.github.com: daily cap before request"]
        )
        self.assertEqual(self.calls, [])
        self.assertFalse(self.out.exists())

    def test_request_margin_and_config_refusals_print_exactly(self):
        with patch.object(gw, "margin_refusal", return_value="quota held"):
            self.assertEqual(
                self.observed_request(),
                (4, [], ["[gw] REFUSED api.github.com: quota held"]),
            )
        with patch.object(gw, "request_config", side_effect=ValueError("bad config")):
            self.assertEqual(
                self.observed_request(),
                (2, [], ["[gw] REFUSED api.github.com: bad config"]),
            )
        self.assertEqual(self.calls, [])

    def test_request_pacing_uses_provider_floor_ceiling_and_elapsed_time(self):
        instant = 2_000_000_000.0
        cases = (
            ("export.arxiv.org", 0.1, 1.0, 2.0),
            ("api.github.com", 0.01, 0.5, 0.5),
            ("api.github.com", 20.0, 1.0, 119.0),
            ("api.github.com", 2.0, 1.0, 19.0),
            ("api.github.com", 2.0, 20.0, 0.0),
        )
        for index, (host, duration, elapsed, expected_wait) in enumerate(cases):
            with (
                self.subTest(index=index),
                patch.object(gw.time, "time", return_value=instant),
                patch.object(gw.time, "sleep") as sleep,
            ):
                self.expect_key = host == "api.github.com"
                self.put_entry({"end": instant - elapsed, "dur": duration}, host)
                code, stdout, stderr = self.observed_request(
                    f"https://{host}/rate_limit"
                )
                self.assertEqual(code, 0)
                self.assertEqual(
                    stdout,
                    [f"[gw] {host} attempt 1 HTTP 200 0.20s", "[gw] requests made: 1"],
                )
                self.assertEqual(
                    stderr,
                    [f"[gw] pacing {host}: waiting {expected_wait:.1f}s"]
                    if expected_wait
                    else [],
                )
                self.assertEqual(
                    sleep.call_args_list,
                    [unittest.mock.call(expected_wait)] if expected_wait else [],
                )

    def test_request_unlisted_host_uses_configured_gap_floor(self):
        instant = 2_000_000_000.0
        host = "2606:4700:4700::1111"
        config = gw.load_config()
        config["gateway"]["default_gap_floor_s"] = 0.5
        self.expect_key = False
        self.put_entry({"end": instant, "dur": 0.01}, host)
        with (
            patch.object(gw, "load_config", return_value=config),
            patch.object(gw.time, "time", return_value=instant),
            patch.object(gw.time, "sleep") as sleep,
        ):
            code, stdout, stderr = self.observed_request(f"https://[{host}]/")
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout, [f"[gw] {host} attempt 1 HTTP 200 0.20s", "[gw] requests made: 1"]
        )
        self.assertEqual(stderr, [f"[gw] pacing {host}: waiting 0.5s"])
        sleep.assert_called_once_with(0.5)

    def test_request_curl_command_and_ipv6_resolve(self):
        settings = gw.load_config()["gateway"]
        for host, url in (
            ("api.github.com", "https://api.github.com/rate_limit"),
            ("2606:4700:4700::1111", "https://[2606:4700:4700::1111]/"),
        ):
            with self.subTest(host=host):
                self.expect_key = host == "api.github.com"
                self.assertEqual(self.observed_request(url)[0], 0)
                command = self.calls[-1][0]
                body = command[command.index("--output") + 1]
                headers = command[command.index("--dump-header") + 1]
                resolve_host = f"[{host}]" if ":" in host else host
                self.assertEqual(
                    command,
                    [
                        gw.CURL,
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
                        f"{resolve_host}:443:140.82.112.6",
                        "--output",
                        body,
                        "--max-filesize",
                        str(settings["max_body_bytes"] + 1),
                        "--dump-header",
                        headers,
                        "--write-out",
                        "%{http_code} %{time_total} %{size_download} %{time_connect}",
                        "--config",
                        "-",
                    ],
                )

    def test_request_write_out_fields_and_transfer_failure(self):
        cases = (
            ("200 0.25 11", 0, 200, 0.25),
            ("200 0.25", 0, 200, 0.25),
            ("200", 0, 200, 0.0),
            ("", 0, 0, 0.0),
            ("abc", 0, 0, 0.0),
            ("200 0.25 11", 28, 0, 0.25),
        )
        for index, (write_out, returncode, status, duration) in enumerate(cases):
            with self.subTest(index=index):
                self.write_outs = [write_out] * (index + 1)
                self.returncodes = [0] * index + [returncode]
                self.put_entry({})
                code, stdout, stderr = self.observed_request()
                self.assertEqual(code, 1 if status == 0 else 0)
                self.assertEqual(
                    stdout,
                    [
                        f"[gw] api.github.com attempt 1 HTTP {status} {duration:.2f}s",
                        "[gw] requests made: 1",
                    ],
                )
                self.assertEqual(stderr, [])
                self.assertEqual(
                    json.loads(self.out.read_text())["duration_s"], duration
                )
                self.assertEqual(self.log_records()[-1]["duration_s"], duration)
                self.assertEqual(self.saved_entry()["code"], status)

    def test_request_missing_download_size_is_zero_on_oversize(self):
        self.body_bytes = b""
        self.returncodes = [63]
        for write_out in ("200 0.25", "abc"):
            with self.subTest(write_out=write_out):
                self.write_outs = [write_out] * (len(self.calls) + 1)
                self.put_entry({})
                self.assertEqual(self.observed_request()[0], 1)
                self.assertEqual(json.loads(self.out.read_text())["body_size"], 0)

    def test_request_oversize_and_normal_body_fields(self):
        limit = gw.load_config()["gateway"]["max_body_bytes"]
        self.write_outs = ["200 0.25 4096"]
        self.returncodes = [63]
        self.assertEqual(self.observed_request()[0], 1)
        saved = json.loads(self.out.read_text())
        self.assertEqual(
            saved["body_omitted"], f"curl stopped response over {limit} bytes"
        )
        self.assertEqual(saved["body_size"], 4096)
        self.write_outs = ["200 0.25 4096", "200 0.25 11"]
        self.returncodes = [63, 0]
        self.assertEqual(self.observed_request()[0], 0)
        saved = json.loads(self.out.read_text())
        self.assertNotIn("body_omitted", saved)
        self.assertNotIn("body_size", saved)

    def test_request_success_messages_log_and_envelope(self):
        with patch.dict(os.environ, {"RESEARCH_RUN": "run-87"}):
            self.assertEqual(
                self.observed_request(),
                (
                    0,
                    [
                        "[gw] api.github.com attempt 1 HTTP 200 0.20s",
                        "[gw] requests made: 1",
                    ],
                    [],
                ),
            )
        record = self.log_records()[-1]
        saved = json.loads(self.out.read_text())
        self.assertEqual(record["run"], "run-87")
        self.assertEqual(record["attempt"], 1)
        self.assertEqual(record["status"], 200)
        for stamp in (record["ts"], saved["requested_at"]):
            self.assertTrue(stamp.endswith("Z"), stamp)
            self.assertEqual(
                datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo,
                timezone.utc,
            )
        self.assertEqual(self.saved_entry()["code"], 200)
        with patch.dict(os.environ, {"RESEARCH_RUN": ""}, clear=False):
            del os.environ["RESEARCH_RUN"]
            self.assertEqual(self.observed_request()[0], 0)
        self.assertIsNone(self.log_records()[-1]["run"])

    def test_request_logs_without_relocking_the_gateway_lock(self):
        result = []
        append_log = gw.append_log

        def append_with_gateway_lock(entry, **kwargs):
            return append_log(entry, lock_path=self.lock, **kwargs)

        with patch.object(gw, "append_log", side_effect=append_with_gateway_lock):
            worker = threading.Thread(
                target=lambda: result.append(self.observed_request()), daemon=True
            )
            worker.start()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive(), "request waited on its own gateway lock")
        self.assertEqual(
            result,
            [
                (
                    0,
                    [
                        "[gw] api.github.com attempt 1 HTTP 200 0.20s",
                        "[gw] requests made: 1",
                    ],
                    [],
                )
            ],
        )
        self.assertEqual(len(self.log_records()), 1)

    def test_request_window_restarts_at_boundary_and_accumulates_inside(self):
        instant = 2_000_000_000.0
        self.rate_headers = False
        for index, (old_end, expected_used) in enumerate(
            ((instant - 1, 1), (instant, 1), (instant + 100, 8))
        ):
            with (
                self.subTest(index=index),
                patch.object(gw.time, "time", return_value=instant),
            ):
                self.put_entry({"window_end": old_end, "window_used": 7})
                self.assertEqual(self.observed_request()[0], 0)
                entry = self.saved_entry()
                self.assertEqual(entry["window_used"], expected_used)
                self.assertEqual(
                    entry["window_end"],
                    instant + 3600 if old_end <= instant else old_end,
                )

    def test_request_retry_backoff_and_bounded_retry_after(self):
        cases = (("api.github.com", 4), ("export.arxiv.org", 6))
        for host, backoff in cases:
            with self.subTest(host=host), patch.object(gw.time, "sleep") as sleep:
                self.expect_key = host == "api.github.com"
                self.statuses = (
                    [429, 200]
                    if not self.calls
                    else [200] * len(self.calls) + [429, 200]
                )
                code, stdout, stderr = self.observed_request(
                    f"https://{host}/rate_limit"
                )
                self.assertEqual(code, 0)
                self.assertEqual(
                    stdout,
                    [
                        f"[gw] {host} attempt 1 HTTP 429 0.20s",
                        f"[gw] {host} attempt 2 HTTP 200 0.20s",
                        "[gw] requests made: 2",
                    ],
                )
                self.assertEqual(
                    stderr, [f"[gw] 429 from {host}: retry backoff {backoff}s"]
                )
                sleep.assert_called_once_with(backoff)
        self.retry_after = "121"
        self.expect_key = True
        self.put_entry({})
        self.statuses = [200] * len(self.calls) + [429]
        with patch.object(gw.time, "sleep") as sleep:
            code, stdout, stderr = self.observed_request()
        self.assertEqual(
            (code, stderr),
            (4, ["[gw] REFUSED api.github.com: Retry-After exceeds the bounded wait"]),
        )
        self.assertEqual(
            stdout,
            ["[gw] api.github.com attempt 1 HTTP 429 0.20s", "[gw] requests made: 1"],
        )
        sleep.assert_not_called()

    def test_request_retry_margin_prints_exact_refusal(self):
        self.statuses = [429]
        self.remaining = 500
        with patch.object(gw.time, "sleep") as sleep:
            code, stdout, stderr = self.observed_request()
        self.assertEqual(code, 4)
        self.assertEqual(
            stdout,
            ["[gw] api.github.com attempt 1 HTTP 429 0.20s", "[gw] requests made: 1"],
        )
        self.assertEqual(
            stderr,
            [
                "[gw] REFUSED api.github.com: reported quota margin reached; resets 2033-05-18T03:33:20+00:00 before retry"
            ],
        )
        sleep.assert_not_called()

    def test_request_daily_cap_between_attempts_keeps_envelope(self):
        self.statuses = [429, 200]
        cap = gw.load_config()["gateway"]["daily_host_cap"]
        self.put_entry({"day": "2026-09-26", "count": cap - 1})
        day = time.strptime("2026-09-26", "%Y-%m-%d")
        with (
            patch.object(gw.time, "localtime", return_value=day),
            patch.object(gw.time, "sleep") as sleep,
        ):
            code, stdout, stderr = self.observed_request()
        self.assertEqual(code, 3)
        self.assertEqual(
            stdout,
            ["[gw] api.github.com attempt 1 HTTP 429 0.20s", "[gw] requests made: 1"],
        )
        self.assertEqual(
            stderr,
            [
                "[gw] 429 from api.github.com: retry backoff 4s",
                "[gw] REFUSED api.github.com: daily cap before request",
            ],
        )
        self.assertEqual(json.loads(self.out.read_text())["status"], 429)
        self.assertEqual(len(self.calls), 1)
        sleep.assert_called_once_with(4)

    def test_request_status_classification_and_duration_floor(self):
        for index, (status, expected_errors) in enumerate(
            (
                (0, 3),
                (399, 0),
                (400, 3),
                (404, 0),
                (429, 0),
                (500, 3),
                (599, 3),
                (600, 0),
            )
        ):
            with self.subTest(status=status), patch.object(gw.time, "sleep"):
                self.statuses = [200] * len(self.calls) + (
                    [429, 429, 429] if status == 429 else [status]
                )
                self.write_outs = ["200 0.1 11"] * len(self.calls) + (
                    ["429 0.1 11"] * 3 if status == 429 else [f"{status} 0.1 11"]
                )
                self.put_entry({"errors": 2, "dur": 0.5})
                code, stdout, stderr = self.observed_request()
                entry = self.saved_entry()
                self.assertEqual(entry["errors"], expected_errors)
                self.assertEqual(entry["code"], status)
                self.assertEqual(entry["dur"], 0.5)
                self.assertEqual(
                    stdout[-1], f"[gw] requests made: {3 if status == 429 else 1}"
                )

    def test_request_two_attempts_sum_durations_and_save_last(self):
        self.statuses = [429, 200]
        self.write_outs = ["429 0.25 11", "200 0.5 11"]
        instant = 2_000_000_000.0
        with (
            patch.object(gw.time, "time", return_value=instant),
            patch.object(gw.time, "sleep") as sleep,
        ):
            code, stdout, stderr = self.observed_request()
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            [
                "[gw] api.github.com attempt 1 HTTP 429 0.25s",
                "[gw] api.github.com attempt 2 HTTP 200 0.50s",
                "[gw] requests made: 2",
            ],
        )
        self.assertEqual(stderr, ["[gw] 429 from api.github.com: retry backoff 4s"])
        sleep.assert_called_once_with(4)
        self.assertEqual(json.loads(self.out.read_text())["duration_s"], 0.75)
        self.assertEqual(self.saved_entry()["dur"], 0.5)
        self.assertEqual(self.saved_entry()["end"], instant)

    def test_request_second_retry_doubles_backoff_and_stops_at_limit(self):
        self.statuses = [429, 429, 429]
        with patch.object(gw.time, "sleep") as sleep:
            code, stdout, stderr = self.observed_request()
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            [
                "[gw] api.github.com attempt 1 HTTP 429 0.20s",
                "[gw] api.github.com attempt 2 HTTP 429 0.20s",
                "[gw] api.github.com attempt 3 HTTP 429 0.20s",
                "[gw] requests made: 3",
            ],
        )
        self.assertEqual(
            stderr,
            [
                "[gw] 429 from api.github.com: retry backoff 4s",
                "[gw] 429 from api.github.com: retry backoff 8s",
            ],
        )
        self.assertEqual(
            sleep.call_args_list, [unittest.mock.call(4), unittest.mock.call(8)]
        )
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(json.loads(self.out.read_text())["attempts"], 3)

    def test_request_third_retry_uses_exponential_backoff(self):
        config = gw.load_config()
        config["gateway"]["max_attempts"] = 4
        self.statuses = [429] * 4
        with (
            patch.object(gw, "load_config", return_value=config),
            patch.object(gw.time, "sleep") as sleep,
        ):
            code, stdout, stderr = self.observed_request()
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            [
                "[gw] api.github.com attempt 1 HTTP 429 0.20s",
                "[gw] api.github.com attempt 2 HTTP 429 0.20s",
                "[gw] api.github.com attempt 3 HTTP 429 0.20s",
                "[gw] api.github.com attempt 4 HTTP 429 0.20s",
                "[gw] requests made: 4",
            ],
        )
        self.assertEqual(
            stderr,
            [
                "[gw] 429 from api.github.com: retry backoff 4s",
                "[gw] 429 from api.github.com: retry backoff 8s",
                "[gw] 429 from api.github.com: retry backoff 16s",
            ],
        )
        self.assertEqual(
            sleep.call_args_list,
            [unittest.mock.call(4), unittest.mock.call(8), unittest.mock.call(16)],
        )

    def test_request_http_date_retry_after_controls_wait(self):
        instant = 2_000_000_000.0
        self.statuses = [429, 200]
        self.retry_after = "Wed, 18 May 2033 03:33:50 GMT"
        with (
            patch.object(gw.time, "time", return_value=instant),
            patch.object(gw.time, "sleep") as sleep,
        ):
            code, stdout, stderr = self.observed_request()
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            [
                "[gw] api.github.com attempt 1 HTTP 429 0.20s",
                "[gw] api.github.com attempt 2 HTTP 200 0.20s",
                "[gw] requests made: 2",
            ],
        )
        self.assertEqual(stderr, ["[gw] 429 from api.github.com: retry backoff 30s"])
        sleep.assert_called_once_with(30.0)

    def test_request_retry_after_at_ceiling_is_allowed(self):
        self.statuses = [429, 200]
        self.retry_after = "120"
        with patch.object(gw.time, "sleep") as sleep:
            code, stdout, stderr = self.observed_request()
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            [
                "[gw] api.github.com attempt 1 HTTP 429 0.20s",
                "[gw] api.github.com attempt 2 HTTP 200 0.20s",
                "[gw] requests made: 2",
            ],
        )
        self.assertEqual(stderr, ["[gw] 429 from api.github.com: retry backoff 120s"])
        sleep.assert_called_once_with(120.0)

    def test_request_reads_only_maximum_body_plus_one_byte(self):
        limit = gw.load_config()["gateway"]["max_body_bytes"]
        self.body_bytes = b"x" * (limit + 2)
        self.returncodes = [63]
        self.write_outs = [f"200 0.25 {limit + 2}"]
        self.assertEqual(self.observed_request()[0], 1)
        saved = json.loads(self.out.read_text())
        self.assertEqual(saved["body_size"], limit + 2)
        self.assertEqual(
            saved["sha256"], hashlib.sha256(self.body_bytes[: limit + 1]).hexdigest()
        )

    def test_request_provider_cost_adds_to_unexpired_window(self):
        instant = 2_000_000_000.0
        self.expect_key = True
        self.rate_headers = False
        self.body_bytes = b'{"creditsUsed":2}'
        self.put_entry(
            {"window_used": 7, "window_end": instant + 100}, "api.firecrawl.dev"
        )
        with patch.object(gw.time, "time", return_value=instant):
            code, stdout, stderr = self.observed_request(
                "https://api.firecrawl.dev/v2/search"
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            [
                "[gw] api.firecrawl.dev attempt 1 HTTP 200 0.20s",
                "[gw] requests made: 1",
            ],
        )
        self.assertEqual(stderr, [])
        self.assertEqual(self.saved_entry("api.firecrawl.dev")["window_used"], 9)

    def test_request_seeds_provider_window_before_snapshot_expires(self):
        instant = datetime(2026, 9, 26, 12, tzinfo=timezone.utc).timestamp()
        self.rate_headers = False
        with patch.object(gw.time, "time", return_value=instant):
            code, stdout, stderr = self.observed_request(
                "https://api.firecrawl.dev/v2/search"
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            [
                "[gw] api.firecrawl.dev attempt 1 HTTP 200 0.20s",
                "[gw] requests made: 1",
            ],
        )
        self.assertEqual(stderr, [])
        entry = self.saved_entry("api.firecrawl.dev")
        self.assertEqual(entry["window_used"], 212)
        self.assertEqual(
            entry["window_end"], datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp()
        )

    def test_request_status_200_300_and_301_duration_boundary(self):
        for index, (status, expected_duration) in enumerate(
            ((200, 0.1), (300, 0.5), (301, 0.5))
        ):
            with self.subTest(status=status):
                self.put_entry({"dur": 0.5})
                self.statuses = [200] * len(self.calls) + [status]
                self.write_outs = ["200 0.1 11"] * len(self.calls) + [
                    f"{status} 0.1 11"
                ]
                code, stdout, stderr = self.observed_request()
                self.assertEqual(code, 0)
                self.assertEqual(
                    stdout,
                    [
                        f"[gw] api.github.com attempt 1 HTTP {status} 0.10s",
                        "[gw] requests made: 1",
                    ],
                )
                self.assertEqual(stderr, [])
                self.assertEqual(self.saved_entry()["dur"], expected_duration)

    def test_request_missing_response_headers_still_writes_envelope(self):
        self.write_headers = False
        code, stdout, stderr = self.observed_request()
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            ["[gw] api.github.com attempt 1 HTTP 200 0.20s", "[gw] requests made: 1"],
        )
        self.assertEqual(stderr, [])
        self.assertEqual(json.loads(self.out.read_text())["headers"], {})

    def test_request_missing_error_count_obeys_configured_streak(self):
        config = gw.load_config()
        config["gateway"]["error_streak"] = 1
        instant = 100.0
        with (
            patch.object(gw, "load_config", return_value=config),
            patch.object(gw.time, "time", return_value=instant),
            patch.object(gw.time, "sleep"),
        ):
            self.put_entry({"end": instant})
            self.assertEqual(
                self.observed_request(),
                (
                    0,
                    [
                        "[gw] api.github.com attempt 1 HTTP 200 0.20s",
                        "[gw] requests made: 1",
                    ],
                    ["[gw] pacing api.github.com: waiting 1.0s"],
                ),
            )

    def test_request_cooldown_without_saved_end_at_exact_boundary(self):
        config = gw.load_config()
        instant = float(config["gateway"]["error_cooldown_s"])
        self.put_entry({"errors": config["gateway"]["error_streak"]})
        with patch.object(gw.time, "time", return_value=instant):
            code, stdout, stderr = self.observed_request()
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            ["[gw] api.github.com attempt 1 HTTP 200 0.20s", "[gw] requests made: 1"],
        )
        self.assertEqual(stderr, [])

    def test_request_pacing_without_saved_duration_uses_floor(self):
        instant = 2_000_000_000.0
        self.put_entry({"end": instant})
        with (
            patch.object(gw.time, "time", return_value=instant),
            patch.object(gw.time, "sleep") as sleep,
        ):
            code, stdout, stderr = self.observed_request()
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            ["[gw] api.github.com attempt 1 HTTP 200 0.20s", "[gw] requests made: 1"],
        )
        self.assertEqual(stderr, ["[gw] pacing api.github.com: waiting 1.0s"])
        sleep.assert_called_once_with(1)

    def test_request_missing_window_usage_starts_with_request_cost(self):
        instant = 2_000_000_000.0
        self.rate_headers = False
        self.put_entry({"window_end": instant + 100})
        with patch.object(gw.time, "time", return_value=instant):
            self.assertEqual(self.observed_request()[0], 0)
        self.assertEqual(self.saved_entry()["window_used"], 1)

    def test_request_failure_without_saved_duration_keeps_last_duration(self):
        self.statuses = [400]
        self.write_outs = ["400 0.1 11"]
        self.assertEqual(self.observed_request()[0], 0)
        self.assertEqual(self.saved_entry()["dur"], 0.1)

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
            "local_used=37/1000 local_remaining=963 local_margin=100",
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
