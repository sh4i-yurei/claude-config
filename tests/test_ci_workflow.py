"""The caller workflow and test collection contract."""

from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import yaml


ROOT = Path(__file__).resolve().parents[1]

# mutmut 3.8.0's own copy step, in the order its run command calls it. It runs
# in a separate process because mutmut reads pyproject.toml from the current
# folder once and keeps the settings in a module-level variable.
MUTMUT_COPY_STEP = """
from pathlib import Path

from mutmut.utils.file_utils import copy_also_copy_files, copy_src_dir

Path("mutants").mkdir()
copy_src_dir()
copy_also_copy_files()
"""


def test_python_workflow_caller():
    workflow = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert workflow["on"] == {"push": {}}
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"python", "shell"}
    job = workflow["jobs"]["python"]
    assert job["uses"] == (
        "sh4i-yurei/ci-workflows/.github/workflows/python.yml@"
        "6fa70095587800bf834d27d1cf2313a7b8dbb168"
    )
    assert job["with"]["caller_workflow"] == ".github/workflows/ci.yml"
    assert job["with"]["caller_job"] == "python"
    assert job["with"]["coverage_floor"] == "69"
    install = job["with"]["install_command"]
    assert "gh_2.97.0_linux_amd64.tar.gz" in install
    assert "a2c9b8497e1f85b1ad0dfcb78b5a622e098801b8e461e459e88e1ee12f018112" in install
    assert '"$GITHUB_PATH"' in install
    assert (
        "python -m pip install PyYAML==6.0.3 pytest==9.1.1 "
        "pytest-cov==7.1.0 mutmut==3.8.0"
    ) in install.splitlines()
    shell = workflow["jobs"]["shell"]
    assert shell["uses"] == (
        "sh4i-yurei/ci-workflows/.github/workflows/shell.yml@"
        "58da91c02d82b0632d2a31fa9ee81bbb34dfe717"
    )
    assert shell["with"] == {
        "caller_workflow": ".github/workflows/ci.yml",
        "caller_job": "shell",
        "source_paths": '["hooks", "skills/buildlog/scripts", "tools"]',
        "tests_path": "tests/shell",
        "coverage_floor": "73",
    }


def test_python_source_and_collection_settings():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    mutation = config["tool"]["mutmut"]
    assert mutation["source_paths"] == [
        "hooks",
        "tools",
        "skills/research",
        "skills/vault-query",
        "skills/vault-sweep",
    ]
    assert mutation["cache_invalidation_files"] == [
        "tests/*.py",
        "tests/**/*.py",
        "vendor/**/*.py",
    ]
    assert ".mutation-survivors.yml" in mutation["also_copy"]
    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]


def test_mutmut_copies_every_skills_file(tmp_path):
    shutil.copy2(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copytree(
        ROOT / "skills",
        tmp_path / "skills",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    subprocess.run(
        [sys.executable, "-c", MUTMUT_COPY_STEP],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    missing = sorted(
        path.relative_to(tmp_path).as_posix()
        for path in (tmp_path / "skills").rglob("*")
        if path.is_file()
        and not (tmp_path / "mutants" / path.relative_to(tmp_path)).is_file()
    )
    assert missing == []


def test_mutation_survivors_use_shared_check_schema():
    entries = yaml.safe_load((ROOT / ".mutation-survivors.yml").read_text())
    assert isinstance(entries, list)
    assert all(set(entry) == {"mutant", "reason"} for entry in entries)
    assert len({entry["mutant"] for entry in entries}) == len(entries)
    assert {
        entry["mutant"]
        for entry in entries
        if entry["mutant"].startswith(
            "skills.research.scripts.research.x_append_round__"
        )
    } == {
        "skills.research.scripts.research.x_append_round__mutmut_4",
        "skills.research.scripts.research.x_append_round__mutmut_64",
    }
