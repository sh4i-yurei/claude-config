"""Public behavior of vault-commit in disposable Git repositories."""

import importlib.util
import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT.parent if ROOT.name == "mutants" else ROOT
SCRIPT = SOURCE_ROOT / "tools/vault_commit.py"


def git(vault, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=vault, text=True, capture_output=True, check=check
    )


def setup_vault(tmp_path, hook="#!/bin/sh\nexit 0\n"):
    vault = tmp_path / "vault"
    origin = tmp_path / "origin.git"
    vault.mkdir()
    git(vault, "init", "-q", "-b", "main")
    git(vault, "config", "user.name", "Test")
    git(vault, "config", "user.email", "test@example.invalid")
    (vault / "initial.txt").write_text("initial\n")
    git(vault, "add", "initial.txt")
    git(vault, "commit", "-qm", "initial")
    git(vault, "init", "-q", "--bare", str(origin))
    git(vault, "remote", "add", "origin", str(origin))
    git(vault, "push", "-q", "-u", "origin", "main")
    git(vault, "config", "core.hooksPath", ".githooks")
    hooks = vault / ".githooks"
    hooks.mkdir()
    set_hook(vault, hook)
    home = tmp_path / "home"
    home.mkdir()
    return vault, origin, home


def set_hook(vault, content):
    path = vault / ".githooks/pre-commit"
    path.write_text(content)
    path.chmod(0o755)


def run_child(vault, home, *args, cwd=None, extra_env=None):
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "SECOND_BRAIN": str(vault),
    }
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd or vault,
        env=env,
        text=True,
        capture_output=True,
    )


def run_in_process(vault, home, monkeypatch, capfd, *args, cwd=None, main_style=False):
    monkeypatch.setenv("SECOND_BRAIN", str(vault))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd or vault)
    if main_style:
        monkeypatch.setattr(sys, "argv", [str(ROOT / "tools/vault_commit.py"), *args])
        with pytest.raises(SystemExit) as result:
            runpy.run_path(str(ROOT / "tools/vault_commit.py"), run_name="__main__")
        code = result.value.code
    else:
        spec = importlib.util.spec_from_file_location(
            "vault_commit", ROOT / "tools/vault_commit.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        code = module.main(list(args))
    output = capfd.readouterr()
    return code, output.out, output.err


def head(vault):
    return git(vault, "rev-parse", "HEAD").stdout.strip()


def changed(vault):
    return git(
        vault, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
    ).stdout.splitlines()


def staged(vault):
    return git(vault, "diff", "--cached", "--name-only").stdout.splitlines()


def origin_head(origin):
    return git(origin, "rev-parse", "refs/heads/main").stdout.strip()


def test_private_index_preserves_other_staged_file(tmp_path, monkeypatch, capfd):
    vault, origin, home = setup_vault(tmp_path)
    (vault / "c.txt").write_text("c\n")
    (vault / "d.txt").write_text("d\n")
    git(vault, "add", "d.txt")
    code, out, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "add c", "--", "c.txt", main_style=True
    )
    assert (code, err) == (0, "")
    assert out.splitlines()[-1] == f"{head(vault)[:7]} add c"
    assert changed(vault) == ["c.txt"]
    assert origin_head(origin) == head(vault)
    assert staged(vault) == ["d.txt"]
    assert git(vault, "log", "-1", "--format=%B").stdout == "add c\n\n"


def test_hook_stages_another_sessions_file(tmp_path, monkeypatch, capfd):
    for name in ("plain", "private"):
        base = tmp_path / name
        base.mkdir()
        vault, _, home = setup_vault(base)
        marker = base / "hook-ran"
        set_hook(
            vault,
            f"#!/bin/sh\nif test ! -e '{marker}'; then\n  touch '{marker}'\n  env -u GIT_INDEX_FILE git add b.txt\nfi\n",
        )
        (vault / "a.txt").write_text("a\n")
        (vault / "b.txt").write_text("b\n")
        if name == "plain":
            git(vault, "add", "a.txt")
            git(vault, "commit", "-qm", "plain a")
            assert changed(vault) == ["a.txt", "b.txt"]
        else:
            code, _, err = run_in_process(
                vault, home, monkeypatch, capfd, "-m", "add a", "--", "a.txt"
            )
            assert (code, err, changed(vault), staged(vault)) == (
                0,
                "",
                ["a.txt"],
                ["b.txt"],
            )


def test_hook_moves_branch_once(tmp_path, monkeypatch, capfd):
    vault, origin, home = setup_vault(tmp_path)
    marker = tmp_path / "hook-ran"
    set_hook(
        vault,
        f"#!/bin/sh\nif test ! -e '{marker}'; then\n  touch '{marker}'\n  git add z.txt\n  git commit --no-verify -qm 'add z'\nfi\n",
    )
    (vault / "z.txt").write_text("z\n")
    (vault / "c.txt").write_text("c\n")
    code, _, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "add c", "--", "c.txt"
    )
    assert (code, err, changed(vault), origin_head(origin)) == (
        0,
        "",
        ["c.txt"],
        head(vault),
    )
    assert git(vault, "log", "-1", "--format=%s", "HEAD^").stdout == "add z\n"


def test_hook_moves_branch_every_attempt(tmp_path, monkeypatch, capfd):
    vault, _, home = setup_vault(tmp_path)
    count = tmp_path / "hook-count"
    set_hook(
        vault,
        f'#!/bin/sh\nn=$(cat "{count}" 2>/dev/null || echo 0)\nn=$((n + 1))\necho "$n" > "{count}"\necho "$n" > z.txt\ngit add z.txt\ngit commit --no-verify -qm "z $n"\n',
    )
    (vault / "c.txt").write_text("c\n")
    code, out, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "add c", "--", "c.txt"
    )
    assert (
        code,
        out,
        err.splitlines()[-1],
        count.read_text(),
        git(vault, "log", "--format=%s").stdout.count("add c"),
    ) == (1, "", "main kept moving; nothing committed", "3\n", 0)


def test_push_refusal_leaves_local_commit(tmp_path, monkeypatch, capfd):
    vault, origin, home = setup_vault(tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(origin), str(other))
    git(other, "checkout", "-q", "main")
    git(other, "config", "user.name", "Other")
    git(other, "config", "user.email", "other@example.invalid")
    (other / "other.txt").write_text("other\n")
    git(other, "add", "other.txt")
    git(other, "commit", "-qm", "other")
    git(other, "push", "-q", "origin", "main")
    remote = origin_head(origin)
    (vault / "c.txt").write_text("c\n")
    code, out, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "add c", "--", "c.txt"
    )
    assert code == 1 and out == ""
    assert (
        err.splitlines()[0]
        == f"committed {head(vault)[:7]} locally; the push was refused"
    )
    assert len(err.splitlines()) > 1
    assert origin_head(origin) == remote
    assert git(vault, "cat-file", "-e", remote, check=False).returncode == 1


def test_shared_index_lock_still_pushes(tmp_path, monkeypatch, capfd):
    vault, origin, home = setup_vault(tmp_path)
    set_hook(vault, "#!/bin/sh\ntouch .git/index.lock\n")
    (vault / "c.txt").write_text("c\n")
    try:
        code, _, err = run_in_process(
            vault, home, monkeypatch, capfd, "-m", "add c", "--", "c.txt"
        )
    finally:
        (vault / ".git/index.lock").unlink(missing_ok=True)
    assert code == 1
    assert (
        err.splitlines()[-1]
        == f"committed {head(vault)[:7]}, but resetting its paths in the shared index failed"
    )
    assert changed(vault) == ["c.txt"] and origin_head(origin) == head(vault)


@pytest.mark.parametrize("outcome", ["committed", "refused", "failed"])
def test_temporary_index_cleaned(tmp_path, outcome):
    vault, _, home = setup_vault(tmp_path)
    temp = tmp_path / "temp"
    temp.mkdir()
    (vault / "c.txt").write_text("c\n")
    if outcome == "failed":
        set_hook(vault, "#!/bin/sh\nexit 1\n")
    elif outcome == "refused":
        set_hook(vault, "#!/bin/sh\necho x > .git/index.lock\n")
    result = run_child(
        vault, home, "-m", "add c", "--", "c.txt", extra_env={"TMPDIR": str(temp)}
    )
    if outcome == "refused":
        (vault / ".git/index.lock").unlink()
    assert result.returncode == (0 if outcome == "committed" else 1)
    assert list(temp.iterdir()) == []


def test_hook_failure(tmp_path, monkeypatch, capfd):
    vault, origin, home = setup_vault(
        tmp_path, "#!/bin/sh\necho 'broken link in x.md'\nexit 1\n"
    )
    (vault / "c.txt").write_text("c\n")
    old = head(vault)
    code, out, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "add c", "--", "c.txt"
    )
    assert (code, out, err) == (
        1,
        "",
        "broken link in x.md\nvault check failed; nothing committed\n",
    )
    assert (head(vault), staged(vault), origin_head(origin)) == (old, [], old)


def test_missing_hook(tmp_path, monkeypatch, capfd):
    vault, _, home = setup_vault(tmp_path)
    (vault / ".githooks/pre-commit").unlink()
    (vault / "c.txt").write_text("c\n")
    old = head(vault)
    code, out, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "add c", "--", "c.txt"
    )
    assert (code, out, err, head(vault)) == (
        2,
        "",
        "the vault has no pre-commit hook: set core.hooksPath\n",
        old,
    )


def test_absolute_hook_location(tmp_path, monkeypatch, capfd):
    vault, origin, home = setup_vault(tmp_path)
    git(vault, "config", "core.hooksPath", str(vault / ".githooks"))
    (vault / "c.txt").write_text("c\n")
    code, _, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "add c", "--", "c.txt"
    )
    assert (code, err, changed(vault), origin_head(origin)) == (
        0,
        "",
        ["c.txt"],
        head(vault),
    )


def test_deleted_and_unchanged_paths(tmp_path, monkeypatch, capfd):
    vault, origin, home = setup_vault(tmp_path)
    (vault / "initial.txt").unlink()
    code, _, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "drop", "--", "initial.txt"
    )
    assert (code, err, changed(vault), origin_head(origin)) == (
        0,
        "",
        ["initial.txt"],
        head(vault),
    )
    (vault / "same.txt").write_text("same\n")
    git(vault, "add", "same.txt")
    git(vault, "commit", "-qm", "same")
    old = head(vault)
    code, out, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "same", "--", "same.txt"
    )
    assert (code, out, err, head(vault)) == (
        0,
        "nothing to commit in those paths\n",
        "",
        old,
    )


@pytest.mark.parametrize(
    "kind,message",
    [
        ("outside", "not in the vault"),
        ("directory", "not a file"),
        ("missing", "not found"),
        ("ignored", "ignored by the vault"),
    ],
)
def test_invalid_path_before_hook(tmp_path, monkeypatch, capfd, kind, message):
    vault, _, home = setup_vault(tmp_path)
    marker = tmp_path / "hook-ran"
    set_hook(vault, f"#!/bin/sh\ntouch '{marker}'\n")
    if kind == "outside":
        path = str(tmp_path / "outside.txt")
        Path(path).write_text("outside\n")
    elif kind == "directory":
        path = "folder"
        (vault / path).mkdir()
    elif kind == "missing":
        path = "missing.txt"
    else:
        (vault / ".gitignore").write_text("secret.txt\n")
        git(vault, "add", ".gitignore")
        git(vault, "commit", "-qm", "ignore")
        marker.unlink()
        path = "secret.txt"
        (vault / path).write_text("secret\n")
    code, out, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "x", "--", path
    )
    assert (code, out, err) == (2, "", f"{message}: {path}\n")
    assert not marker.exists()


def test_subfolder_relative_and_absolute(tmp_path, monkeypatch, capfd):
    vault, origin, home = setup_vault(tmp_path)
    folder = vault / "sub"
    folder.mkdir()
    for number, path in enumerate(("one.txt", str(folder / "two.txt"))):
        (folder / f"{'one' if number == 0 else 'two'}.txt").write_text("x\n")
        code, _, err = run_in_process(
            vault, home, monkeypatch, capfd, "-m", "sub", "--", path, cwd=folder
        )
        assert (code, err, changed(vault), origin_head(origin)) == (
            0,
            "",
            [f"sub/{'one' if number == 0 else 'two'}.txt"],
            head(vault),
        )


def test_detached_head(tmp_path, monkeypatch, capfd):
    vault, _, home = setup_vault(tmp_path)
    (vault / "c.txt").write_text("c\n")
    git(vault, "checkout", "-q", "--detach")
    code, out, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "x", "--", "c.txt"
    )
    assert (code, out, err) == (2, "", "the vault is not on a branch\n")


@pytest.mark.parametrize(
    "args", [("--", "c.txt"), ("-m", "x"), ("-m", "x", "c.txt"), ("-m", "x", "--")]
)
def test_usage(tmp_path, monkeypatch, capfd, args):
    vault, _, home = setup_vault(tmp_path)
    code, out, err = run_in_process(vault, home, monkeypatch, capfd, *args)
    assert code == 2 and out == "" and err.startswith("usage: vault-commit")


def test_not_repository_top_level(tmp_path, monkeypatch, capfd):
    vault, _, home = setup_vault(tmp_path)
    bad = vault / "sub"
    bad.mkdir()
    monkeypatch.setenv("SECOND_BRAIN", str(bad))
    monkeypatch.setenv("HOME", str(home))
    code, out, err = run_in_process(
        bad, home, monkeypatch, capfd, "-m", "x", "--", "c.txt"
    )
    assert (code, out, err) == (2, "", f"not a git repository: {bad}\n")
