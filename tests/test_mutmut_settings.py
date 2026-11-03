"""Check that this repository's mutmut settings invalidate cached verdicts."""

import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest


@pytest.mark.parametrize(
    ("changed_file", "replacement", "reruns"),
    [
        ("tests/test_sample.py", "# Test-only edit.\n", True),
        ("tests/fixtures/issue_open/fake_gh.py", "VALUE = 2\n", True),
        ("tools/workflow/config.py", "def config_value():\n    return 40 + 2\n", False),
        ("hooks/bashlex_compat.py", "def compat_value():\n    return 40 + 2\n", False),
        ("vendor/bashlex/parser.py", "VALUE = 2\n", True),
        (None, None, False),
        ("sample/__init__.py", "def answer():\n    return 40 + 2\n", False),
    ],
)
def test_mutmut_cache_invalidation(tmp_path, changed_file, replacement, reruns):
    repository = Path(__file__).resolve().parents[1]
    settings = tomllib.loads((repository / "pyproject.toml").read_text())["tool"][
        "mutmut"
    ]
    watched = settings.get("cache_invalidation_files", [])
    policy = settings.get("on_dependency_change", "warn")

    files = {
        "sample/__init__.py": "def answer():\n    return 42\n",
        "tests/__init__.py": "",
        "tests/test_sample.py": (
            "from sample import answer\n"
            "from tools.workflow.config import config_value\n"
            "from hooks.bashlex_compat import compat_value\n\n"
            "def test_answer():\n"
            "    assert answer() == 42\n"
            "    assert config_value() == 42\n"
            "    assert compat_value() == 42\n"
        ),
        "tests/fixtures/issue_open/fake_gh.py": "VALUE = 1\n",
        "tools/workflow/config.py": "def config_value():\n    return 42\n",
        "hooks/bashlex_compat.py": "def compat_value():\n    return 42\n",
        "vendor/bashlex/parser.py": "VALUE = 1\n",
        ".gitignore": "mutants/\n__pycache__/\n",
        "pyproject.toml": (
            '[tool.mutmut]\nsource_paths = ["sample", "tools", "hooks"]\n'
            'pytest_add_cli_args_test_selection = ["tests/test_sample.py"]\n'
            f"cache_invalidation_files = {watched!r}\n"
            f'on_dependency_change = "{policy}"\n'
        ),
    }
    for name, contents in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    environment = {key: os.environ[key] for key in ("PATH", "HOME")}
    environment.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")

    def run(command):
        return subprocess.run(
            command,
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )

    for command in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-q",
            "-m",
            "initial",
        ],
    ):
        result = run(command)
        assert result.returncode == 0, result.stdout + result.stderr

    command = [sys.executable, "-m", "mutmut", "run", "--max-children", "1"]
    first = run(command)
    assert first.returncode == 0, first.stdout + first.stderr
    if changed_file is not None:
        path = tmp_path / changed_file
        if changed_file == "tests/test_sample.py":
            path.write_text(replacement + path.read_text())
        else:
            path.write_text(replacement)
    second = run(command)
    output = second.stdout + second.stderr
    assert second.returncode == 0, output
    if reruns:
        assert f"rerunning all mutants: {changed_file}" in output
    else:
        assert "rerunning all mutants" not in output
