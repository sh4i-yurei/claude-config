"""Public behavior of the vault-env program."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from unittest.mock import patch
import unittest

import test_vault_item as fixture

ROOT, TOKEN, FIXTURE, VALUES = fixture.ROOT, fixture.TOKEN, fixture.FIXTURE, fixture.VALUES
from tools import vault_item

sys.modules["vault_item"] = vault_item
from tools import vault_env


class VaultEnvTests(unittest.TestCase):
    setUp = fixture.VaultItemTests.setUp
    calls = fixture.VaultItemTests.calls
    copy_items = fixture.VaultItemTests.copy_items

    def run_env(self, args=()):
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, self.environment, clear=True),
            patch.object(os, "getuid", return_value=4294967294),
            patch.object(vault_item, "CONTAINER_MARKER", self.marker),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = vault_env.main(list(args))
        result = (code, out.getvalue(), err.getvalue())
        self.assertTrue(all(value not in result[2] for value in VALUES), result)
        self.assertTrue(
            all(value not in result[1] for value in VALUES)
            or result[1].startswith("export "),
            result,
        )
        return result

    def test_exports_exact_item_in_field_order(self):
        self.environment["BW_SESSION"] = "dummy-session"
        self.assertEqual(
            self.run_env(),
            (
                0,
                "export CLOUDFLARE_API_TOKEN=dummy-cf\nexport GH_TOKEN=dummy-gh\nexport DIGITALOCEAN_API_TOKEN=dummy-do\nexport Brevo_smtp_key=dummy-brevo\n",
                "",
            ),
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

    def test_quoting_and_skipped_fields(self):
        def change(items):
            items[1]["fields"][1]["value"] = 'it\'s a "token" $HOME'
            items[1]["fields"].extend(
                [
                    {"name": "NULL_VALUE_SKIPPED", "value": None, "type": 1},
                    {"name": "", "value": "dummy-unnamed", "type": 1},
                ]
            )

        self.copy_items(change)
        code, out, err = self.run_env()
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("NULL_VALUE_SKIPPED", out)
        self.assertNotIn("dummy-unnamed", out)
        output = self.root / "out"
        output.write_text(out)
        result = subprocess.run(
            ["bash", "-c", 'eval "$(cat out)"; printf %s "$GH_TOKEN"'],
            cwd=self.root,
            env={"PATH": "/usr/bin:/bin", "HOME": str(self.root)},
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, 'it\'s a "token" $HOME', ""),
        )

    def test_missing_or_null_fields(self):
        for mode in ("no-fields", "null-fields"):
            with self.subTest(mode=mode):
                self.environment["FAKE_BW_MODE"] = mode
                self.assertEqual(self.run_env(), (0, "", ""))

    def test_arguments_refused_before_read(self):
        for args in (("GH_TOKEN",), ("--help",), ("-h",)):
            with self.subTest(args=args):
                self.assertEqual(
                    self.run_env(args), (2, "", 'usage: eval "$(vault-env)"\n')
                )
                self.assertFalse(self.calls_file.exists())

    def test_terminal_refused_before_read(self):
        master, follower = os.openpty()
        try:
            with (
                os.fdopen(follower, "w") as terminal,
                patch.object(sys, "stdout", terminal),
                patch.dict(os.environ, self.environment, clear=True),
                patch.object(os, "getuid", return_value=4294967294),
                patch.object(vault_item, "CONTAINER_MARKER", self.marker),
                redirect_stderr(io.StringIO()) as err,
            ):
                code = vault_env.main([])
            os.set_blocking(master, False)
            try:
                written = os.read(master, 4096)
            except OSError:
                written = b""
            self.assertEqual(
                (code, written, err.getvalue()),
                (2, b"", 'usage: eval "$(vault-env)"\n'),
            )
            self.assertFalse(self.calls_file.exists())
        finally:
            os.close(master)

    def test_container_and_missing_session(self):
        self.marker.unlink()
        self.assertEqual(
            self.run_env(),
            (
                1,
                "",
                "vault-env: bw runs only inside the dev container (distrobox enter dev)\n",
            ),
        )
        self.assertFalse(self.calls_file.exists())
        self.marker.touch()
        self.session.unlink()
        self.assertEqual(
            self.run_env(),
            (
                1,
                "",
                f'vault-env: nothing from the vault for "{TOKEN}". Is it unlocked? Run vu.\n',
            ),
        )

    def test_no_exact_item(self):
        self.copy_items(lambda items: items[1].update(name=TOKEN + " new"))
        self.assertEqual(
            self.run_env(),
            (1, "", f'vault-env: no vault item is named exactly "{TOKEN}"\n'),
        )

    def test_link_and_main_line(self):
        link = self.root / "vault-env"
        source_root = ROOT.parent if ROOT.name == "mutants" else ROOT
        link.symlink_to(source_root / "tools/vault_env.py")
        home = self.root / "home"
        home.mkdir()
        env = {"PATH": self.environment["PATH"] + ":/bin", "HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(link), "--help"],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (2, "", 'usage: eval "$(vault-env)"\n'),
        )
        with (
            patch.object(sys, "argv", [str(ROOT / "tools/vault_env.py"), "--help"]),
            self.assertRaises(SystemExit) as raised,
        ):
            runpy.run_path(str(ROOT / "tools/vault_env.py"), run_name="__main__")
        self.assertEqual(raised.exception.code, 2)
