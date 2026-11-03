"""Focused regressions from the third W1 review round."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from io import StringIO
from pathlib import Path
from unittest import mock
import pytest


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks/git-guard.py"
FEATURE = str(ROOT)
FORCE = "git push --for" + "ce origin x"


def scope_cases():
    with tempfile.TemporaryDirectory(prefix=".guard-scope-", dir=ROOT) as path:
        subprocess.run(["git", "init", "-q", "--initial-branch=main", path], check=True)
        for command in (
            "(cd " + FEATURE + " && true); git " + "merge x",
            "cd " + FEATURE + " | cat; git " + "merge x",
        ):
            check("deny", command, path)


def oversized_case():
    command = "git " + "merge x; " + "echo x; " * 9000
    assert len(command.encode()) > 64 * 1024
    actual, reason = decision(command)
    assert actual == "deny" and "too large" in reason.lower(), reason


def deadline_case():
    spec = importlib.util.spec_from_file_location("round4_guard", HOOK)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    event = {
        "tool_name": "Bash",
        "cwd": FEATURE,
        "tool_input": {"command": "git " + "merge x"},
    }
    output = StringIO()
    with (
        mock.patch.object(guard.time, "monotonic", side_effect=[0, 6]),
        mock.patch.object(sys, "stdin", StringIO(json.dumps(event))),
        mock.patch.object(sys, "stdout", output),
        mock.patch.object(sys, "argv", [str(HOOK), "--agent", "claude"]),
        mock.patch.object(sys, "path", [str(ROOT / "hooks"), *sys.path]),
    ):
        guard.main()
    payload = json.loads(output.getvalue())["hookSpecificOutput"]
    assert payload["permissionDecision"] == "deny", payload
    assert "too complex" in payload["permissionDecisionReason"].lower(), payload


def decision(command, cwd=None, agent="claude"):
    cwd = FEATURE if cwd is None else cwd
    event = {"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": command}}
    result = subprocess.run(
        [sys.executable, str(HOOK), "--agent", agent],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=True,
    )
    assert not result.stderr, result.stderr
    if not result.stdout:
        return "allow", ""
    payload = json.loads(result.stdout)["hookSpecificOutput"]
    return payload["permissionDecision"], payload["permissionDecisionReason"]


def check(expected, command, cwd=None, agent="claude"):
    actual, reason = decision(command, cwd, agent)
    assert actual == expected, (command, expected, actual, reason)


def main():
    scope_cases()
    oversized_case()
    deadline_case()
    # This fixture's origin is deliberately outside Claude's direct push list.
    temporary = tempfile.TemporaryDirectory(prefix=".guard-round3-", dir=ROOT)
    infra = Path(temporary.name)
    subprocess.run(
        ["git", "init", "-q", "--initial-branch=main", str(infra)], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(infra),
            "remote",
            "add",
            "origin",
            "https://github.com/example/infra.git",
        ],
        check=True,
    )
    try:
        for command in (
            "git push --tags origin main",
            "git push origin main --tags",
            "git push origin HEAD --tags",
        ):
            check("deny", command, str(infra))
        check("allow", "git push --tags", str(infra))

        for command in (
            "echo hi | (" + FORCE + ")",
            "echo hi | { " + FORCE + "; }",
            "ls | while read l; do " + FORCE + "; done",
            "true | if true; then " + FORCE + "; fi",
            "(" + FORCE + ") | cat",
            '{ :; } > "$(' + FORCE + ')"',
        ):
            check("deny", command)

        for command in (
            "env -- " + FORCE,
            "command -- " + FORCE,
            "exec " + FORCE,
            "sudo -D /tmp " + FORCE,
            'bash <<< "' + FORCE + '"',
            "flatpak-spawn --host " + FORCE,
        ):
            check("deny", command)

        command = "; ".join(
            "git --work-tree=/w" + str(index) + " merge x" for index in range(1700)
        )
        start = time.monotonic()
        actual, reason = decision(command)
        assert actual == "deny" and "too complex" in reason.lower(), reason
        assert time.monotonic() - start < 7

        vendor_files = {
            str(path.relative_to(ROOT / "vendor"))
            for path in (ROOT / "vendor/bashlex").glob("*.py")
        }
        vendor_files.add("bashlex/LICENSE")
        assert vendor_files == set(VENDOR_SHA256), vendor_files ^ set(VENDOR_SHA256)
        for relative, digest in VENDOR_SHA256.items():
            actual = hashlib.sha256(
                (ROOT / "vendor" / relative).read_bytes()
            ).hexdigest()
            assert actual == digest, relative
    finally:
        temporary.cleanup()
    print("round 3 regressions passed")


VENDOR_SHA256 = {
    "bashlex/LICENSE": "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903",
    "bashlex/__init__.py": "99fedb241aaec2cc9d0cb5000907d73b55f198d9b73480bfb6da81b9929f155c",
    "bashlex/ast.py": "24ae9d556f9d8afc6e1339366f7cf62745465ac0bfccccf96ef211f49ea16ecf",
    "bashlex/errors.py": "769504ca772ca3f5b5d403a4e84c896830b180d4573ba2c02c7ba425ed20bcd3",
    "bashlex/flags.py": "0a2805efaaa807570a019ffbea3de3b394cf24e41bc58ed3036a13c98974522d",
    "bashlex/heredoc.py": "ff3a51cef6b496dfdfb98fd8e7ed9f7f3013ac9afa377f73e9d9b14e73772449",
    "bashlex/parser.py": "fdddc8c057b8668f4be040711e62d651a6c52e9b0e4fd36dfaa3876b3cb53ff8",
    "bashlex/parsetab.py": "b10eff3b953ead33c770f29506bfaa90f6e474399740eedf89c4481cccda6389",
    "bashlex/shutils.py": "739908891397422faf8d4dceff47c5ffa18148f4fd7691766c4119ba66645a5f",
    "bashlex/state.py": "620b7a35cea8de35a48e6fe218020a3b8480bb0ac74e1b8a6470a293ea5ca418",
    "bashlex/subst.py": "9b822ca200d0e5419716f1f52671da4fcc6f5a3390110f1aada3fcddaff233ce",
    "bashlex/tokenizer.py": "3eb6f050057b92e7ec0024627698a01d636ae3acaf27135ae1e68b68c0fd8268",
    "bashlex/utils.py": "71720b4dadecba24115900bb54ff1281d63570ccdb539016e896c01e088b9444",
    "bashlex/yacc.py": "a51bde6abb37d8c9fb985a31a78f35d8d24bf73a921e03cd2adb848d787e5792",
}


def test_round3_regressions(tmp_path, monkeypatch):
    feature = tmp_path / "feature"
    subprocess.run(
        ["git", "init", "-q", "--initial-branch=feature/test", str(feature)],
        check=True,
    )
    monkeypatch.setattr(sys.modules[__name__], "FEATURE", str(feature))
    main()


if __name__ == "__main__":
    pytest.main([__file__])
