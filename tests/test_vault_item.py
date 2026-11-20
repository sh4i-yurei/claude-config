"""Exact-name vault lookup through a Bitwarden stand-in."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import vault_item

TOKEN = "API tokens (keepbreath.ing)"
HUB = "keepbreath0 sudo (hub)"
FIXTURE = ROOT / "tests/fixtures/bw/items.json"
FAKE = ROOT / "tests/fixtures/bw/fake_bw.py"
VALUES = (
    "dummy-cf",
    "dummy-gh",
    "dummy-do",
    "dummy-brevo",
    "dummy-pass",
    "dummy-hash",
    "dummy-session",
    "dummy-retired-gh",
    "dummy-lower-gh",
    "dummy-old-gh",
    "dummy-dns",
    "dummy-control",
    "dummy-old-pass",
    "dummy-second-pass",
    "dummy-file-session",
    "dummy-unnamed",
)


class VaultItemTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "bw").symlink_to(FAKE)
        self.calls_file = self.root / "calls.jsonl"
        self.items_file = FIXTURE
        self.marker = self.root / "container"
        self.marker.touch()
        self.session = self.root / "bw-session"
        self.session.write_text("dummy-file-session")
        self.environment = dict(os.environ)
        for name in (
            "BW_SESSION",
            "BW_NOINTERACTION",
            "CLOUDFLARE_API_TOKEN",
            "GH_TOKEN",
            "DIGITALOCEAN_API_TOKEN",
            "Brevo_smtp_key",
            "XDG_RUNTIME_DIR",
        ):
            self.environment.pop(name, None)
        self.environment.update(
            PATH=f"{bin_dir}:/usr/bin",
            XDG_RUNTIME_DIR=str(self.root),
            FAKE_BW_CALLS=str(self.calls_file),
            FAKE_BW_ITEMS=str(self.items_file),
        )

    def run_read(self, name):
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, self.environment, clear=True),
            patch.object(os, "getuid", return_value=4294967294),
            patch.object(vault_item, "CONTAINER_MARKER", self.marker),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            try:
                item, error = vault_item.read_item(name), None
            except vault_item.VaultItemError as exc:
                item, error = None, str(exc)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "")
        self.assertTrue(
            all(value not in out.getvalue() + err.getvalue() for value in VALUES)
        )
        return item, error

    def calls(self):
        return (
            [json.loads(line) for line in self.calls_file.read_text().splitlines()]
            if self.calls_file.exists()
            else []
        )

    def copy_items(self, change):
        items = json.loads(FIXTURE.read_text())
        change(items)
        self.items_file = self.root / "items.json"
        self.items_file.write_text(json.dumps(items))
        self.environment["FAKE_BW_ITEMS"] = str(self.items_file)

    def test_exact_token_item(self):
        self.environment["BW_SESSION"] = "dummy-session"
        self.assertEqual(
            self.run_read(TOKEN), (json.loads(FIXTURE.read_text())[1], None)
        )
        self.assertEqual(
            self.calls(),
            [
                {
                    "args": ["list", "items", "--search", TOKEN],
                    "session": "dummy-session",
                    "nointeraction": "true",
                }
            ],
        )

    def test_session_file_unset_and_empty(self):
        for session in (None, ""):
            with self.subTest(session=session):
                self.calls_file.unlink(missing_ok=True)
                if session is None:
                    self.environment.pop("BW_SESSION", None)
                else:
                    self.environment["BW_SESSION"] = session
                self.assertEqual(
                    self.run_read(HUB), (json.loads(FIXTURE.read_text())[7], None)
                )
                self.assertEqual(self.calls()[0]["session"], "dummy-file-session")

    def test_missing_session_file(self):
        self.session.unlink()
        self.assertEqual(
            self.run_read(TOKEN),
            (None, f'nothing from the vault for "{TOKEN}". Is it unlocked? Run vu.'),
        )
        self.assertEqual(self.calls()[0]["session"], None)

    def test_default_session_file_is_not_real_session(self):
        self.session.unlink()
        self.environment.pop("XDG_RUNTIME_DIR")
        self.assertEqual(
            self.run_read(TOKEN),
            (None, f'nothing from the vault for "{TOKEN}". Is it unlocked? Run vu.'),
        )
        self.assertEqual(self.calls()[0]["session"], None)

    def test_no_exact_item(self):
        for name in ("keepbreath0 sudo", "keepbreath0 sudo (web)"):
            with self.subTest(name=name):
                self.calls_file.unlink(missing_ok=True)
                self.assertEqual(
                    self.run_read(name),
                    (None, f'no vault item is named exactly "{name}"'),
                )
                self.assertEqual(len(self.calls()), 1)

    def test_duplicate_exact_item(self):
        def duplicate(items):
            second = json.loads(json.dumps(items[7]))
            second["login"]["password"] = "dummy-second-pass"
            items.insert(8, second)

        self.copy_items(duplicate)
        self.assertEqual(
            self.run_read(HUB), (None, f'2 vault items are named exactly "{HUB}"')
        )

    def test_unreadable_bw_results(self):
        for mode in ("failed-json", "not-json", "object"):
            with self.subTest(mode=mode):
                self.environment["FAKE_BW_MODE"] = mode
                self.assertEqual(
                    self.run_read(TOKEN),
                    (
                        None,
                        f'nothing from the vault for "{TOKEN}". Is it unlocked? Run vu.',
                    ),
                )
        self.environment.pop("FAKE_BW_MODE")
        empty = self.root / "empty"
        empty.mkdir()
        self.environment["PATH"] = str(empty)
        self.assertEqual(
            self.run_read(TOKEN),
            (None, f'nothing from the vault for "{TOKEN}". Is it unlocked? Run vu.'),
        )

    def test_bw_stderr_never_reaches_fd_2(self):
        self.environment["FAKE_BW_MODE"] = "stderr-secret"
        captured = self.root / "stderr"
        saved = os.dup(2)
        try:
            with captured.open("w") as target:
                os.dup2(target.fileno(), 2)
                self.assertEqual(
                    self.run_read(TOKEN), (json.loads(FIXTURE.read_text())[1], None)
                )
        finally:
            os.dup2(saved, 2)
            os.close(saved)
        self.assertEqual(captured.read_text(), "")

    def test_junk_entries_are_skipped(self):
        self.environment["FAKE_BW_MODE"] = "junk"
        self.assertEqual(
            self.run_read(TOKEN), (json.loads(FIXTURE.read_text())[1], None)
        )

    def test_container_required_before_bw(self):
        self.marker.unlink()
        self.assertEqual(
            self.run_read(TOKEN),
            (None, "bw runs only inside the dev container (distrobox enter dev)"),
        )
        self.assertFalse(self.calls_file.exists())
