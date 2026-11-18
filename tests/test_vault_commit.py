"""Public behavior of vault-commit in disposable Git repositories."""

import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest
from tools import vault_commit


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
    if extra_env and "SECOND_BRAIN" in extra_env and extra_env["SECOND_BRAIN"] is None:
        env.pop("SECOND_BRAIN")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd or vault,
        env=env,
        text=True,
        capture_output=True,
    )


def run_in_process(
    vault,
    home,
    monkeypatch,
    capfd,
    *args,
    cwd=None,
    main_style=False,
    default_vault=False,
    no_argv=False,
):
    if default_vault:
        monkeypatch.delenv("SECOND_BRAIN", raising=False)
    else:
        monkeypatch.setenv("SECOND_BRAIN", str(vault))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd or vault)
    if main_style:
        monkeypatch.setattr(sys, "argv", [str(ROOT / "tools/vault_commit.py"), *args])
        with pytest.raises(SystemExit) as result:
            runpy.run_path(str(ROOT / "tools/vault_commit.py"), run_name="__main__")
        code = result.value.code
    else:
        if no_argv:
            monkeypatch.setattr(sys, "argv", ["vault-commit", *args])
        code = vault_commit.main() if no_argv else vault_commit.main(list(args))
    output = capfd.readouterr()
    return code, output.out, output.err


@pytest.fixture(params=("child", "in_process"))
def runner(request, monkeypatch, capfd):
    def run(
        vault,
        home,
        *args,
        cwd=None,
        main_style=False,
        default_vault=False,
        no_argv=False,
    ):
        if request.param == "child":
            result = run_child(
                vault,
                home,
                *args,
                cwd=cwd,
                extra_env={"SECOND_BRAIN": None} if default_vault else None,
            )
            return result.returncode, result.stdout, result.stderr
        return run_in_process(
            vault,
            home,
            monkeypatch,
            capfd,
            *args,
            cwd=cwd,
            main_style=main_style,
            default_vault=default_vault,
            no_argv=no_argv,
        )

    return run


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


@pytest.mark.parametrize("mode", ("child", "in_process"))
def test_unborn_branch_raises_git_error(tmp_path, monkeypatch, capfd, mode):
    vault = tmp_path / "vault"
    origin = tmp_path / "origin.git"
    home = tmp_path / "home"
    vault.mkdir()
    home.mkdir()
    git(vault, "init", "-q", "-b", "main")
    git(vault, "config", "user.name", "Test")
    git(vault, "config", "user.email", "test@example.invalid")
    git(vault, "init", "-q", "--bare", str(origin))
    git(vault, "remote", "add", "origin", str(origin))
    git(vault, "config", "core.hooksPath", ".githooks")
    (vault / ".githooks").mkdir()
    set_hook(vault, "#!/bin/sh\nprintf 'ran\\n' >> hook-runs\n")
    (vault / "c.txt").write_text("c\n")

    if mode == "child":
        result = run_child(vault, home, "-m", "add c", "--", "c.txt")
        assert result.returncode == 1
        assert result.stdout == ""
        assert "subprocess.CalledProcessError" in result.stderr
        assert "kept moving" not in result.stderr
    else:
        monkeypatch.setenv("SECOND_BRAIN", str(vault))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(vault)
        with pytest.raises(subprocess.CalledProcessError):
            vault_commit.main(["-m", "add c", "--", "c.txt"])
        output = capfd.readouterr()
        assert output.out == ""
        assert "kept moving" not in output.err

    assert not (vault / "hook-runs").exists()
    assert git(vault, "rev-list", "--all", "--count").stdout.strip() == "0"
    assert git(origin, "rev-list", "--all", "--count").stdout.strip() == "0"


def test_untracked_text_allowed_by_ignore_exception(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    (vault / ".gitignore").write_text("*\n!*.txt\n!.gitignore\n")
    git(vault, "add", ".gitignore")
    git(vault, "commit", "-qm", "ignore other files")
    git(vault, "push", "-q", "origin", "main")
    (vault / "c.txt").write_text("c\n")

    code, out, err = runner(vault, home, "-m", "add c", "--", "c.txt")

    assert (code, err) == (0, "")
    assert out == git(vault, "log", "--oneline", "-1").stdout
    assert changed(vault) == ["c.txt"]
    assert git(vault, "show", "HEAD:c.txt").stdout == "c\n"
    assert origin_head(origin) == head(vault)


def test_private_index_preserves_other_staged_file(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    (vault / "c.txt").write_text("c\n")
    (vault / "d.txt").write_text("d\n")
    git(vault, "add", "d.txt")
    code, out, err = runner(vault, home, "-m", "add c", "--", "c.txt")
    assert (code, err) == (0, "")
    assert out == f"{head(vault)[:7]} add c\n"
    assert changed(vault) == ["c.txt"]
    assert origin_head(origin) == head(vault)
    assert staged(vault) == ["d.txt"]
    assert git(vault, "status", "--porcelain", "--untracked-files=all").stdout == (
        "A  d.txt\n?? .githooks/pre-commit\n"
    )
    assert git(vault, "log", "-1", "--format=%B").stdout == "add c\n\n"


def test_private_index_main_module_entry(tmp_path, monkeypatch, capfd):
    vault, origin, home = setup_vault(tmp_path)
    (vault / "c.txt").write_text("c\n")
    (vault / "d.txt").write_text("d\n")
    git(vault, "add", "d.txt")
    code, out, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "add c", "--", "c.txt", main_style=True
    )
    assert (code, out, err) == (0, f"{head(vault)[:7]} add c\n", "")
    assert (changed(vault), staged(vault), origin_head(origin)) == (
        ["c.txt"],
        ["d.txt"],
        head(vault),
    )


def test_main_reads_argv_in_process(tmp_path, monkeypatch, capfd):
    vault, origin, home = setup_vault(tmp_path)
    (vault / "c.txt").write_text("c\n")
    code, out, err = run_in_process(
        vault, home, monkeypatch, capfd, "-m", "add c", "--", "c.txt", no_argv=True
    )
    assert (code, out, err) == (0, f"{head(vault)[:7]} add c\n", "")
    assert (changed(vault), origin_head(origin), staged(vault)) == (
        ["c.txt"],
        head(vault),
        [],
    )


def test_default_vault(tmp_path, runner):
    home = tmp_path / "home"
    home.mkdir()
    documents = home / "Documents"
    documents.mkdir()
    vault, origin, _ = setup_vault(documents)
    vault.rename(documents / "Second_Brain")
    vault = documents / "Second_Brain"
    (vault / "c.txt").write_text("c\n")
    code, out, err = runner(
        vault, home, "-m", "add c", "--", "c.txt", default_vault=True
    )
    assert (code, out, err) == (0, f"{head(vault)[:7]} add c\n", "")
    assert (changed(vault), origin_head(origin), staged(vault)) == (
        ["c.txt"],
        head(vault),
        [],
    )


def test_absolute_path_from_outside_vault(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    (vault / "c.txt").write_text("c\n")
    code, out, err = runner(
        vault, home, "-m", "add c", "--", str(vault / "c.txt"), cwd=tmp_path
    )
    assert (code, out, err) == (0, f"{head(vault)[:7]} add c\n", "")
    assert (changed(vault), origin_head(origin), staged(vault)) == (
        ["c.txt"],
        head(vault),
        [],
    )


def test_absolute_deleted_path_from_outside_vault(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    (vault / "initial.txt").unlink()
    code, out, err = runner(
        vault, home, "-m", "drop", "--", str(vault / "initial.txt"), cwd=tmp_path
    )
    assert (code, out, err) == (0, f"{head(vault)[:7]} drop\n", "")
    assert (changed(vault), origin_head(origin), staged(vault)) == (
        ["initial.txt"],
        head(vault),
        [],
    )


def test_absolute_ignored_path_from_outside_vault(tmp_path, runner):
    vault, _, home = setup_vault(tmp_path)
    (vault / ".gitignore").write_text("secret.txt\n")
    git(vault, "add", ".gitignore")
    git(vault, "commit", "-qm", "ignore")
    (vault / "secret.txt").write_text("secret\n")
    marker = tmp_path / "hook-ran"
    set_hook(vault, f"#!/bin/sh\ntouch '{marker}'\n")
    name = str(vault / "secret.txt")
    code, out, err = runner(vault, home, "-m", "x", "--", name, cwd=tmp_path)
    assert (code, out, err) == (2, "", f"ignored by the vault: {name}\n")
    assert not marker.exists()


def test_hook_stages_another_sessions_file(tmp_path, runner):
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
            code, _, err = runner(vault, home, "-m", "add a", "--", "a.txt")
            assert (code, err, changed(vault), staged(vault)) == (
                0,
                "",
                ["a.txt"],
                ["b.txt"],
            )


def test_hook_moves_branch_once(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    marker = tmp_path / "hook-ran"
    set_hook(
        vault,
        f"#!/bin/sh\nif test ! -e '{marker}'; then\n  touch '{marker}'\n  git add z.txt\n  git commit --no-verify -qm 'add z'\nfi\n",
    )
    (vault / "z.txt").write_text("z\n")
    (vault / "c.txt").write_text("c\n")
    code, _, err = runner(vault, home, "-m", "add c", "--", "c.txt")
    assert (code, err, changed(vault), origin_head(origin)) == (
        0,
        "",
        ["c.txt"],
        head(vault),
    )
    assert git(vault, "log", "-1", "--format=%s", "HEAD^").stdout == "add z\n"


def test_hook_moves_branch_every_attempt(tmp_path, runner):
    vault, _, home = setup_vault(tmp_path)
    count = tmp_path / "hook-count"
    set_hook(
        vault,
        f'#!/bin/sh\nn=$(cat "{count}" 2>/dev/null || echo 0)\nn=$((n + 1))\necho "$n" > "{count}"\necho "$n" > z.txt\ngit add z.txt\ngit commit --no-verify -qm "z $n"\n',
    )
    (vault / "c.txt").write_text("c\n")
    code, out, err = runner(vault, home, "-m", "add c", "--", "c.txt")
    assert (
        code,
        out,
        err.splitlines()[-1],
        count.read_text(),
        git(vault, "log", "--format=%s").stdout.count("add c"),
    ) == (1, "", "main kept moving; nothing committed", "3\n", 0)


def test_push_refusal_leaves_local_commit(tmp_path, runner):
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
    code, out, err = runner(vault, home, "-m", "add c", "--", "c.txt")
    assert code == 1 and out == ""
    assert (
        err.splitlines()[0]
        == f"committed {head(vault)[:7]} locally; the push was refused"
    )
    assert len(err.splitlines()) > 1
    expected = git(vault, "push", "-q", "origin", "main", check=False)
    assert (
        err
        == f"committed {head(vault)[:7]} locally; the push was refused\n{expected.stderr}"
    )
    assert changed(vault) == ["c.txt"]
    assert git(vault, "log", "-1", "--format=%s").stdout == "add c\n"
    assert origin_head(origin) == remote
    assert git(vault, "cat-file", "-e", remote, check=False).returncode == 1


def test_push_with_no_upstream(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    git(vault, "branch", "--unset-upstream")
    git(vault, "config", "push.default", "nothing")
    (vault / "c.txt").write_text("c\n")
    code, out, err = runner(vault, home, "-m", "add c", "--", "c.txt")
    assert (code, out, err) == (0, f"{head(vault)[:7]} add c\n", "")
    assert (changed(vault), origin_head(origin)) == (["c.txt"], head(vault))


def test_success_line_names_own_commit_after_pre_push_moves_head(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    (vault / ".githooks/pre-push").write_text(
        "#!/bin/sh\necho z > z.txt\ngit add z.txt\ngit commit --no-verify -qm 'add z'\n"
    )
    (vault / ".githooks/pre-push").chmod(0o755)
    (vault / "c.txt").write_text("c\n")
    code, out, err = runner(vault, home, "-m", "add c", "--", "c.txt")
    own = git(vault, "rev-parse", "HEAD^").stdout.strip()
    assert (code, out, err) == (0, f"{own[:7]} add c\n", "")
    assert (changed(vault), origin_head(origin)) == (["z.txt"], own)


def test_shared_index_lock_still_pushes(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    set_hook(vault, "#!/bin/sh\ntouch .git/index.lock\n")
    (vault / "c.txt").write_text("c\n")
    try:
        code, out, err = runner(vault, home, "-m", "add c", "--", "c.txt")
        reset = git(vault, "reset", "-q", "--", "c.txt", check=False)
    finally:
        (vault / ".git/index.lock").unlink(missing_ok=True)
    assert code == 1
    assert out == ""
    assert err == (
        reset.stderr
        + f"committed {head(vault)[:7]}, but resetting its paths in the shared index failed\n"
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


def test_hook_failure(tmp_path, runner):
    vault, origin, home = setup_vault(
        tmp_path, "#!/bin/sh\necho 'broken link in x.md'\nexit 1\n"
    )
    (vault / "c.txt").write_text("c\n")
    old = head(vault)
    code, out, err = runner(vault, home, "-m", "add c", "--", "c.txt")
    assert (code, out, err) == (
        1,
        "",
        "broken link in x.md\nvault check failed; nothing committed\n",
    )
    assert (head(vault), staged(vault), origin_head(origin)) == (old, [], old)


def test_missing_hook(tmp_path, runner):
    vault, _, home = setup_vault(tmp_path)
    (vault / ".githooks/pre-commit").unlink()
    (vault / "c.txt").write_text("c\n")
    old = head(vault)
    code, out, err = runner(vault, home, "-m", "add c", "--", "c.txt")
    assert (code, out, err, head(vault)) == (
        2,
        "",
        "the vault has no pre-commit hook: set core.hooksPath\n",
        old,
    )


def test_nonexecutable_hook(tmp_path, runner):
    vault, _, home = setup_vault(tmp_path)
    (vault / ".githooks/pre-commit").chmod(0o644)
    (vault / "c.txt").write_text("c\n")
    old = head(vault)
    code, out, err = runner(vault, home, "-m", "add c", "--", "c.txt")
    assert (code, out, err, head(vault)) == (
        2,
        "",
        "the vault has no pre-commit hook: set core.hooksPath\n",
        old,
    )


def test_absolute_hook_location(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    git(vault, "config", "core.hooksPath", str(vault / ".githooks"))
    (vault / "c.txt").write_text("c\n")
    code, _, err = runner(vault, home, "-m", "add c", "--", "c.txt")
    assert (code, err, changed(vault), origin_head(origin)) == (
        0,
        "",
        ["c.txt"],
        head(vault),
    )


def test_deleted_and_unchanged_paths(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    (vault / "initial.txt").unlink()
    code, _, err = runner(vault, home, "-m", "drop", "--", "initial.txt")
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
    remote = origin_head(origin)
    code, out, err = runner(vault, home, "-m", "same", "--", "same.txt")
    assert (code, out, err, head(vault)) == (
        0,
        "nothing to commit in those paths\n",
        "",
        old,
    )
    assert origin_head(origin) == remote


def test_deleted_from_worktree_and_shared_index(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    (vault / "initial.txt").unlink()
    git(vault, "rm", "--cached", "initial.txt")
    code, out, err = runner(vault, home, "-m", "drop", "--", "initial.txt")
    assert (code, out, err) == (0, f"{head(vault)[:7]} drop\n", "")
    assert (changed(vault), origin_head(origin)) == (["initial.txt"], head(vault))


@pytest.mark.parametrize(
    "kind,message",
    [
        ("outside", "not in the vault"),
        ("directory", "not a file"),
        ("missing", "not found"),
        ("ignored", "ignored by the vault"),
    ],
)
def test_invalid_path_before_hook(tmp_path, runner, kind, message):
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
    code, out, err = runner(vault, home, "-m", "x", "--", path)
    assert (code, out, err) == (2, "", f"{message}: {path}\n")
    assert not marker.exists()


def test_dash_prefixed_file_commits(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    (vault / "-notes.md").write_text("notes\n")
    code, out, err = runner(vault, home, "-m", "notes", "--", "-notes.md")
    assert (code, out, err) == (0, f"{head(vault)[:7]} notes\n", "")
    assert (changed(vault), origin_head(origin)) == (["-notes.md"], head(vault))


def test_dash_prefixed_ignored_file_refused_before_hook(tmp_path, runner):
    vault, _, home = setup_vault(tmp_path)
    (vault / ".gitignore").write_text("-secret.txt\n")
    git(vault, "add", ".gitignore")
    git(vault, "commit", "-qm", "ignore")
    (vault / "-secret.txt").write_text("secret\n")
    marker = tmp_path / "hook-ran"
    set_hook(vault, f"#!/bin/sh\ntouch '{marker}'\n")
    code, out, err = runner(vault, home, "-m", "x", "--", "-secret.txt")
    assert (code, out, err) == (2, "", "ignored by the vault: -secret.txt\n")
    assert not marker.exists()


def test_subfolder_relative_and_absolute(tmp_path, runner):
    vault, origin, home = setup_vault(tmp_path)
    folder = vault / "sub"
    folder.mkdir()
    for number, path in enumerate(("one.txt", str(folder / "two.txt"))):
        (folder / f"{'one' if number == 0 else 'two'}.txt").write_text("x\n")
        code, _, err = runner(vault, home, "-m", "sub", "--", path, cwd=folder)
        assert (code, err, changed(vault), origin_head(origin)) == (
            0,
            "",
            [f"sub/{'one' if number == 0 else 'two'}.txt"],
            head(vault),
        )
        assert staged(vault) == []


def test_detached_head(tmp_path, runner):
    vault, _, home = setup_vault(tmp_path)
    (vault / "c.txt").write_text("c\n")
    git(vault, "checkout", "-q", "--detach")
    code, out, err = runner(vault, home, "-m", "x", "--", "c.txt")
    assert (code, out, err) == (2, "", "the vault is not on a branch\n")


@pytest.mark.parametrize(
    "args,error",
    [
        (("--", "c.txt"), "the following arguments are required: -m"),
        (("-m", "x"), "-- before PATH is required"),
        (("-m", "x", "c.txt"), "unrecognized arguments: c.txt"),
        (("-m", "x", "--"), "at least one PATH is required"),
    ],
)
def test_usage(tmp_path, runner, args, error):
    vault, _, home = setup_vault(tmp_path)
    code, out, err = runner(vault, home, *args)
    assert (code, out, err) == (
        2,
        "",
        f"usage: vault-commit -m MESSAGE -- PATH [PATH...]\nvault-commit: error: {error}\n",
    )


def test_help_shows_message_option(tmp_path, runner):
    vault, _, home = setup_vault(tmp_path)
    code, out, err = runner(vault, home, "-h")
    assert code == 0
    assert err == ""
    assert "  -m MESSAGE" in out.splitlines()


def test_not_repository_top_level(tmp_path, runner):
    vault, _, home = setup_vault(tmp_path)
    bad = vault / "sub"
    bad.mkdir()
    code, out, err = runner(bad, home, "-m", "x", "--", "c.txt")
    assert (code, out, err) == (2, "", f"not a git repository: {bad}\n")


def test_plain_folder_is_not_repository(tmp_path, runner):
    bad = tmp_path / "plain"
    bad.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    code, out, err = runner(bad, home, "-m", "x", "--", "c.txt")
    assert (code, out, err) == (2, "", f"not a git repository: {bad}\n")


def test_missing_vault_folder(tmp_path, runner):
    missing = tmp_path / "absent-vault"
    home = tmp_path / "home"
    home.mkdir()
    code, out, err = runner(missing, home, "-m", "x", "--", "c.txt", cwd=tmp_path)
    assert (code, out, err) == (2, "", f"not a git repository: {missing}\n")
