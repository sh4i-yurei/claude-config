"""The vault runner's public behavior, using a fake Bitwarden executable."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import vault_run

TOKEN_ITEM = "API tokens (keepbreath.ing)"
SUDO_ITEM = "keepbreath0 sudo (hub)"
VALUES = (
    "dummy-cf",
    "dummy-gh",
    "dummy-do",
    "dummy-brevo",
    "dummy-pass",
    "dummy-hash",
    "dummy-session",
)
PYTHON = "/usr/bin/python3"
CREATE = [PYTHON, "-c", "open('ran','w')"]


class VaultRunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls_file = self.root / "calls.jsonl"
        self.session = self.root / "bw-session"
        self.session.write_text("dummy-session")
        self.marker = self.root / "container"
        self.marker.touch()
        fake = self.bin / "bw"
        fake.write_text("""#!/usr/bin/python3
import json, os, sys
from pathlib import Path
with Path(os.environ["FAKE_BW_CALLS"]).open("a") as output:
    output.write(json.dumps({"args": sys.argv[1:], "session": os.environ.get("BW_SESSION"), "nointeraction": os.environ.get("BW_NOINTERACTION")}) + "\\n")
if not os.environ.get("BW_SESSION"):
    print("Vault is locked.", file=sys.stderr)
    sys.exit(1)
if os.environ.get("FAKE_BW_MODE") == "failed-json":
    print('{"fields": [{"name": "GH_TOKEN", "value": "dummy-gh"}]}')
    sys.exit(1)
if os.environ.get("FAKE_BW_MODE") == "stderr-secret":
    print("dummy-pass", file=sys.stderr)
items = {
    "API tokens (keepbreath.ing)": {"object": "item", "type": 2, "name": "API tokens (keepbreath.ing)", "secureNote": {"type": 0}, "fields": [{"name": "CLOUDFLARE_API_TOKEN", "value": "dummy-cf", "type": 1}, {"name": "GH_TOKEN", "value": "dummy-gh", "type": 1}, {"name": "DIGITALOCEAN_API_TOKEN", "value": "dummy-do", "type": 1}, {"name": "Brevo_smtp_key", "value": "dummy-brevo", "type": 1}]},
    "keepbreath0 sudo (hub)": {"object": "item", "type": 1, "name": "keepbreath0 sudo (hub)", "login": {"username": "keepbreath0", "password": "dummy-pass", "uris": [], "fido2Credentials": [], "passwordRevisionDate": None}, "fields": [{"name": "hash", "value": "dummy-hash", "type": 1}]},
}
if sys.argv[1:] != ["get", "item", sys.argv[3]] or sys.argv[3] not in items:
    print("Not found.", file=sys.stderr)
    sys.exit(1)
if os.environ.get("FAKE_BW_MODE") == "no-fields":
    items["API tokens (keepbreath.ing)"].pop("fields")
print(json.dumps(items[sys.argv[3]]))
""")
        fake.chmod(0o755)
        self.environment = dict(os.environ)
        for name in (
            "BW_SESSION",
            "BW_NOINTERACTION",
            "CLOUDFLARE_API_TOKEN",
            "GH_TOKEN",
            "DIGITALOCEAN_API_TOKEN",
            "Brevo_smtp_key",
        ):
            self.environment.pop(name, None)
        self.environment.update(
            PATH=f"{self.bin}:/usr/bin",
            XDG_RUNTIME_DIR=str(self.root),
            FAKE_BW_CALLS=str(self.calls_file),
        )

    def run_vault(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        previous = Path.cwd()
        captured_stdout = self.root / "stdout"
        captured_stderr = self.root / "stderr"
        saved_stdout, saved_stderr = os.dup(1), os.dup(2)
        try:
            os.chdir(self.root)
            with (
                captured_stdout.open("w+") as child_stdout,
                captured_stderr.open("w+") as child_stderr,
            ):
                os.dup2(child_stdout.fileno(), 1)
                os.dup2(child_stderr.fileno(), 2)
                with (
                    patch.dict(os.environ, self.environment, clear=True),
                    patch.object(vault_run, "CONTAINER_MARKER", self.marker),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    code = vault_run.main(list(args))
        finally:
            os.dup2(saved_stdout, 1)
            os.dup2(saved_stderr, 2)
            os.close(saved_stdout)
            os.close(saved_stderr)
            os.chdir(previous)
        result = (
            code,
            stdout.getvalue() + captured_stdout.read_text(),
            stderr.getvalue() + captured_stderr.read_text(),
        )
        self.assertTrue(
            all(value not in result[1] + result[2] for value in VALUES), result
        )
        return result

    def calls(self):
        return (
            [json.loads(line) for line in self.calls_file.read_text().splitlines()]
            if self.calls_file.exists()
            else []
        )

    def run_link(self, *args):
        link = self.root / "vault-run"
        link.symlink_to(ROOT / "tools" / "vault_run.py")
        return subprocess.run(
            ["/usr/bin/bash", "-c", '"$0" "$@"', str(link), *args],
            cwd=ROOT,
            env=self.environment,
            capture_output=True,
            text=True,
        )

    def test_link_runs_help_as_command(self):
        result = self.run_link("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            result.stdout.startswith(
                "usage: vault-run [--env NAME]... [--stdin ITEM] -- COMMAND [ARG]...\n"
            ),
            result.stdout,
        )

    def test_link_passes_one_environment_field(self):
        result = self.run_link(
            "--env",
            "GH_TOKEN",
            "--",
            PYTHON,
            "-c",
            "import os,sys; sys.exit(0 if os.environ.get('GH_TOKEN')=='dummy-gh' else 3)",
        )
        if Path("/run/.containerenv").is_file():
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertEqual(result.returncode, 1)
            self.assertEqual(
                result.stderr,
                "vault-run: bw runs only inside the dev container (distrobox enter dev)\n",
            )
            self.assertEqual(self.calls(), [])
        self.assertEqual(result.stdout, "")

    def test_one_environment_field(self):
        child = [
            PYTHON,
            "-c",
            "import os,sys; e=os.environ; sys.exit(0 if e.get('GH_TOKEN')=='dummy-gh' and not any(k in e for k in ('CLOUDFLARE_API_TOKEN','DIGITALOCEAN_API_TOKEN','Brevo_smtp_key','BW_SESSION')) else 3)",
        ]
        self.assertEqual(self.run_vault("--env", "GH_TOKEN", "--", *child), (0, "", ""))
        self.assertEqual(
            self.calls(),
            [
                {
                    "args": ["get", "item", TOKEN_ITEM],
                    "session": "dummy-session",
                    "nointeraction": "true",
                }
            ],
        )

    def test_multiple_environment_fields_both_spellings(self):
        child = [
            PYTHON,
            "-c",
            "import os,sys; e=os.environ; sys.exit(0 if e.get('GH_TOKEN')=='dummy-gh' and e.get('CLOUDFLARE_API_TOKEN')=='dummy-cf' and 'DIGITALOCEAN_API_TOKEN' not in e else 3)",
        ]
        for options in (
            ("--env", "GH_TOKEN", "--env", "CLOUDFLARE_API_TOKEN"),
            ("--env=GH_TOKEN", "--env=CLOUDFLARE_API_TOKEN"),
        ):
            with self.subTest(options=options):
                self.calls_file.unlink(missing_ok=True)
                self.assertEqual(self.run_vault(*options, "--", *child), (0, "", ""))
                self.assertEqual(len(self.calls()), 1)

    def test_password_on_stdin(self):
        child = [
            PYTHON,
            "-c",
            "import sys; sys.exit(0 if sys.stdin.read()=='dummy-pass\\n' else 3)",
        ]
        self.assertEqual(
            self.run_vault("--stdin", SUDO_ITEM, "--", *child), (0, "", "")
        )
        self.assertEqual(
            self.calls(),
            [
                {
                    "args": ["get", "item", SUDO_ITEM],
                    "session": "dummy-session",
                    "nointeraction": "true",
                }
            ],
        )

    def test_environment_and_stdin(self):
        child = [
            PYTHON,
            "-c",
            "import os,sys; sys.exit(0 if os.environ.get('GH_TOKEN')=='dummy-gh' and sys.stdin.read()=='dummy-pass\\n' else 3)",
        ]
        self.assertEqual(
            self.run_vault("--env", "GH_TOKEN", "--stdin=" + SUDO_ITEM, "--", *child),
            (0, "", ""),
        )
        self.assertEqual(
            [call["args"] for call in self.calls()],
            [["get", "item", TOKEN_ITEM], ["get", "item", SUDO_ITEM]],
        )

    def test_child_exit_and_signal(self):
        self.assertEqual(
            self.run_vault(
                "--env", "GH_TOKEN", "--", PYTHON, "-c", "import sys; sys.exit(7)"
            ),
            (7, "", ""),
        )
        self.assertEqual(
            self.run_vault(
                "--env",
                "GH_TOKEN",
                "--",
                PYTHON,
                "-c",
                "import os,signal; os.kill(os.getpid(), signal.SIGTERM)",
            ),
            (143, "", ""),
        )

    def test_missing_field(self):
        self.assertEqual(
            self.run_vault("--env", "NO_SUCH_FIELD", "--", *CREATE),
            (2, "", f'vault-run: no field NO_SUCH_FIELD on "{TOKEN_ITEM}"\n'),
        )
        self.assertFalse((self.root / "ran").exists())

    def test_note_without_fields_has_no_requested_field(self):
        self.environment["FAKE_BW_MODE"] = "no-fields"
        self.assertEqual(
            self.run_vault("--env", "GH_TOKEN", "--", *CREATE),
            (2, "", f'vault-run: no field GH_TOKEN on "{TOKEN_ITEM}"\n'),
        )
        self.assertFalse((self.root / "ran").exists())

    def test_missing_password(self):
        self.assertEqual(
            self.run_vault("--stdin", TOKEN_ITEM, "--", *CREATE),
            (2, "", f'vault-run: "{TOKEN_ITEM}" has no password\n'),
        )
        self.assertFalse((self.root / "ran").exists())

    def test_missing_item(self):
        self.assertEqual(
            self.run_vault("--stdin", "no such item zz", "--", *CREATE),
            (
                1,
                "",
                'vault-run: nothing from the vault for "no such item zz". Is the vault unlocked, and does the item exist? Run vu.\n',
            ),
        )
        self.assertFalse((self.root / "ran").exists())

    def test_missing_session(self):
        self.session.unlink()
        self.assertEqual(
            self.run_vault("--env", "GH_TOKEN", "--", *CREATE),
            (
                1,
                "",
                f'vault-run: nothing from the vault for "{TOKEN_ITEM}". Is the vault unlocked, and does the item exist? Run vu.\n',
            ),
        )
        self.assertEqual(self.calls()[0]["session"], None)
        self.assertFalse((self.root / "ran").exists())

    def test_empty_environment_session_is_not_sent_when_file_is_missing(self):
        self.environment["BW_SESSION"] = ""
        self.session.unlink()
        self.assertEqual(self.run_vault("--env", "GH_TOKEN", "--", *CREATE)[0], 1)
        self.assertEqual(self.calls()[0]["session"], None)

    def test_bw_stderr_is_discarded(self):
        self.environment["FAKE_BW_MODE"] = "stderr-secret"
        self.assertEqual(
            self.run_vault("--env", "GH_TOKEN", "--", PYTHON, "-c", "pass"),
            (0, "", ""),
        )

    def test_failed_bw_response_does_not_supply_a_field(self):
        self.environment["FAKE_BW_MODE"] = "failed-json"
        self.assertEqual(
            self.run_vault("--env", "GH_TOKEN", "--", *CREATE),
            (
                1,
                "",
                f'vault-run: nothing from the vault for "{TOKEN_ITEM}". Is the vault unlocked, and does the item exist? Run vu.\n',
            ),
        )
        self.assertFalse((self.root / "ran").exists())

    def test_environment_session_has_priority(self):
        self.environment["BW_SESSION"] = "dummy-env-session"
        child = [
            PYTHON,
            "-c",
            "import os,sys; e=os.environ; sys.exit(0 if e.get('GH_TOKEN')=='dummy-gh' and 'BW_SESSION' not in e else 3)",
        ]
        self.assertEqual(self.run_vault("--env", "GH_TOKEN", "--", *child), (0, "", ""))
        self.assertEqual(self.calls()[0]["session"], "dummy-env-session")

    def test_bad_arguments_do_not_read_vault(self):
        cases = (
            (),
            ("--env", "GH_TOKEN"),
            ("--env", "GH_TOKEN", "--"),
            ("--", "true"),
            ("--stdin", "a", "--stdin", "b", "--", "true"),
            ("--frobnicate", "--", "true"),
        )
        for args in cases:
            with self.subTest(args=args):
                code, stdout, stderr = self.run_vault(*args)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.startswith("usage: vault-run"), stderr)
                self.assertEqual(self.calls(), [])

    def test_help_does_not_read_vault(self):
        code, stdout, stderr = self.run_vault("--help")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.calls(), [])
        self.assertEqual(
            stdout,
            "usage: vault-run [--env NAME]... [--stdin ITEM] -- COMMAND [ARG]...\n\n"
            "options:\n  -h, --help    show this help message and exit\n"
            "  --env NAME\n  --stdin ITEM\n",
        )

    def test_error_names_the_missing_separator(self):
        self.assertEqual(
            self.run_vault("--env", "GH_TOKEN"),
            (
                2,
                "",
                "usage: vault-run [--env NAME]... [--stdin ITEM] -- COMMAND [ARG]...\nvault-run: error: -- before COMMAND is required\n",
            ),
        )

    def test_error_names_missing_secret_or_command(self):
        self.assertEqual(
            self.run_vault("--", "true"),
            (
                2,
                "",
                "usage: vault-run [--env NAME]... [--stdin ITEM] -- COMMAND [ARG]...\nvault-run: error: one --env or --stdin and one COMMAND are required\n",
            ),
        )

    def test_main_uses_process_arguments(self):
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["vault-run", "--help"]),
            redirect_stdout(output),
        ):
            self.assertEqual(vault_run.main(), 0)
        self.assertTrue(output.getvalue().startswith("usage: vault-run"))

    def test_child_output_passes_through(self):
        child = [
            PYTHON,
            "-c",
            "import sys; print('child-out'); print('child-err', file=sys.stderr)",
        ]
        self.assertEqual(
            self.run_vault("--env", "GH_TOKEN", "--", *child),
            (0, "child-out\n", "child-err\n"),
        )

    def test_child_inherits_stdin_without_stdin_option(self):
        child = [
            PYTHON,
            "-c",
            "import select,sys; ready,_,_=select.select([sys.stdin],[],[],0.2); sys.exit(0 if ready and sys.stdin.read()=='ordinary input' else 3)",
        ]
        saved_stdin = os.dup(0)
        read_end, write_end = os.pipe()
        try:
            os.write(write_end, b"ordinary input")
            os.close(write_end)
            os.dup2(read_end, 0)
            self.assertEqual(
                self.run_vault("--env", "GH_TOKEN", "--", *child), (0, "", "")
            )
        finally:
            os.dup2(saved_stdin, 0)
            os.close(saved_stdin)
            os.close(read_end)

    def test_container_required(self):
        self.marker.unlink()
        self.assertEqual(
            self.run_vault("--env", "GH_TOKEN", "--", *CREATE),
            (
                1,
                "",
                "vault-run: bw runs only inside the dev container (distrobox enter dev)\n",
            ),
        )
        self.assertEqual(self.calls(), [])

    def test_missing_command(self):
        self.assertEqual(
            self.run_vault("--env", "GH_TOKEN", "--", "/nonexistent/command"),
            (127, "", "vault-run: command not found: /nonexistent/command\n"),
        )


if __name__ == "__main__":
    unittest.main()
