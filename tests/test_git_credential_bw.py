"""Public behavior of the Git credential helper."""

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
from tools import git_credential_bw


class CredentialTests(unittest.TestCase):
    setUp = fixture.VaultItemTests.setUp
    calls = fixture.VaultItemTests.calls
    copy_items = fixture.VaultItemTests.copy_items

    def run_helper(self, args):
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, self.environment, clear=True),
            patch.object(os, "getuid", return_value=4294967294),
            patch.object(vault_item, "CONTAINER_MARKER", self.marker),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = git_credential_bw.main(list(args))
        result = (code, out.getvalue(), err.getvalue())
        self.assertTrue(all(value not in result[2] for value in VALUES), result)
        self.assertTrue(
            all(value not in result[1] for value in VALUES)
            or result[1] == "username=sh4i-yurei\npassword=dummy-gh\n",
            result,
        )
        return result

    def test_get_exact_item(self):
        self.environment["BW_SESSION"] = "dummy-session"
        self.assertEqual(
            self.run_helper(("get",)),
            (0, "username=sh4i-yurei\npassword=dummy-gh\n", ""),
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

    def test_other_operations_do_not_read(self):
        for args in ((), ("store",), ("erase",)):
            with self.subTest(args=args):
                self.assertEqual(self.run_helper(args), (0, "", ""))
                self.assertFalse(self.calls_file.exists())

    def test_missing_empty_or_nonstring_token(self):
        for value in (None, "", 42):
            with self.subTest(value=value):
                self.calls_file.unlink(missing_ok=True)

                def change(items):
                    if value is None:
                        items[1]["fields"] = [
                            f for f in items[1]["fields"] if f["name"] != "GH_TOKEN"
                        ]
                    else:
                        items[1]["fields"][1]["value"] = value

                self.copy_items(change)
                self.assertEqual(
                    self.run_helper(("get",)),
                    (1, "", f'git-credential-bw: no GH_TOKEN on "{TOKEN}"\n'),
                )

    def test_container_and_duplicate(self):
        self.marker.unlink()
        self.assertEqual(
            self.run_helper(("get",)),
            (
                1,
                "",
                "git-credential-bw: bw runs only inside the dev container (distrobox enter dev)\n",
            ),
        )
        self.assertFalse(self.calls_file.exists())
        self.marker.touch()
        self.copy_items(lambda items: items.insert(2, json.loads(json.dumps(items[1]))))
        self.assertEqual(
            self.run_helper(("get",)),
            (1, "", f'git-credential-bw: 2 vault items are named exactly "{TOKEN}"\n'),
        )

    def test_get_does_not_consume_stdin(self):
        read_fd, write_fd = os.pipe()
        data = b"protocol=https\nhost=github.com\n\n"
        os.write(write_fd, data)
        os.close(write_fd)
        with os.fdopen(read_fd, "r") as incoming, patch.object(sys, "stdin", incoming):
            self.assertEqual(
                self.run_helper(("get",)),
                (0, "username=sh4i-yurei\npassword=dummy-gh\n", ""),
            )
            self.assertEqual(incoming.read(), data.decode())

    def test_link_and_main_line(self):
        link = self.root / "git-credential-bw"
        source_root = ROOT.parent if ROOT.name == "mutants" else ROOT
        link.symlink_to(source_root / "tools/git_credential_bw.py")
        home = self.root / "home"
        home.mkdir()
        env = {"PATH": self.environment["PATH"] + ":/bin", "HOME": str(home)}
        result = subprocess.run(
            [sys.executable, str(link), "store"],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        with (
            patch.object(
                sys, "argv", [str(ROOT / "tools/git_credential_bw.py"), "store"]
            ),
            self.assertRaises(SystemExit) as raised,
        ):
            runpy.run_path(
                str(ROOT / "tools/git_credential_bw.py"), run_name="__main__"
            )
        self.assertEqual(raised.exception.code, 0)
