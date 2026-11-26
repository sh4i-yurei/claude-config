"""Check that no test reaches the real home folder, Claude's folder or the vault."""

import inspect
import os
import pwd
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "mutants"
    if os.environ.get("MUTANT_UNDER_TEST") and ROOT.name != "mutants"
    else ROOT
)
sys.path.insert(0, str(SOURCE / "skills/research/scripts"))
sys.path.insert(0, str(SOURCE))

import common
import gw

from skills.research.scripts import research

REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
SEEN = []


def environment_folders():
    folders = {}
    for name in ("HOME", "SECOND_BRAIN", "CLAUDE_CONFIG_DIR"):
        value = os.environ.get(name)
        assert value is not None, f"{name} is not set"
        folders[name] = Path(value).resolve()
    return folders


@pytest.mark.parametrize("run", [1, 2])
def test_each_test_gets_its_own_folders(run):
    folders = environment_folders()
    earlier = list(SEEN)
    SEEN.append(folders)

    parent = folders["HOME"].parent
    assert parent.name.startswith("isolated"), folders
    assert folders == {
        "HOME": parent / "home",
        "SECOND_BRAIN": parent / "vault",
        "CLAUDE_CONFIG_DIR": parent / "claude",
    }
    for path in folders.values():
        assert not path.is_relative_to(REAL_HOME), path
    for entry in earlier:
        for name, path in folders.items():
            assert path != entry[name], name


def test_gateway_lock_default_is_in_the_session_folder():
    lock = inspect.signature(common.gateway_lock).parameters["path"].default
    lock = Path(lock).resolve()
    assert not lock.is_relative_to(REAL_HOME), lock

    with common.gateway_lock():
        assert lock.is_file()

    assert lock.name == "research-gw.lock"
    assert lock.parent.name == ".claude"
    assert lock.parent.parent.name == "home"
    assert lock.parent.parent.parent.name.startswith("claude-config-tests-")
    assert Path(gw.STATE).resolve().parent == lock.parent
    assert Path(gw.LOCK).resolve().parent == lock.parent


def test_new_topic_without_root_writes_under_the_test_vault():
    vault = Path(os.environ["SECOND_BRAIN"]).resolve()
    assert vault.parent.name.startswith("isolated"), vault

    returned = research.new_topic("isolation-check", "survey", "Does isolation hold?")

    assert returned.parents[1].resolve() == vault / "70_Research" / "isolation-check"
    assert returned.is_file()
    assert not returned.resolve().is_relative_to(REAL_HOME), returned
