"""Public behavior of secret-load against local Bitwarden and OpenBao doubles."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import resource
import runpy
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import vault_item

sys.modules["vault_item"] = vault_item
from tools import secret_load
from tests.fixtures.secret_load.fake_openbao import FakeOpenBao

DEST = "openbao:iac-durable/cloudflare-token#value"
VALUE = "dummy-iac-durable-cloudflare-222222222222222222222222"
LINES = [
    b"IaC plan token = dummy-iac-plan-cloudflare-111111111111111111111111111",
    b"iac-durable API = " + VALUE.encode(),
    b"iac-short-lived API = dummy-iac-short-lived-cf-3333333333333333333333333333",
]
SECRETS = [
    VALUE,
    "dummy-iac-plan-cloudflare-111111111111111111111111111",
    "dummy-iac-short-lived-cf-3333333333333333333333333333",
    "dummy-durable-colon-value-4444444444444444444444444==",
    "dummy-key-line-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "dummy-login-pw-5555",
    "dummy-old-login-pw-6666",
    "dummy-bao-token-7777",
    "dummy-session",
]


class SecretLoadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "bin").mkdir()
        (self.root / "bin/bw").symlink_to(ROOT / "tests/fixtures/bw/fake_bw.py")
        (self.root / "bw-session").write_text("dummy-session")
        self.marker = self.root / "container"
        self.marker.touch()
        self.calls_path = self.root / "calls.jsonl"
        self.environment = dict(os.environ)
        for name in (
            "BW_SESSION",
            "BW_NOINTERACTION",
            "XDG_RUNTIME_DIR",
            "http_proxy",
            "https_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "all_proxy",
            "ALL_PROXY",
        ):
            self.environment.pop(name, None)
        self.environment.update(
            PATH=f"{self.root}/bin:/usr/bin",
            XDG_RUNTIME_DIR=str(self.root),
            FAKE_BW_CALLS=str(self.calls_path),
            FAKE_BW_ITEMS=str(ROOT / "tests/fixtures/secret_load/items.json"),
        )
        self.bao = FakeOpenBao().start()
        self.addCleanup(self.bao.close)
        self.source = self.root / "cf.txt"
        self.source.write_bytes(b"\n".join(LINES) + b"\n")
        self.source.chmod(0o600)

    def calls(self):
        return (
            [json.loads(line) for line in self.calls_path.read_text().splitlines()]
            if self.calls_path.exists()
            else []
        )

    def run_tool(self, *args, cwd=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        out_file, err_file = self.root / "stdout", self.root / "stderr"
        saved = os.dup(1), os.dup(2)
        previous = Path.cwd()
        try:
            with out_file.open("w+") as out, err_file.open("w+") as err:
                os.dup2(out.fileno(), 1)
                os.dup2(err.fileno(), 2)
                os.chdir(cwd or self.root)
                with (
                    patch.dict(os.environ, self.environment, clear=True),
                    patch.object(vault_item, "CONTAINER_MARKER", self.marker),
                    patch.object(os, "getuid", return_value=4294967294),
                    patch.object(
                        secret_load,
                        "OPENBAO_ADDR",
                        getattr(self, "address_override", self.bao.address),
                    ),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    code = secret_load.main(list(args))
        finally:
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])
            os.chdir(previous)
        result = (
            code,
            stdout.getvalue() + out_file.read_text(),
            stderr.getvalue() + err_file.read_text(),
        )
        for secret in SECRETS:
            self.assertNotIn(secret, result[1] + result[2])
            self.assertNotIn(
                secret, json.dumps([call["args"] for call in self.calls()])
            )
        for method, path, token, body in self.bao.requests:
            self.assertTrue(all(secret not in path for secret in SECRETS))
            self.assertTrue(
                all(
                    secret not in (token or "")
                    for secret in SECRETS
                    if secret != "dummy-bao-token-7777"
                )
            )
            if token is not None:
                self.assertEqual(token, "dummy-bao-token-7777")
        return result

    def load(self, *args):
        return self.run_tool(
            "--from",
            "cf.txt",
            "--label",
            "iac-durable API",
            "--to",
            "openbao:iac-durable/cloudflare-token",
            *args,
        )

    def test_absent_and_exact_lookup(self):
        self.assertEqual(
            self.load(),
            (
                0,
                f"login: 200\n{DEST}: write 200, read back 200, matches True, length 53, version 1\nrevoke: 204\n",
                "",
            ),
        )
        self.assertEqual(
            self.bao.entries["iac-durable/cloudflare-token"],
            {"data": {"value": VALUE}, "version": 1, "deleted": False},
        )
        self.assertEqual(
            [r[:2] for r in self.bao.requests],
            [
                ("POST", "/v1/auth/userpass/login/keepbreath0"),
                ("GET", "/v1/secret/data/iac-durable/cloudflare-token"),
                ("POST", "/v1/secret/data/iac-durable/cloudflare-token"),
                ("GET", "/v1/secret/data/iac-durable/cloudflare-token"),
                ("POST", "/v1/auth/token/revoke-self"),
            ],
        )
        self.assertEqual(self.bao.requests[2][3]["options"], {"cas": 0})

    def test_http_requests_have_json_headers_and_no_body_on_reads(self):
        self.assertEqual(self.load()[0], 0)
        self.assertEqual(
            self.bao.raw_request_bodies,
            [
                json.dumps({"password": "dummy-login-pw-5555"}).encode(),
                b"",
                json.dumps({"options": {"cas": 0}, "data": {"value": VALUE}}).encode(),
                b"",
                b"",
            ],
        )
        self.assertEqual(
            [request[3] for request in self.bao.requests if request[0] == "GET"],
            [None, None],
        )
        self.assertIsNone(self.bao.requests[-1][3])
        self.assertTrue(
            all(
                headers.get("Content-Type") == "application/json"
                for headers in self.bao.request_headers
            )
        )
        self.assertEqual(
            self.calls()[0]["args"],
            ["list", "items", "--search", "openbao keepbreath0 (hub)"],
        )

    def test_label_variants(self):
        for content, label, expected in [
            (
                b"iac-durable API:\tdummy-durable-colon-value-4444444444444444444444444==\n",
                "iac-durable API",
                "dummy-durable-colon-value-4444444444444444444444444==",
            ),
            (
                b"IaC plan token old = dummy-iac-short-lived-cf-3333333333333333333333333333\nIaC plan token = dummy-iac-plan-cloudflare-111111111111111111111111111\n",
                "IaC plan token",
                "dummy-iac-plan-cloudflare-111111111111111111111111111",
            ),
            (
                b"\n# Cloudflare scoped tokens\n"
                + b"\n# Cloudflare scoped tokens\n".join(LINES)
                + b"\n",
                "iac-durable API",
                VALUE,
            ),
            (b"\r\n".join(LINES) + b"\r\n", "iac-durable API", VALUE),
        ]:
            with self.subTest(label=label, content=content):
                self.bao.entries.clear()
                self.bao.token_live = False
                self.source.write_bytes(content)
                code, out, err = self.run_tool(
                    "--from",
                    "cf.txt",
                    "--label",
                    label,
                    "--to",
                    "openbao:iac-durable/cloudflare-token",
                )
                self.assertEqual((code, err), (0, ""))
                self.assertIn(f"length {len(expected)}", out)
                self.assertEqual(
                    self.bao.entries["iac-durable/cloudflare-token"]["data"],
                    {"value": expected},
                )

    def test_invalid_sources_stop_before_network(self):
        for content, label, error in [
            (
                b"\n".join(LINES) + b"\n",
                "iac-sweep API",
                'no line labelled "iac-sweep API" in cf.txt',
            ),
            (
                LINES[0] + b"\n" + LINES[1] + b"\n" + LINES[0] + b"\n",
                "IaC plan token",
                '"IaC plan token" is on lines 1 and 3 of cf.txt',
            ),
            (
                LINES[0]
                + b"\niac-durable API = d\nummy-iac-durable-cloudflare-222222222222222222222222\n",
                "iac-durable API",
                'line 3 of cf.txt is not "label = value" or "label: value" (length 52)',
            ),
            (
                LINES[0] + b"\niac-durable API = dummy durable\n",
                "iac-durable API",
                'line 2 of cf.txt is not "label = value" or "label: value" (length 31)',
            ),
        ]:
            with self.subTest(error=error):
                self.source.write_bytes(content)
                self.assertEqual(
                    self.run_tool(
                        "--from", "cf.txt", "--label", label, "--to", "openbao:a/b"
                    ),
                    (2, "", f"secret-load: {error}\n"),
                )
                self.assertEqual(self.calls(), [])
                self.assertEqual(self.bao.requests, [])
        self.assertEqual(
            self.run_tool("--from", "missing.txt", "--to", "openbao:a/b"),
            (
                2,
                "",
                "secret-load: cannot read missing.txt: No such file or directory\n",
            ),
        )

    def test_parser_boundaries(self):
        cases = [
            (b"other =\n", "iac-durable API", 1, 7),
            (b"= dummy\n", "iac-durable API", 1, 7),
            (b"=dummy:x\n", "iac-durable API", 1, 8),
        ]
        for content, label, number, length in cases:
            with self.subTest(content=content):
                self.source.write_bytes(content)
                self.assertEqual(
                    self.run_tool(
                        "--from", "cf.txt", "--label", label, "--to", "openbao:a/b"
                    ),
                    (
                        2,
                        "",
                        f'secret-load: line {number} of cf.txt is not "label = value" or "label: value" (length {length})\n',
                    ),
                )
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.bao.requests, [])

    def test_first_separator_and_indented_comment(self):
        for line, expected in (
            (
                b"iac-durable API = dummy-durable-colon-value-4444444444444444444444444==",
                "dummy-durable-colon-value-4444444444444444444444444==",
            ),
            (b"iac-durable API: dummy:x", "dummy:x"),
            (b"iac-durable API=dummy", "dummy"),
        ):
            with self.subTest(line=line):
                self.source.write_bytes(b"  # note\n" + line + b"\n")
                self.bao.entries.clear()
                code, out, err = self.load()
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(
                    self.bao.entries["iac-durable/cloudflare-token"]["data"],
                    {"value": expected},
                )
                self.assertIn(f"length {len(expected)}", out)

    def test_crlf_whole_file_and_split_token_length(self):
        self.source.write_bytes(b"abc\r\n")
        code, out, err = self.run_tool("--from", "cf.txt", "--to", "openbao:a/b")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.bao.entries["a/b"]["data"], {"value": "abc"})
        self.assertIn("length 3", out)
        self.source.write_bytes(
            LINES[0]
            + b"\r\niac-durable API = d\r\nummy-iac-durable-cloudflare-222222222222222222222222\r\n"
        )
        self.assertEqual(
            self.load(),
            (
                2,
                "",
                'secret-load: line 3 of cf.txt is not "label = value" or "label: value" (length 52)\n',
            ),
        )

    def test_whole_file_and_empty(self):
        key = "-----BEGIN FAKE KEY-----\ndummy-key-line-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n-----END FAKE KEY-----"
        (self.root / "key.pem").write_text(key + "\n")
        code, out, err = self.run_tool(
            "--from", "key.pem", "--to", "openbao:grafana/tailscale-client-id"
        )
        self.assertEqual((code, err), (0, ""))
        self.assertIn("length 95", out)
        self.assertEqual(
            self.bao.entries["grafana/tailscale-client-id"]["data"], {"value": key}
        )
        for content in (b"", b"\n"):
            (self.root / "empty.txt").write_bytes(content)
            self.assertEqual(
                self.run_tool("--from", "empty.txt", "--to", "openbao:a/b"),
                (2, "", "secret-load: empty.txt is empty\n"),
            )

    def test_destinations_and_help(self):
        for destination, error in [
            (
                "vaultwarden:openbao keepbreath0 (hub)#login.password",
                "vaultwarden: destinations are not built yet",
            ),
            *[
                (x, "--to must be openbao:PATH[#KEY]")
                for x in (
                    "openbao:",
                    "openbao:/x",
                    "openbao:a//b",
                    "openbao:a/../b",
                    "openbao:a/./b",
                    "openbao:a#",
                    "openbao:a#b#c",
                    "openbao:a#b/c",
                    "openbao:a?b",
                    "openbao:a\\b",
                    "secret/x",
                )
            ],
        ]:
            with self.subTest(destination=destination):
                self.assertEqual(
                    self.run_tool("--from", "cf.txt", "--to", destination),
                    (2, "", f"secret-load: {error}\n"),
                )
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.bao.requests, [])
        link = self.root / "secret-load"
        link.symlink_to(ROOT / "tools/secret_load.py")
        result = subprocess.run(
            [sys.executable, str(link), "--help"],
            env=self.environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        help_text = " ".join(result.stdout.split())
        self.assertIn(
            "Replace a different existing value. OpenBao keeps the old version; Vaultwarden keeps no history for a custom field, so its old value is lost.",
            help_text,
        )
        self.assertIn(
            "After a verified match, remove the label's line, or the whole file. Removal does not scrub the old data from a btrfs disk.",
            help_text,
        )
        code, out, err = self.run_tool("--help")
        self.assertEqual((code, err), (0, ""))
        help_text = " ".join(out.split())
        self.assertEqual(
            help_text,
            "usage: secret-load [-h] --from FILE [--label LABEL] --to openbao:PATH[#KEY] "
            "[--dry-run] [--replace] [--remove-source] options: -h, --help show this help "
            "message and exit --from FILE --label LABEL --to openbao:PATH[#KEY] --dry-run "
            "--replace Replace a different existing value. OpenBao keeps the old version; "
            "Vaultwarden keeps no history for a custom field, so its old value is lost. "
            "--remove-source After a verified match, remove the label's line, or the whole "
            "file. Removal does not scrub the old data from a btrfs disk.",
        )

    def test_lone_carriage_return_numbers_and_removes_one_label(self):
        original = LINES[0] + b"\r" + LINES[1] + b"\n" + LINES[2] + b"\n"
        self.source.write_bytes(original)
        self.assertEqual(
            self.load("--remove-source"),
            (
                0,
                f"login: 200\n{DEST}: write 200, read back 200, matches True, length 53, version 1\n"
                "revoke: 204\nremoved line 2 of cf.txt\n",
                "",
            ),
        )
        self.assertEqual(self.source.read_bytes(), LINES[0] + b"\r" + LINES[2] + b"\n")

    def test_write_merges_and_cas(self):
        self.bao.seed(
            "iac-durable/cloudflare-token",
            {"client_id": "dummy-client-id", "note": "dummy-note"},
            3,
        )
        code, out, err = self.load()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out,
            f"login: 200\n{DEST}: write 200, read back 200, matches True, length 53, version 4\nrevoke: 204\n",
        )
        self.assertEqual(
            self.bao.requests[2][3],
            {
                "options": {"cas": 3},
                "data": {
                    "client_id": "dummy-client-id",
                    "note": "dummy-note",
                    "value": VALUE,
                },
            },
        )
        self.assertEqual(
            self.bao.entries["iac-durable/cloudflare-token"]["data"],
            {"client_id": "dummy-client-id", "note": "dummy-note", "value": VALUE},
        )

    def test_same_refusal_replace_and_deleted(self):
        self.bao.seed("iac-durable/cloudflare-token", {"value": VALUE}, 2)
        self.assertEqual(
            self.load(),
            (
                0,
                f"login: 200\n{DEST}: already holds this value, length 53\nrevoke: 204\n",
                "",
            ),
        )
        self.assertEqual([r[0] for r in self.bao.requests].count("POST"), 2)
        writes_before_refusal = sum(
            r[:2] == ("POST", "/v1/secret/data/iac-durable/cloudflare-token")
            for r in self.bao.requests
        )
        self.bao.seed("iac-durable/cloudflare-token", {"value": "different"}, 2)
        self.assertEqual(
            self.load(),
            (
                1,
                "login: 200\nrevoke: 204\n",
                f"secret-load: {DEST} holds a different value; use --replace to rotate it\n",
            ),
        )
        self.assertEqual(
            sum(
                r[:2] == ("POST", "/v1/secret/data/iac-durable/cloudflare-token")
                for r in self.bao.requests
            ),
            writes_before_refusal,
        )
        code, out, err = self.load("--replace")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out,
            f"login: 200\n{DEST}: write 200, read back 200, matches True, length 53, version 3\nrevoke: 204\n",
        )
        self.assertEqual(self.bao.requests[-3][3]["options"], {"cas": 2})
        self.bao.seed("iac-durable/cloudflare-token", {"old": "old"}, 3, deleted=True)
        code, out, err = self.load()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out,
            f"login: 200\n{DEST}: write 200, read back 200, matches True, length 53, version 4\nrevoke: 204\n",
        )
        self.assertEqual(
            self.bao.entries["iac-durable/cloudflare-token"]["data"], {"value": VALUE}
        )
        self.assertEqual(self.bao.requests[-3][3]["options"], {"cas": 3})

    def test_write_failures_and_revoke(self):
        for fault, expected, error in [
            (
                "raise_version",
                None,
                f"secret-load: {DEST} changed while loading; nothing written\n",
            ),
            ("write_error", f"{DEST}: write 500\n", ""),
            (
                "readback_mismatch",
                f"{DEST}: write 200, read back 200, matches False, length 53, version 1\n",
                "",
            ),
        ]:
            with self.subTest(fault=fault):
                self.bao.entries.clear()
                self.bao.written = False
                setattr(self.bao, fault, True)
                code, out, err = self.load()
                self.assertEqual(
                    (code, out, err),
                    (1, "login: 200\n" + (expected or "") + "revoke: 204\n", error),
                )
                setattr(self.bao, fault, False)
        self.bao.revoke_error = True
        self.assertEqual(self.load()[0:1], (1,))
        self.assertTrue(
            self.bao.requests[-1][:2] == ("POST", "/v1/auth/token/revoke-self")
        )

    def test_login_failures(self):
        items = self.root / "items.json"
        items.write_text(
            json.dumps(
                [
                    {
                        "name": "openbao keepbreath0 (hub)",
                        "login": {"password": "dummy-wrong-pw-8888"},
                    }
                ]
            )
        )
        self.environment["FAKE_BW_ITEMS"] = str(items)
        self.assertEqual(
            self.load(), (1, "login: 400\n", "secret-load: OpenBao sign-in failed\n")
        )
        self.assertEqual(len(self.bao.requests), 1)
        items.write_text(
            json.dumps(
                [
                    {
                        "name": "openbao keepbreath0 (hub) old",
                        "login": {"password": "dummy-old-login-pw-6666"},
                    }
                ]
            )
        )
        self.assertEqual(
            self.load(),
            (
                1,
                "",
                'secret-load: no vault item is named exactly "openbao keepbreath0 (hub)"\n',
            ),
        )
        self.assertEqual(len(self.bao.requests), 1)

    def test_malformed_login_replies(self):
        for reply in (None, [], {"auth": {}}):
            with self.subTest(reply=reply):
                self.bao.login_fault = reply if reply is not None else "no-body"
                self.assertEqual(
                    self.load(),
                    (1, "login: 200\n", "secret-load: OpenBao sign-in failed\n"),
                )
                self.assertFalse(
                    any(
                        path == "/v1/auth/token/revoke-self"
                        for _, path, _, _ in self.bao.requests
                    )
                )
        self.bao.login_fault = None

    def test_malformed_read_and_write_replies(self):
        self.bao.read_fault = "malformed-one-field"
        self.assertEqual(
            self.load(),
            (
                1,
                "login: 200\nrevoke: 204\n",
                "secret-load: OpenBao returned an unreadable entry\n",
            ),
        )
        for status, body in (
            (400, {"errors": ["invalid request"]}),
            (400, {}),
            (500, None),
        ):
            with self.subTest(status=status, body=body):
                self.bao.write_fault = (status, body)
                self.assertEqual(
                    self.load(),
                    (1, f"login: 200\n{DEST}: write {status}\nrevoke: 204\n", ""),
                )
        self.bao.write_fault = None

    def test_read_body_timeout_is_network_error(self):
        self.bao.read_fault = "body-timeout"
        code, out, err = self.load()
        self.assertEqual((code, out), (1, "login: 200\nrevoke: 204\n"))
        self.assertTrue(err.startswith("secret-load: cannot reach OpenBao: "))

    def test_dry_run(self):
        self.assertEqual(
            self.load("--dry-run"),
            (
                0,
                f"login: 200\ndry run: {DEST}: would write a new key, length 53\nrevoke: 204\n",
                "",
            ),
        )
        self.bao.seed("iac-durable/cloudflare-token", {"value": VALUE})
        self.assertEqual(
            self.load("--dry-run"),
            (
                0,
                f"login: 200\ndry run: {DEST}: already holds this value, length 53\nrevoke: 204\n",
                "",
            ),
        )
        self.bao.seed("iac-durable/cloudflare-token", {"value": "other"})
        self.assertEqual(
            self.load("--dry-run"),
            (
                1,
                "login: 200\nrevoke: 204\n",
                f"secret-load: {DEST} holds a different value; use --replace to rotate it\n",
            ),
        )
        self.assertEqual(
            self.load("--dry-run", "--replace"),
            (
                0,
                f"login: 200\ndry run: {DEST}: would replace a different value, length 53\nrevoke: 204\n",
                "",
            ),
        )
        self.assertEqual(
            len(
                [
                    r
                    for r in self.bao.requests
                    if r[:2] == ("POST", "/v1/secret/data/iac-durable/cloudflare-token")
                ]
            ),
            0,
        )

    def test_removal_preserves_other_lines_and_mode(self):
        original = b"# Cloudflare scoped tokens\n" + self.source.read_bytes()
        self.source.write_bytes(original)
        self.assertEqual(
            self.load("--remove-source"),
            (
                0,
                f"login: 200\n{DEST}: write 200, read back 200, matches True, length 53, version 1\nrevoke: 204\nremoved line 3 of cf.txt\n",
                "",
            ),
        )
        self.assertEqual(
            self.source.read_bytes(),
            b"# Cloudflare scoped tokens\n" + LINES[0] + b"\n" + LINES[2] + b"\n",
        )
        self.assertEqual(self.source.stat().st_mode & 0o777, 0o600)

    def test_form_feed_comment_removes_loaded_line(self):
        original = b"# a\x0c# b\n" + b"\n".join(LINES) + b"\n"
        self.source.write_bytes(original)
        self.assertEqual(
            self.load("--remove-source"),
            (
                0,
                f"login: 200\n{DEST}: write 200, read back 200, matches True, length 53, version 1\nrevoke: 204\nremoved line 3 of cf.txt\n",
                "",
            ),
        )
        self.assertEqual(
            self.source.read_bytes(),
            b"# a\x0c# b\n" + LINES[0] + b"\n" + LINES[2] + b"\n",
        )

    def test_removal_line_endings_and_delete(self):
        for content, label, expected in [
            (
                b"\r\n".join(LINES) + b"\r\n",
                "iac-durable API",
                LINES[0] + b"\r\n" + LINES[2] + b"\r\n",
            ),
            (b"\n".join(LINES), "IaC plan token", LINES[1] + b"\n" + LINES[2]),
        ]:
            self.source.write_bytes(content)
            self.bao.entries.clear()
            code, out, err = self.run_tool(
                "--from",
                "cf.txt",
                "--label",
                label,
                "--to",
                "openbao:iac-durable/cloudflare-token",
                "--remove-source",
            )
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(self.source.read_bytes(), expected)
        self.source.write_bytes(
            b"# comment\n\niac-durable API = " + VALUE.encode() + b"\n"
        )
        self.bao.seed("iac-durable/cloudflare-token", {"value": VALUE})
        self.assertEqual(
            self.load("--remove-source")[1].splitlines()[-1], "deleted cf.txt"
        )
        self.assertFalse(self.source.exists())
        self.source.write_bytes(
            b"  # comment\niac-durable API = " + VALUE.encode() + b"\n"
        )
        self.assertEqual(
            self.load("--remove-source")[1].splitlines()[-1], "deleted cf.txt"
        )
        self.assertFalse(self.source.exists())

    def test_whole_file_remove_and_dry_remove(self):
        key = self.root / "key.pem"
        key.write_text("dummy-key-line-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n")
        code, out, err = self.run_tool(
            "--from",
            "key.pem",
            "--to",
            "openbao:keys/test",
            "--dry-run",
            "--remove-source",
        )
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.endswith("dry run: would delete key.pem\n"))
        self.assertTrue(key.exists())
        code, out, err = self.run_tool(
            "--from", "key.pem", "--to", "openbao:keys/test", "--remove-source"
        )
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.endswith("deleted key.pem\n"))
        self.assertFalse(key.exists())

    def test_removal_only_after_success(self):
        for state in ("different", "write_error", "readback_mismatch", "revoke_error"):
            self.bao.entries.clear()
            self.bao.written = False
            self.source.write_bytes(b"\n".join(LINES) + b"\n")
            original = self.source.read_bytes()
            if state == "different":
                self.bao.seed("iac-durable/cloudflare-token", {"value": "other"})
            else:
                setattr(self.bao, state, True)
            self.assertEqual(self.load("--remove-source")[0], 1)
            self.assertEqual(self.source.read_bytes(), original)
            if state != "different":
                setattr(self.bao, state, False)

    def test_absolute_source_and_session_options(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        code, out, err = self.run_tool(
            "--from",
            str(self.source),
            "--label",
            "iac-durable API",
            "--to",
            "openbao:iac-durable/cloudflare-token",
            cwd=elsewhere,
        )
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out,
            f"login: 200\n{DEST}: write 200, read back 200, matches True, length 53, version 1\nrevoke: 204\n",
        )
        self.assertEqual(self.calls()[0]["session"], "dummy-session")
        self.bao.entries.clear()
        self.assertEqual(
            self.run_tool(
                "--from",
                str(self.source),
                "--label",
                "iac-durable API",
                "--to",
                "openbao:iac-durable/cloudflare-token",
                "--remove-source",
                cwd=elsewhere,
            )[1].splitlines()[-1],
            f"removed line 2 of {self.source}",
        )
        self.source.write_bytes(b"\n".join(LINES) + b"\n")
        (self.root / "bw-session").unlink()
        self.environment["BW_SESSION"] = "dummy-session"
        self.bao.entries.clear()
        self.assertEqual(self.load()[0], 0)
        self.assertEqual(self.calls()[-1]["session"], "dummy-session")

    def test_custom_key_and_dry_remove_line(self):
        code, out, err = self.run_tool(
            "--from",
            "cf.txt",
            "--label",
            "iac-durable API",
            "--to",
            "openbao:iac-plan/cloudflare-token#client_id",
        )
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(
            out.startswith(
                "login: 200\nopenbao:iac-plan/cloudflare-token#client_id: write 200"
            )
        )
        self.assertEqual(
            self.bao.entries["iac-plan/cloudflare-token"]["data"], {"client_id": VALUE}
        )
        self.bao.seed("iac-durable/cloudflare-token", {"value": VALUE})
        original = self.source.read_bytes()
        self.assertEqual(
            self.load("--dry-run", "--remove-source"),
            (
                0,
                f"login: 200\ndry run: {DEST}: already holds this value, length 53\nrevoke: 204\ndry run: would remove line 2 of cf.txt\n",
                "",
            ),
        )
        self.assertEqual(self.source.read_bytes(), original)

    def test_conflict_and_revoke_failures_are_exact(self):
        self.bao.raise_version = True
        self.assertEqual(
            self.load(),
            (
                1,
                "login: 200\nrevoke: 204\n",
                f"secret-load: {DEST} changed while loading; nothing written\n",
            ),
        )
        self.bao.entries.clear()
        self.bao.revoke_error = True
        code, out, err = self.load()
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(
            out,
            f"login: 200\n{DEST}: write 200, read back 200, matches True, length 53, version 1\nrevoke: 500\n",
        )

    def test_unreachable_and_missing_arguments(self):
        self.address_override = "http://127.0.0.1:1"
        code, out, err = self.load()
        del self.address_override
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("secret-load: cannot reach OpenBao: "))
        self.assertEqual(self.bao.requests, [])
        for args in (("--from", "cf.txt"), ("--to", "openbao:a/b")):
            code, out, err = self.run_tool(*args)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("usage: secret-load", err)

    def test_unreadable_source_and_missing_password(self):
        (self.root / "bad.txt").write_bytes(b"\xff")
        self.assertEqual(
            self.run_tool("--from", "bad.txt", "--to", "openbao:a/b"),
            (2, "", "secret-load: cannot read bad.txt: source is not UTF-8 text\n"),
        )
        items = self.root / "no-password.json"
        items.write_text(
            json.dumps([{"name": "openbao keepbreath0 (hub)", "login": {}}])
        )
        self.environment["FAKE_BW_ITEMS"] = str(items)
        self.assertEqual(
            self.load(),
            (1, "", 'secret-load: "openbao keepbreath0 (hub)" has no password\n'),
        )
        self.assertEqual(self.bao.requests, [])

    def test_bad_openbao_replies_revoke_token(self):
        for fault, message in (
            ("invalid-json", "OpenBao returned unreadable JSON"),
            ("malformed-present", "OpenBao returned an unreadable entry"),
            ("malformed-deleted", "OpenBao could not read the entry"),
            ("status-500", "OpenBao read failed with status 500"),
        ):
            with self.subTest(fault=fault):
                self.bao.read_fault = fault
                code, out, err = self.load()
                self.assertEqual(
                    (code, out, err),
                    (1, "login: 200\nrevoke: 204\n", f"secret-load: {message}\n"),
                )

    def test_revoke_disconnect_blocks_removal(self):
        original = self.source.read_bytes()
        self.bao.revoke_disconnect = True
        code, out, err = self.load("--remove-source")
        self.assertEqual(code, 1)
        self.assertIn("write 200, read back 200, matches True", out)
        self.assertTrue(err.startswith("secret-load: cannot reach OpenBao: "))
        self.assertEqual(self.source.read_bytes(), original)

    def test_changed_source_blocks_removal(self):
        original = self.source.read_bytes()
        self.bao.on_revoke = lambda: self.source.write_bytes(original + b"# changed\n")
        code, out, err = self.load("--remove-source")
        self.assertEqual(code, 1)
        self.assertTrue(out.endswith("revoke: 204\n"))
        self.assertEqual(
            err, "secret-load: cannot remove cf.txt: source changed while loading\n"
        )
        self.assertEqual(self.source.read_bytes(), original + b"# changed\n")

    def test_failed_source_replace_preserves_original(self):
        locked = self.root / "locked"
        locked.mkdir()
        source = locked / "cf.txt"
        source.write_bytes(self.source.read_bytes())
        original = source.read_bytes()
        locked.chmod(0o500)
        try:
            code, out, err = self.run_tool(
                "--from",
                "locked/cf.txt",
                "--label",
                "iac-durable API",
                "--to",
                "openbao:iac-durable/cloudflare-token",
                "--remove-source",
            )
        finally:
            locked.chmod(0o700)
        self.assertEqual(code, 1)
        self.assertTrue(out.endswith("revoke: 204\n"))
        self.assertEqual(
            err, "secret-load: cannot remove locked/cf.txt: Permission denied\n"
        )
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(list(locked.glob(".cf.txt.*")), [])

    def test_disk_full_cleans_up_temporary_source(self):
        original = self.source.read_bytes()
        old_limit = resource.getrlimit(resource.RLIMIT_FSIZE)
        old_signal = signal.signal(signal.SIGXFSZ, signal.SIG_IGN)

        def fill_disk():
            resource.setrlimit(resource.RLIMIT_FSIZE, (64, old_limit[1]))

        self.bao.on_revoke = fill_disk
        try:
            code, out, err = self.load("--remove-source")
        finally:
            resource.setrlimit(resource.RLIMIT_FSIZE, old_limit)
            signal.signal(signal.SIGXFSZ, old_signal)
        self.assertEqual(code, 1)
        self.assertTrue(out.endswith("revoke: 204\n"))
        self.assertEqual(err, "secret-load: cannot remove cf.txt: File too large\n")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(list(self.root.glob(".cf.txt.*")), [])

    def test_module_entry_point_prints_help(self):
        stdout = io.StringIO()
        with (
            patch.object(sys, "argv", ["secret-load", "--help"]),
            redirect_stdout(stdout),
        ):
            with self.assertRaises(SystemExit) as outcome:
                runpy.run_path(str(ROOT / "tools/secret_load.py"), run_name="__main__")
        self.assertEqual(outcome.exception.code, 0)
        self.assertIn("usage: secret-load", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
