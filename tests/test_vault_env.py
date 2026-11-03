"""W1b vault-env behavior with a harmless Bitwarden replacement."""

import errno
import os
import pty
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/vault-env"
USAGE = 'usage: eval "$(vault-env)"\n'


class VaultEnvTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".vault-env-test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.marker = self.path / "bw-ran"
        fake = self.path / "bw"
        fake.write_text('#!/bin/sh\nprintf ran > "$BW_MARKER"\n')
        fake.chmod(0o755)
        self.environment = {
            "PATH": f"{self.path}:/usr/bin",
            "BW_MARKER": str(self.marker),
        }

    def test_arguments_never_read_vault(self):
        for argument in ("--help", "-h", "GH_TOKEN"):
            with self.subTest(argument=argument):
                result = subprocess.run(
                    [str(SCRIPT), argument],
                    env=self.environment,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, USAGE)
                self.assertFalse(self.marker.exists())

    def test_terminal_stdout_never_reads_vault(self):
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(
                [str(SCRIPT)],
                env=self.environment,
                stdout=slave,
                stderr=subprocess.PIPE,
            )
            os.close(slave)
            slave = -1
            _, stderr = process.communicate()
            self.assertEqual(process.returncode, 2)
            try:
                terminal_output = os.read(master, 4096)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                terminal_output = b""
            self.assertEqual(terminal_output, b"")
            self.assertEqual(stderr, USAGE.encode())
            self.assertFalse(self.marker.exists())
        finally:
            os.close(master)
            if slave >= 0:
                os.close(slave)

    def test_outside_container_preserves_error(self):
        command = [str(SCRIPT)]
        environment = dict(self.environment)
        if Path("/run/.containerenv").exists():
            command = [
                "flatpak-spawn",
                "--host",
                "--clear-env",
                f"--env=PATH={self.path}:/usr/bin",
                f"--env=BW_MARKER={self.marker}",
                str(SCRIPT),
            ]
            if "DBUS_SESSION_BUS_ADDRESS" in os.environ:
                environment["DBUS_SESSION_BUS_ADDRESS"] = os.environ[
                    "DBUS_SESSION_BUS_ADDRESS"
                ]
        result = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr,
            "vault-env: bw runs only inside the dev container (distrobox enter dev)\n",
        )
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
