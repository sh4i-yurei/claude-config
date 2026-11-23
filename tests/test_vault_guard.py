"""Command decisions for direct vault reads and the vault-run wrapper."""

import contextlib
import io
import json
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path


HOOK = Path(__file__).resolve().parents[1] / "hooks/git-guard.py"
sys.path.insert(0, str(HOOK.parent))
SPEC = importlib.util.spec_from_file_location("hooks.git-guard", HOOK)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)
import bashlex
import bashlex_compat

bashlex_compat.install()
GUARD.bashlex = bashlex
GUARD.bashlex_compat = bashlex_compat
SECRET = "Secrets stay out of transcripts: "
ISSUE = "Use tools/workflow/issue.py open; see README.md, Opening an issue from a file."
ATTRIBUTION = (
    "Commits and pull requests carry no AI attribution: remove the Co-authored-by "
    "trailer or Generated with line (Operating model decision 12)."
)


def decision(command, agent, cwd="/tmp"):
    event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}
    argv = [sys.executable, str(HOOK)]
    if agent == "claude":
        argv += ["--agent", "claude"]
    result = subprocess.run(
        argv, input=json.dumps(event), text=True, capture_output=True
    )
    if result.returncode != 0 or result.stderr:
        raise AssertionError((command, result.returncode, result.stderr))
    if result.stdout:
        payload = json.loads(result.stdout)["hookSpecificOutput"]
        if payload["permissionDecision"] != "deny":
            raise AssertionError(payload)
        reason = payload["permissionDecisionReason"]
    else:
        reason = None
    return reason


def in_process_decision(command, agent, cwd="/tmp"):
    def timed_out(_signal, _frame):
        raise TimeoutError(command)

    GUARD.DEADLINE = time.monotonic() + 5
    previous = signal.signal(signal.SIGALRM, timed_out)
    signal.setitimer(signal.ITIMER_REAL, 1)
    try:
        return GUARD.script_problem(command, cwd, agent)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class VaultGuardTests(unittest.TestCase):
    decision = staticmethod(decision)
    COMMIT_REASON = (
        "Commit vault work with vault-commit -m MESSAGE -- PATH...: a plain git "
        "commit in the shared vault checkout can take another session's staged files."
    )

    def scratch_vault(self, root, name="vault"):
        vault = Path(root) / name
        subprocess.run(["git", "init", "-q", "-b", "main", str(vault)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(vault),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "initial",
            ],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(vault),
                "remote",
                "add",
                "origin",
                "https://github.com/sh4i-yurei/second-brain.git",
            ],
            check=True,
        )
        return vault

    def check_vault_commit(self, command, cwd, vault, expected):
        with patch.dict(os.environ, {"SECOND_BRAIN": str(vault)}):
            for agent in ("strict", "claude"):
                with self.subTest(command=command, cwd=str(cwd), agent=agent):
                    self.assertEqual(self.decision(command, agent, str(cwd)), expected)

    def test_shared_vault_commit_forms(self):
        with tempfile.TemporaryDirectory() as root:
            vault = self.scratch_vault(root)
            for command in (
                "git commit -m x",
                "git commit --amend --no-edit",
                "git -c user.name=t commit -m x",
            ):
                self.check_vault_commit(command, vault, vault, self.COMMIT_REASON)

    def test_shared_vault_subfolder_and_directory_switches(self):
        with tempfile.TemporaryDirectory() as root:
            vault = self.scratch_vault(root)
            sub = vault / "sub"
            sub.mkdir()
            self.check_vault_commit("git commit -m x", sub, vault, self.COMMIT_REASON)
            self.check_vault_commit(
                f"git -C {vault} commit -m x", root, vault, self.COMMIT_REASON
            )
            self.check_vault_commit(
                f"cd {vault} && git commit -m x", root, vault, self.COMMIT_REASON
            )

    def test_shared_vault_explicit_git_dir_and_work_tree(self):
        with tempfile.TemporaryDirectory() as root:
            vault = self.scratch_vault(root)
            self.check_vault_commit(
                f"git --git-dir={vault / '.git'} --work-tree={vault} commit -m x",
                root,
                vault,
                self.COMMIT_REASON,
            )

    def test_default_vault_location(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "home"
            (home / "Documents").mkdir(parents=True)
            vault = self.scratch_vault(home / "Documents", "Second_Brain")
            with patch.dict(os.environ, {"HOME": str(home)}):
                os.environ.pop("SECOND_BRAIN", None)
                for agent in ("strict", "claude"):
                    with self.subTest(agent=agent):
                        self.assertEqual(
                            self.decision("git commit -m x", agent, str(vault)),
                            self.COMMIT_REASON,
                        )

    def test_symbolic_vault_location_and_cwd(self):
        with tempfile.TemporaryDirectory() as root:
            vault = self.scratch_vault(root)
            link = Path(root) / "linked-vault"
            link.symlink_to(vault, target_is_directory=True)
            self.check_vault_commit("git commit -m x", vault, link, self.COMMIT_REASON)
            self.check_vault_commit("git commit -m x", link, vault, self.COMMIT_REASON)

    def test_vault_worktree_and_clone_commits_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            vault = self.scratch_vault(root)
            worktree = Path(root) / "worktree"
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(vault),
                    "worktree",
                    "add",
                    "-q",
                    "-b",
                    "test",
                    str(worktree),
                ],
                check=True,
            )
            clone = Path(root) / "clone"
            subprocess.run(["git", "clone", "-q", str(vault), str(clone)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(clone),
                    "remote",
                    "set-url",
                    "origin",
                    "https://github.com/sh4i-yurei/second-brain.git",
                ],
                check=True,
            )
            for cwd in (worktree, clone):
                self.check_vault_commit("git commit -m x", cwd, vault, None)

    def test_other_vault_actions_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            vault = self.scratch_vault(root)
            for command in (
                "git status",
                "git add a.md",
                "git log -1",
                "vault-commit -m x -- a.md",
            ):
                self.check_vault_commit(command, vault, vault, None)

    def test_other_repository_commit_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            vault = self.scratch_vault(root)
            other = Path(root) / "other"
            subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(other),
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/sh4i-yurei/claude-config.git",
                ],
                check=True,
            )
            self.check_vault_commit("git commit -m x", other, vault, None)

    def test_missing_vault_location_allows_commit(self):
        with tempfile.TemporaryDirectory() as root:
            vault = self.scratch_vault(root)
            self.check_vault_commit(
                "git commit -m x", vault, Path(root) / "missing", None
            )

    def check_secret(self, commands):
        for agent in ("claude", "strict"):
            for command in commands:
                with self.subTest(agent=agent, command=command):
                    reason = self.decision(command, agent)
                    self.assertIsNotNone(reason)
                    self.assertTrue(reason.startswith(SECRET), reason)

    def check_allowed(self, commands):
        for agent in ("claude", "strict"):
            for command in commands:
                with self.subTest(agent=agent, command=command):
                    self.assertIsNone(self.decision(command, agent))

    def test_vault_env_commands(self):
        self.check_secret(
            (
                "vault-env",
                "vault-env --help",
                'eval "$(vault-env)"; gh run list --limit 1',
                'x=$(vault-env); eval "$x"',
                'echo "$(vault-env)"',
                "distrobox enter dev -- vault-env",
                "bash -lc 'eval \"$(vault-env)\" && gh run list'",
                "/var/home/sh4i_yurei/.local/bin/vault-env",
                "tools/vault_env.py",
                "./vault_env.py",
                "/var/home/sh4i_yurei/Documents/claude-config/tools/vault_env.py",
            )
        )
        self.check_allowed(
            (
                "grep -n vault-env README.md",
                "rg -n 'vault-env' hooks",
                "git log --grep vault-env --oneline",
                "cat tools/vault_env.py",
                "git log --oneline -- tools/vault_env.py",
            )
        )

    def test_bw_commands(self):
        self.check_secret(
            (
                'bw get item "API tokens (keepbreath.ing)"',
                'bw get password "keepbreath0 sudo (hub)"',
                "bw list items",
                "bw export",
                "bw serve",
                "bw unlock --raw",
                "bw login",
                "bw config server",
                "bw create item x",
                "bw frobnicate",
            )
        )
        self.check_allowed(
            (
                "bw",
                "bw status",
                "bw lock",
                "bw sync",
                "bw --version",
                "bw --help",
                "bw -h",
                "bw help",
            )
        )

    def test_session_paths(self):
        self.check_secret(
            (
                'cat "$XDG_RUNTIME_DIR/bw-session"',
                'cat "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/bw-session"',
                "cat /run/user/1000/bw-session",
                "cp /run/user/1000/bw-session /tmp/key",
                "tr -d x < /run/user/1000/bw-session",
                "python3 -c 1 > /run/user/1000/bw-session",
            )
        )
        self.check_allowed(
            (
                "grep -n bw-session README.md",
                "rg -n bw-session hooks",
                "ls /run/user/1000",
            )
        )

    def test_gh_token_commands(self):
        self.check_secret(
            (
                "gh auth token",
                "gh auth status -t",
                "gh auth status --show-token",
                "gh auth status -at",
                "gh auth status --show-token=true",
                "gh auth status -h github.com -t",
                "gh auth status --json hosts --show-token",
            )
        )
        for command in (
            "gh auth status",
            "gh auth status -a",
            "gh auth status --hostname github.com",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.decision(command, "claude"))

    def test_boolean_flag_attached_values(self):
        for value in (
            "1",
            "t",
            "T",
            "TRUE",
            "true",
            "True",
            "0",
            "f",
            "F",
            "FALSE",
            "false",
            "False",
        ):
            command = "gh auth status --show-token=" + value
            for agent in ("claude", "strict"):
                with self.subTest(command=command, agent=agent):
                    self.assertEqual(
                        self.decision(command, agent),
                        SECRET + "gh auth status can show a token.",
                    )
        for agent in ("claude", "strict"):
            with self.subTest(agent=agent):
                self.assertEqual(
                    self.decision("gh auth status --active=1", agent),
                    self.decision("gh auth status --active", agent),
                )
                self.assertEqual(
                    self.decision("gh auth status -a=1", agent),
                    self.decision("gh auth status -a", agent),
                )
                self.assertEqual(
                    self.decision("gh auth status -t=1", agent),
                    SECRET + "gh auth status can show a token.",
                )
                self.assertEqual(
                    self.decision("gh auth status -at=1", agent),
                    SECRET + "gh auth status can show a token.",
                )
            self.assertEqual(
                self.decision("gh auth status --show-token=yes", agent),
                "The guard can't judge this gh command: it doesn't know the flag --show-token.",
            )

    def test_parse_failure_fallback(self):
        cases = (
            "bw get item x; echo $((1+1))",
            "for ((i=0;i<1;i++)); do bw get item x; done",
            "vault-env; case x in x) ;; esac",
            "cat /run/user/1000/bw-session; echo $((1+1))",
            "git status; echo $((1+1))",
            "b'w' get item x; echo $((1+1))",
        )
        prefix = (
            "Cannot parse a command mentioning git, gh, bw, vault-env or vault-commit: "
        )
        for agent in ("claude", "strict"):
            for command in cases:
                with self.subTest(command=command, agent=agent):
                    reason = self.decision(command, agent)
                    self.assertIsNotNone(reason)
                    self.assertTrue(reason.startswith(prefix), reason)
            self.assertEqual(
                self.decision("git status; echo $((1+1))", agent),
                prefix + "arithmetic expansion",
            )
            self.assertIsNone(self.decision("echo $((1+1))", agent))

    def test_vault_run_wrapper(self):
        self.check_allowed(
            (
                "vault-run --env GH_TOKEN -- gh run list --limit 1",
                "vault-run --env GH_TOKEN --env CLOUDFLARE_API_TOKEN -- tofu plan",
                "vault-run --env=GH_TOKEN -- gh run list --limit 1",
                'vault-run --stdin "keepbreath0 sudo (hub)" -- ssh hub "sudo -S -p \'\' true"',
                "vault-run --help",
            )
        )
        for command, expected in (
            (
                "vault-run --env GH_TOKEN -- gh issue create -R sh4i-yurei/claude-config -t x -b y",
                ISSUE,
            ),
            (
                "vault-run --env GH_TOKEN -- env gh issue create -R sh4i-yurei/claude-config -t x -b y",
                ISSUE,
            ),
            (
                "vault-run --env GH_TOKEN -- git push --force origin main",
                "Force pushes are refused.",
            ),
        ):
            for agent in ("claude", "strict"):
                with self.subTest(agent=agent, command=command):
                    self.assertEqual(self.decision(command, agent), expected)
        self.check_secret(
            (
                "vault-run --env GH_TOKEN -- bw get item x",
                "vault-run --env GH_TOKEN -- sudo bw get item x",
                "vault-run --frobnicate -- gh run list",
                "vault-run --env GH_TOKEN gh run list",
                "vault-run --env",
            )
        )

    def test_existing_unrelated_decisions(self):
        self.check_allowed(
            (
                "env",
                "printenv",
                "export -p",
                "declare -p",
                "set -x",
                "cat /proc/self/environ",
                "ps eww 1",
                "tofu plan",
                "ssh hub \"sudo -S -p '' true\"",
                "gh run list --limit 1",
            )
        )
        for command, expected in (
            ("gh issue create -R sh4i-yurei/claude-config -t x -b y", ISSUE),
            ("git push --force origin main", "Force pushes are refused."),
        ):
            for agent in ("claude", "strict"):
                with self.subTest(agent=agent, command=command):
                    self.assertEqual(self.decision(command, agent), expected)

    def test_gh_version_allowed_for_both_agents(self):
        for agent in ("strict", "claude"):
            with self.subTest(agent=agent):
                self.assertEqual(self.decision("gh --version", agent), None)

    def test_gh_version_allowed_through_path_and_shell(self):
        commands = (
            '"$RUNNER_TEMP/gh_2.97.0_linux_amd64/bin/gh" --version',
            "bash -lc 'gh --version'",
        )
        for command in commands:
            for agent in ("strict", "claude"):
                with self.subTest(command=command, agent=agent):
                    self.assertEqual(self.decision(command, agent), None)

    def test_other_gh_commands_without_subcommands_stay_refused(self):
        reason = "Allowed gh commands: run list/view/watch; pr view/list/diff/checks/status; issue view/list; repo view; api GET."
        for command in ("gh --version --help", "gh --version=1", "gh --help", "gh"):
            for agent, expected in (("strict", reason), ("claude", None)):
                with self.subTest(command=command, agent=agent):
                    self.assertEqual(self.decision(command, agent), expected)

    def test_gh_version_with_unknown_command_stays_refused(self):
        reason = "The guard can't judge this gh command: it doesn't know the command x."
        for agent in ("strict", "claude"):
            with self.subTest(agent=agent):
                self.assertEqual(self.decision("gh --version x", agent), reason)

    def test_gh_version_does_not_allow_later_gh_command(self):
        reason = "Allowed gh commands: run list/view/watch; pr view/list/diff/checks/status; issue view/list; repo view; api GET."
        self.assertEqual(
            self.decision("gh --version && gh pr create --title x --body y", "strict"),
            reason,
        )

    def test_wrapped_nested_shell_priority(self):
        self.check_secret(
            (
                'distrobox enter dev -- bash -lc \'eval "$(vault-env)" >/dev/null 2>&1; gh issue create -R sh4i-yurei/.github --title "Tech debt from the default-templates review" --body-file /tmp/td-dg.md\'',
            )
        )
        for agent in ("claude", "strict"):
            command = "distrobox enter dev -- bash -lc 'vault-run --env GH_TOKEN -- gh issue create -R sh4i-yurei/.github --title \"Tech debt from the default-templates review\" --body-file /tmp/td-dg.md'"
            with self.subTest(agent=agent, command=command):
                self.assertEqual(self.decision(command, agent), ISSUE)


class VaultGuardInProcessTests(VaultGuardTests):
    decision = staticmethod(in_process_decision)

    def test_config_repository_push_policy(self):
        refusal = "Pushing to main or an unknown branch is refused in this repository."
        with tempfile.TemporaryDirectory() as root:
            repositories = {}
            for name in ("claude-config", "codex-config", "second-brain"):
                path = Path(root) / name
                subprocess.run(
                    ["git", "init", "-q", "--initial-branch=main", str(path)],
                    check=True,
                )
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(path),
                        "remote",
                        "add",
                        "origin",
                        f"https://github.com/sh4i-yurei/{name}.git",
                    ],
                    check=True,
                )
                repositories[name] = str(path)

            cases = (
                ("claude-config", "claude", "git push -q origin main", refusal),
                ("codex-config", "claude", "git push -q origin main", refusal),
                ("claude-config", "claude", "git push", refusal),
                ("second-brain", "claude", "git push -q origin main", None),
                (
                    "claude-config",
                    "claude",
                    "git push -u origin fix/guard-config-direct-push",
                    None,
                ),
                (
                    "second-brain",
                    "strict",
                    "git push -q origin main",
                    "Name the branch: git push [-u] origin <branch> or <source>:<destination>.",
                ),
            )
            for name, agent, command, expected in cases:
                with self.subTest(repository=name, agent=agent, command=command):
                    self.assertEqual(
                        in_process_decision(command, agent, repositories[name]),
                        expected,
                    )

            codex_config = repositories["codex-config"]
            subprocess.run(
                ["git", "-C", codex_config, "symbolic-ref", "HEAD", "refs/heads/fix/x"],
                check=True,
            )
            self.assertEqual(
                in_process_decision(
                    "git push origin HEAD:main", "claude", codex_config
                ),
                refusal,
            )

    def test_wrappers_reach_the_command(self):
        prefixes = (
            "distrobox enter --",
            "distrobox enter dev --",
            "distrobox enter -n dev --",
            "distrobox enter --name dev --",
            "distrobox enter -a x --",
            "distrobox enter --additional-flags x --",
            "distrobox enter -n -- --",
            "distrobox enter --name -- --",
            "distrobox enter -a -- --",
            "distrobox enter --additional-flags -- --",
            "env --",
            "env -u X",
            "env --unset X",
            "env -C /tmp",
            "env --chdir /tmp",
            "env -a x",
            "env --argv0 x",
            "env -i",
            "env --ignore-environment",
            "env -",
            "env --unset=X",
            "env --chdir=/tmp",
            "env --argv0=x",
            "env X=1",
            "sudo --",
            "sudo -u root",
            "sudo -g root",
            "sudo -h host",
            "sudo -p prompt",
            "sudo -D /tmp",
            "sudo -n",
            "timeout 5",
            "timeout -s TERM 5",
            "timeout --signal TERM 5",
            "timeout -k 1 5",
            "timeout --kill-after 1 5",
            "timeout --foreground 5",
            "timeout --signal=TERM 5",
            "timeout --kill-after=1 5",
            "command --",
            "command",
            "command -p",
            "command -v",
            "command -V",
            "flatpak-spawn --host",
            "flatpak-spawn",
            "xargs -n 1",
            "xargs -P 1",
            "xargs -I x",
            "xargs -L 1",
            "xargs -s 10",
            "xargs -d x",
            "xargs -a file",
            "xargs -r",
            "nohup",
            "exec",
        )
        for agent in ("claude", "strict"):
            for prefix in prefixes:
                command = f"{prefix} bw get item x"
                with self.subTest(agent=agent, command=command):
                    reason = self.decision(command, agent)
                    self.assertEqual(
                        reason,
                        "Secrets stay out of transcripts: bw can read the vault.",
                    )

    def test_vault_run_option_edges(self):
        self.check_allowed(
            (
                "vault-run -h",
                "vault-run --stdin=x -- gh run list",
                "vault-run --env== -- gh run list",
            )
        )
        cases = (
            ("vault-run --", "vault-run has no command."),
            ("vault-run --env GH_TOKEN", "vault-run needs -- before its command."),
            ("vault-run --env -- gh run list", "vault-run options are incomplete."),
            ("vault-run --env= -- gh run list", "vault-run options are incomplete."),
            ("vault-run --stdin= -- gh run list", "vault-run options are incomplete."),
            ("vault-run --stdin x", "vault-run needs -- before its command."),
            ("vault-run --env '' -- gh run list", "vault-run options are incomplete."),
            ("vault-run --frobnicate -- gh run list", "vault-run options are unknown."),
        )
        for agent in ("claude", "strict"):
            for command, detail in cases:
                with self.subTest(agent=agent, command=command):
                    self.assertEqual(self.decision(command, agent), SECRET + detail)

    def test_wrapper_without_command(self):
        commands = (
            "distrobox enter --",
            "distrobox enter dev",
            "env",
            "sudo",
            "timeout 5",
            "timeout",
            "command",
            "flatpak-spawn",
            "xargs",
            "nohup",
            "exec",
        )
        self.check_allowed(commands)
        self.assertIsNone(self.decision("echo enter -- bw get item x", "claude"))
        self.assertIsNone(self.decision("env -X=1 bw get item x", "claude"))
        self.assertIsNone(self.decision("sudo -- -- bw get item x", "claude"))

    def test_nested_shell_inputs(self):
        commands = (
            "bash -c 'bw get item x'",
            "sh -c 'bw get item x'",
            "bash -lc 'bw get item x'",
            "bash -Cc 'bw get item x'",
            "bash <<'EOF'\nbw get item x\nEOF",
            "bash <<'EOF'\necho ready\nbw get item x\nEOF",
            "bash <<< 'bw get item x'",
            "cat <<'EOF' | bash\nbw get item x\nEOF",
            "cat <<'EOF' | bash\necho ready\nbw get item x\nEOF",
        )
        for agent in ("claude", "strict"):
            for command in commands:
                with self.subTest(agent=agent, command=command):
                    self.assertEqual(
                        self.decision(command, agent),
                        "Secrets stay out of transcripts: bw can read the vault.",
                    )
        for command in (
            "bash -c 'gh pr create'",
            "sh -c 'gh pr create'",
            "bash <<'EOF'\ngh pr create\nEOF",
            "bash <<< 'gh pr create'",
            "cat <<'EOF' | bash\ngh pr create\nEOF",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.decision(command, "claude"))
        self.assertEqual(
            self.decision("bash <<'EOF'\nbw get item x\necho ready\nEOF", "claude"),
            "Secrets stay out of transcripts: bw can read the vault.",
        )
        self.assertEqual(
            self.decision("bash <<'EOF'\ngh auth status -t\nEOF", "claude"),
            "Secrets stay out of transcripts: gh auth status can show a token.",
        )
        self.assertEqual(
            self.decision("bash <<'EOF'\nvault-env\nEOF", "claude"),
            "Secrets stay out of transcripts: use vault-run to fetch secrets.",
        )
        self.assertIsNone(self.decision("bash -c", "claude"))
        self.assertIsNone(self.decision("bash < README.md", "claude"))
        self.assertIsNone(
            self.decision("bash <<'vault-env'\necho ready\nvault-env", "claude")
        )
        self.assertIsNone(
            self.decision(
                "bash <<'vault-env marker'\necho ready\nvault-env marker", "claude"
            )
        )

    def test_existing_gh_api_flag_decisions(self):
        restricted = (
            "gh api repos/a/b -f x=y",
            "gh api repos/a/b -F x=y",
            "gh api repos/a/b --raw-field x=y",
            "gh api repos/a/b --field x=y",
            "gh api repos/a/b --input body.json",
            "gh api -X POST repos/a/b",
            "gh api --method POST repos/a/b",
            "gh api --method GET repos/a/b --input body.json",
        )
        for command in restricted:
            with self.subTest(command=command):
                self.assertEqual(
                    self.decision(command, "strict"),
                    "Allowed gh commands: run list/view/watch; pr view/list/diff/checks/status; "
                    "issue view/list; repo view; api GET.",
                )
        for command in (
            "gh api repos/a/b",
            "gh api -X GET repos/a/b",
            "gh api --method GET repos/a/b",
            "gh api --paginate repos/a/b",
            "gh api -i repos/a/b",
            "gh api --paginate --method GET repos/a/b",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.decision(command, "claude"))
                self.assertIsNone(self.decision(command, "strict"))
        self.assertIsNone(
            self.decision("gh api --method GET repos/a/b -f x=y", "strict")
        )

    def test_existing_gh_merge_reason(self):
        for agent in ("claude", "strict"):
            self.assertEqual(
                self.decision("gh pr merge 12", agent), "gh pr merge is refused."
            )

    def test_gh_option_terminator(self):
        self.assertIsNone(self.decision("gh auth status -- -t", "claude"))
        self.assertEqual(
            self.decision("gh auth status -- -t", "strict"),
            "Allowed gh commands: run list/view/watch; pr view/list/diff/checks/status; "
            "issue view/list; repo view; api GET.",
        )
        self.assertIsNone(self.decision("gh api -- -f x=y", "strict"))
        self.assertIsNone(self.decision("gh api -- -X POST repos/a/b", "strict"))
        for command in ("gh -- auth token", "gh auth -- token"):
            with self.subTest(command=command):
                self.assertEqual(
                    self.decision(command, "claude"),
                    "Secrets stay out of transcripts: gh auth token prints a token.",
                )
        self.assertEqual(self.decision("gh issue -- create", "claude"), ISSUE)
        self.assertEqual(
            self.decision("gh - auth token", "claude"),
            "The guard can't judge this gh command: it doesn't know the command -.",
        )
        self.assertEqual(
            self.decision("gh auth status --show-token=garbage", "claude"),
            "The guard can't judge this gh command: it doesn't know the flag --show-token.",
        )
        self.assertIsNone(self.decision("gh auth x token", "claude"))
        self.assertEqual(
            self.decision("gh auth status --show-token=false", "claude"),
            "Secrets stay out of transcripts: gh auth status can show a token.",
        )

    def test_cd_changes_branch_context(self):
        with tempfile.TemporaryDirectory(dir=HOOK.parent.parent) as root:
            feature = Path(root) / "feature"
            main = Path(root) / "main"
            for path, branch in ((feature, "feature/test"), (main, "main")):
                subprocess.run(
                    ["git", "init", "-q", "--initial-branch=main", str(path)],
                    check=True,
                )
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(path),
                        "symbolic-ref",
                        "HEAD",
                        "refs/heads/" + branch,
                    ],
                    check=True,
                )
            for command in (
                "cd ../main; git merge x",
                f"cd {main}; git merge x",
            ):
                with self.subTest(command=command):
                    self.assertEqual(
                        in_process_decision(command, "claude", str(feature)),
                        "git merge and git pull are refused on main, master, or an unknown branch, except a fast-forward to the branch's own upstream with --ff-only.",
                    )
            self.assertIsNone(
                in_process_decision("cd ../feature; git merge x", "claude", str(main))
            )
            self.assertIsNone(
                in_process_decision("bash -c 'git merge x'", "claude", str(feature))
            )
            self.assertIsNone(
                in_process_decision(
                    "bash <<'EOF'\ngit merge x\nEOF", "claude", str(feature)
                )
            )
            self.assertIsNone(
                in_process_decision(
                    "cat <<'EOF' | bash\ngit merge x\nEOF", "claude", str(feature)
                )
            )
            self.assertIsNone(
                in_process_decision("bash <<< 'git merge x'", "claude", str(feature))
            )

    def test_main_merge_and_pull_require_own_upstream_fast_forward(self):
        refused = (
            "git merge and git pull are refused on main, master, or an unknown "
            "branch, except a fast-forward to the branch's own upstream with --ff-only."
        )
        environment = {key: os.environ[key] for key in ("PATH", "HOME")}
        environment.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
        with tempfile.TemporaryDirectory(dir=HOOK.parent.parent) as root:
            paths = {
                name: Path(root) / name.lower()
                for name in (
                    "TRACKED",
                    "OTHER",
                    "UNTRACKED",
                    "FEATURE",
                    "CLASH_BRANCH",
                    "CLASH_TAG",
                )
            }

            def git(path, *args):
                subprocess.run(
                    ["git", "-C", str(path), *args],
                    check=True,
                    env=environment,
                    capture_output=True,
                    text=True,
                )

            for name, path in paths.items():
                subprocess.run(
                    ["git", "init", "-q", "--initial-branch=main", str(path)],
                    check=True,
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                git(
                    path,
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/example/keepbreathing-infra.git",
                )
                git(
                    path,
                    "-c",
                    "user.name=test",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    "base",
                )
                if name != "UNTRACKED":
                    upstream = "other" if name == "OTHER" else "main"
                    git(path, "update-ref", "refs/remotes/origin/" + upstream, "HEAD")
                    git(path, "branch", "-q", "--set-upstream-to=origin/" + upstream)
                if name == "FEATURE":
                    git(path, "switch", "-q", "-c", "feature/test")
                if name == "CLASH_BRANCH":
                    git(path, "branch", "-q", "origin/main", "HEAD")
                if name == "CLASH_TAG":
                    git(path, "tag", "origin/main", "HEAD")

            allowed = [
                ("TRACKED", "git merge --ff-only", "claude"),
                ("TRACKED", "git merge --ff-only", "codex"),
                ("TRACKED", "git merge -q --ff-only origin/main", "claude"),
                ("TRACKED", "git merge --ff-only @{u}", "claude"),
                ("TRACKED", "git merge --ff-only @{upstream}", "claude"),
                ("TRACKED", "git pull --ff-only", "claude"),
                ("TRACKED", "git pull --ff-only", "codex"),
                ("TRACKED", "git pull -q --ff-only origin main", "claude"),
                ("TRACKED", "git pull --quiet --ff-only", "claude"),
                ("TRACKED", "git pull -v --ff-only", "claude"),
                ("TRACKED", "git pull --verbose --ff-only", "claude"),
                ("TRACKED", "git pull --stat --ff-only", "claude"),
                ("TRACKED", "git pull -n --ff-only", "claude"),
                ("TRACKED", "git pull --no-stat --ff-only", "claude"),
                ("FEATURE", f"git -C {paths['TRACKED']} pull --ff-only", "claude"),
                (
                    "FEATURE",
                    f"git --git-dir={paths['TRACKED'] / '.git'} "
                    f"--work-tree={paths['TRACKED']} pull --ff-only",
                    "claude",
                ),
                ("FEATURE", "git pull", "claude"),
                ("FEATURE", "git pull --rebase origin main", "claude"),
                ("FEATURE", "git merge x", "claude"),
                ("FEATURE", "git -c core.pager=cat pull", "claude"),
                ("FEATURE", "git -c core.pager=cat merge x", "claude"),
            ]
            for name, command, agent in allowed:
                with self.subTest(name=name, command=command, agent=agent):
                    self.assertIsNone(
                        in_process_decision(command, agent, str(paths[name]))
                    )

            denied = [
                ("TRACKED", "git merge origin/main"),
                ("TRACKED", "git pull"),
                ("TRACKED", "git pull --rebase --ff-only"),
                ("TRACKED", "git pull --ff-only --autostash"),
                ("TRACKED", "git pull --ff-only origin feature/x"),
                ("TRACKED", "git pull --ff-only upstream main"),
                ("TRACKED", "git merge --ff-only feature/x"),
                ("TRACKED", "git merge --ff-only origin/main feature/x"),
                ("TRACKED", "bash -lc 'git pull --ff-only origin feature/x'"),
                (
                    "FEATURE",
                    f"git --git-dir={paths['TRACKED'] / '.git'} "
                    f"--work-tree={paths['TRACKED']} pull",
                ),
                ("OTHER", "git pull --ff-only"),
                ("OTHER", "git merge --ff-only origin/other"),
                ("UNTRACKED", "git pull --ff-only"),
                ("UNTRACKED", "git merge --ff-only"),
                (
                    "TRACKED",
                    "git -c branch.main.merge=refs/heads/feature/x merge --ff-only",
                ),
                (
                    "TRACKED",
                    "git -c remote.origin.url=https://github.com/example/other.git pull --ff-only",
                ),
                (
                    "TRACKED",
                    "git --config-env branch.main.merge=GUARD_TEST_MERGE merge --ff-only",
                ),
                (
                    "TRACKED",
                    "git --config-env=branch.main.merge=GUARD_TEST_MERGE pull --ff-only",
                ),
                ("CLASH_BRANCH", "git merge --ff-only origin/main"),
                ("CLASH_BRANCH", "git merge --ff-only"),
                ("CLASH_TAG", "git merge --ff-only origin/main"),
                ("CLASH_TAG", "git merge --ff-only"),
            ]
            for name, command in denied:
                with self.subTest(name=name, command=command):
                    self.assertEqual(
                        in_process_decision(command, "claude", str(paths[name])),
                        refused,
                    )
            self.assertEqual(
                in_process_decision(
                    "git --frobnicate pull --ff-only", "claude", str(paths["TRACKED"])
                ),
                "Unknown git global option for pull: --frobnicate",
            )
            for action in ("merge", "push"):
                with self.subTest(action=action):
                    self.assertEqual(
                        in_process_decision(
                            "git --frobnicate " + action,
                            "claude",
                            str(paths["TRACKED"]),
                        ),
                        "Unknown git global option for " + action + ": --frobnicate",
                    )

    def test_existing_fixture_decisions(self):
        cases = json.loads(
            HOOK.parent.parent.joinpath("tests/git_guard_commands.json").read_text()
        )
        with tempfile.TemporaryDirectory(dir=HOOK.parent.parent) as root:
            paths = {name: Path(root) / name for name in ("feature", "main")}
            for name, path in paths.items():
                subprocess.run(
                    ["git", "init", "-q", "--initial-branch=main", str(path)],
                    check=True,
                )
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(path),
                        "remote",
                        "add",
                        "origin",
                        "https://github.com/example/keepbreathing-infra.git",
                    ],
                    check=True,
                )
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(path),
                        "symbolic-ref",
                        "HEAD",
                        "refs/heads/"
                        + ("feature/test" if name == "feature" else "main"),
                    ],
                    check=True,
                )
            paths["config"] = HOOK.parent.parent
            for case in cases:
                command = case["command"].replace(
                    "~/Documents/worktrees/claude-config-3.1", str(paths["feature"])
                )
                for agent in ("claude", "codex", "other"):
                    if agent not in case:
                        continue
                    with self.subTest(case=case["name"], agent=agent):
                        reason = in_process_decision(
                            command, agent, str(paths[case["cwd"]])
                        )
                        self.assertEqual("deny" if reason else "allow", case[agent])
                        if reason and case.get("reason"):
                            label = case["reason"]
                            if label == "issue tool":
                                expected = ISSUE
                            elif label == "attribution":
                                expected = ATTRIBUTION
                            elif label == "commit parse":
                                self.assertTrue(
                                    reason.startswith(
                                        "The guard can't judge this git commit: "
                                    ),
                                    reason,
                                )
                                continue
                            elif label == "commit parse bogus":
                                expected = "The guard can't judge this git commit: error: unknown option `bogus'"
                            elif label == "parse fallback":
                                self.assertTrue(
                                    reason.startswith(
                                        "Cannot parse a command mentioning git, gh, bw, vault-env or vault-commit: "
                                    ),
                                    reason,
                                )
                                continue
                            elif label.startswith("message file "):
                                expected = (
                                    "The guard can't read the commit message file "
                                    + label.removeprefix("message file ")
                                    + "."
                                )
                            elif label == "strict rules":
                                expected = (
                                    "Allowed gh commands: run list/view/watch; pr view/list/diff/checks/status; "
                                    "issue view/list; repo view; api GET."
                                )
                            elif label == "queue tags":
                                expected = "Every queue task carries a project: tag and an item: tag, so it can be found by project and item (OpenRig team decision 16)."
                            elif label.startswith("unknown rig option "):
                                word = label.removeprefix("unknown rig option ")
                                expected = f"The guard can't judge this rig command: it doesn't know the option {word}."
                            elif label.startswith("rig option without value "):
                                word = label.removeprefix("rig option without value ")
                                expected = f"The guard can't judge this rig command: the option {word} has no value."
                            elif label.startswith("unknown rtk option "):
                                word = label.removeprefix("unknown rtk option ")
                                expected = f"The guard can't judge this rtk command: it doesn't know the option {word}."
                            elif label.startswith("rtk option without value "):
                                word = label.removeprefix("rtk option without value ")
                                expected = f"The guard can't judge this rtk command: the option {word} has no value."
                            elif label.startswith("rtk shell "):
                                shell = label.removeprefix("rtk shell ")
                                expected = f"The guard can't judge this rtk command: it can't read a {shell} script."
                            elif label.startswith("rtk split "):
                                word = label.removeprefix("rtk split ")
                                expected = f"The guard can't judge this rtk command: it can't split the word {word}."
                            elif label.startswith("rtk pipeline "):
                                word = label.removeprefix("rtk pipeline ")
                                expected = f"The guard can't judge rtk pipeline {word}: it runs gh with arguments that aren't on the command line."
                            elif label.startswith("unknown gh command "):
                                word = label.removeprefix("unknown gh command ")
                                expected = f"The guard can't judge this gh command: it doesn't know the command {word}."
                            elif label.startswith("unknown sudo option "):
                                word = label.removeprefix("unknown sudo option ")
                                expected = f"The guard can't judge this sudo command: it doesn't know the option {word}."
                            elif label.startswith("sudo option without value "):
                                word = label.removeprefix("sudo option without value ")
                                expected = f"The guard can't judge this sudo command: the option {word} has no value."
                            else:
                                flag = label.removeprefix("unknown gh flag ")
                                expected = f"The guard can't judge this gh command: it doesn't know the flag {flag}."
                            self.assertEqual(reason, expected)

    def test_commit_message_file_in_feature_repository(self):
        with tempfile.TemporaryDirectory(dir=HOOK.parent.parent) as root:
            feature = Path(root) / "feature"
            subprocess.run(
                ["git", "init", "-q", "-b", "feature/test", str(feature)], check=True
            )
            message_file = feature / "msg.txt"
            for content, expected in (
                ("Fix the merge\n\nGenerated with Claude Code\n", ATTRIBUTION),
                ("Fix the merge\n", None),
            ):
                message_file.write_text(content)
                for agent in ("claude", "codex"):
                    with self.subTest(content=content, agent=agent):
                        self.assertEqual(
                            in_process_decision(
                                "git commit -F msg.txt", agent, str(feature)
                            ),
                            expected,
                        )
            pipe = feature / "message.pipe"
            os.mkfifo(pipe)
            for agent in ("claude", "codex"):
                with self.subTest(file="pipe", agent=agent):
                    started = time.monotonic()
                    self.assertEqual(
                        in_process_decision(
                            "git commit -F message.pipe", agent, str(feature)
                        ),
                        "The guard can't read the commit message file message.pipe.",
                    )
                    self.assertLess(time.monotonic() - started, 0.5)

    def test_commit_clean_message_file_boundaries(self):
        with tempfile.TemporaryDirectory(dir=HOOK.parent.parent) as root:
            feature = Path(root) / "feature"
            subprocess.run(
                ["git", "init", "-q", "-b", "feature/test", str(feature)], check=True
            )
            for name, content in (
                ("million.txt", b"a" * 1_048_576),
                ("invalid.txt", b"Fix \xff"),
                ("a=b.txt", b"Fix"),
            ):
                (feature / name).write_bytes(content)
                for agent in ("claude", "codex"):
                    with self.subTest(name=name, agent=agent):
                        self.assertIsNone(
                            in_process_decision(
                                f"git commit -F {name}", agent, str(feature)
                            )
                        )

    def test_commit_option_parser_silent_failure_denies(self):
        with tempfile.TemporaryDirectory(dir=HOOK.parent.parent) as root:
            feature = Path(root) / "feature"
            subprocess.run(
                ["git", "init", "-q", "-b", "feature/test", str(feature)], check=True
            )
            fake_bin = Path(root) / "bin"
            fake_bin.mkdir()
            git = shutil.which("git")
            wrapper = fake_bin / "git"
            wrapper.write_text(
                "#!/bin/sh\n"
                'for arg do [ "$arg" = --parseopt ] && exit 1; done\n'
                f'exec "{git}" "$@"\n'
            )
            wrapper.chmod(0o755)
            with patch.dict(
                os.environ, {"PATH": str(fake_bin) + os.pathsep + os.environ["PATH"]}
            ):
                for agent in ("claude", "codex"):
                    with self.subTest(agent=agent):
                        self.assertEqual(
                            in_process_decision(
                                "git commit -m Fix", agent, str(feature)
                            ),
                            "The guard can't judge this git commit: Git rejected the arguments.",
                        )

    def test_commit_option_parser_help_on_success_allows(self):
        with tempfile.TemporaryDirectory(dir=HOOK.parent.parent) as root:
            feature = Path(root) / "feature"
            subprocess.run(
                ["git", "init", "-q", "-b", "feature/test", str(feature)], check=True
            )
            fake_bin = Path(root) / "bin"
            fake_bin.mkdir()
            git = shutil.which("git")
            wrapper = fake_bin / "git"
            wrapper.write_text(
                "#!/bin/sh\n"
                'for arg do if [ "$arg" = --parseopt ]; then\n'
                "    printf '%s\\n' 'cat <<\\EOF' 'usage: git commit' "
                '"    -m, --message <message>  the commit\x27s message" EOF\n'
                "    exit 0\n"
                "fi; done\n"
                f'exec "{git}" "$@"\n'
            )
            wrapper.chmod(0o755)
            with patch.dict(
                os.environ, {"PATH": str(fake_bin) + os.pathsep + os.environ["PATH"]}
            ):
                for agent in ("claude", "codex"):
                    with self.subTest(agent=agent):
                        self.assertIsNone(
                            in_process_decision("git commit -h", agent, str(feature))
                        )

    def test_commit_in_missing_directory_denies(self):
        with tempfile.TemporaryDirectory(dir=HOOK.parent.parent) as root:
            feature = Path(root) / "feature"
            subprocess.run(
                ["git", "init", "-q", "-b", "feature/test", str(feature)], check=True
            )
            event = {
                "tool_name": "Bash",
                "cwd": str(feature),
                "tool_input": {"command": "git -C does-not-exist-56a commit -m Fix"},
            }
            for agent in ("claude", "codex"):
                with self.subTest(agent=agent):
                    output = io.StringIO()
                    argv = ["git-guard.py"]
                    if agent == "claude":
                        argv += ["--agent", "claude"]
                    with patch("sys.stdin", io.StringIO(json.dumps(event))):
                        with patch.object(sys, "argv", argv):
                            with contextlib.redirect_stdout(output):
                                self.assertEqual(GUARD.main(), 0)
                    decision = json.loads(output.getvalue())["hookSpecificOutput"]
                    self.assertEqual(decision["permissionDecision"], "deny")

    def test_commit_option_parser_timeout_denies(self):
        with tempfile.TemporaryDirectory(dir=HOOK.parent.parent) as root:
            feature = Path(root) / "feature"
            subprocess.run(
                ["git", "init", "-q", "-b", "feature/test", str(feature)], check=True
            )
            fake_bin = Path(root) / "bin"
            fake_bin.mkdir()
            git = shutil.which("git")
            wrapper = fake_bin / "git"
            wrapper.write_text(
                "#!/bin/sh\n"
                'for arg do if [ "$arg" = --parseopt ]; then\n'
                "    sleep 3\n"
                "    exit 1\n"
                "fi; done\n"
                f'exec "{git}" "$@"\n'
            )
            wrapper.chmod(0o755)
            event = {
                "tool_name": "Bash",
                "cwd": str(feature),
                "tool_input": {"command": "git commit -m Fix"},
            }
            output = io.StringIO()
            with patch.dict(
                os.environ, {"PATH": str(fake_bin) + os.pathsep + os.environ["PATH"]}
            ):
                with patch("sys.stdin", io.StringIO(json.dumps(event))):
                    with patch.object(sys, "argv", ["git-guard.py"]):
                        with contextlib.redirect_stdout(output):
                            self.assertEqual(GUARD.main(), 0)
            decision = json.loads(output.getvalue())["hookSpecificOutput"]
            self.assertEqual(decision["permissionDecision"], "deny")
            self.assertEqual(
                decision["permissionDecisionReason"],
                "Guard error: TimeoutError: Command was too complex to judge in time.",
            )


if __name__ == "__main__":
    unittest.main()
