"""Keep every test away from the real home folder, Claude's folder and the vault.

pytest imports this file before any test module, so the research tools' paths
computed from Path.home() at import time land inside a temporary session folder.
"""

import atexit
import os
import shutil
import site
import tempfile

import pytest

FOLDERS = (
    ("HOME", "home"),
    ("SECOND_BRAIN", "vault"),
    ("CLAUDE_CONFIG_DIR", "claude"),
)

# The Python programs the tests start keep the user site's packages, such as
# mutmut, even though HOME no longer points at the real home folder.
os.environ.setdefault("PYTHONUSERBASE", site.getuserbase())

SESSION_FOLDER = tempfile.mkdtemp(prefix="claude-config-tests-")
atexit.register(shutil.rmtree, SESSION_FOLDER, True)
for name, subfolder in FOLDERS:
    path = os.path.join(SESSION_FOLDER, subfolder)
    os.mkdir(path)
    os.environ[name] = path


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """Give each test its own home, vault and Claude folders."""
    folder = tmp_path_factory.mktemp("isolated")
    for name, subfolder in FOLDERS:
        path = folder / subfolder
        path.mkdir()
        monkeypatch.setenv(name, str(path))
