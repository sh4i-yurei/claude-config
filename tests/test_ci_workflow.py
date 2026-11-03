"""The caller workflow and test collection contract."""

from pathlib import Path
import tomllib

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_python_workflow_caller():
    workflow = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert workflow["on"] == {"push": {}, "pull_request": {}}
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"python"}
    job = workflow["jobs"]["python"]
    assert job["uses"] == (
        "sh4i-yurei/ci-workflows/.github/workflows/python.yml@"
        "8d1ea0f42d357f6639eda1ac9359b9b1420d8789"
    )
    assert job["with"]["caller_workflow"] == ".github/workflows/ci.yml"
    assert job["with"]["caller_job"] == "python"
    assert job["with"]["coverage_floor"] == "69"
    install = job["with"]["install_command"]
    assert "gh_2.97.0_linux_amd64.tar.gz" in install
    assert "a2c9b8497e1f85b1ad0dfcb78b5a622e098801b8e461e459e88e1ee12f018112" in install
    assert '"$GITHUB_PATH"' in install
    assert "PyYAML==6.0.3" in install
    assert "pytest==9.1.1" in install
    assert "pytest-cov==7.1.0" in install


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
    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
