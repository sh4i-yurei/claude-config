import json, os, subprocess, sys, tempfile, time
from pathlib import Path

HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "git-guard.py")
D = os.path.expanduser("~/Documents")
TEMP = tempfile.TemporaryDirectory(
    prefix=".guard-tests-", dir=Path(__file__).resolve().parents[1]
)
INFRA, CC = f"{TEMP.name}/feature", str(Path(__file__).resolve().parents[1])
MAIN = f"{TEMP.name}/main"
for directory, branch in ((INFRA, "feature/test"), (MAIN, "main")):
    subprocess.run(
        ["git", "init", "-q", "--initial-branch=main", directory], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            directory,
            "remote",
            "add",
            "origin",
            "https://github.com/example/keepbreathing-infra.git",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", directory, "symbolic-ref", "HEAD", "refs/heads/" + branch],
        check=True,
    )
WRAP = "distrobox enter dev -- bash -lc 'cd " + INFRA + " && {}'"
cases = [
    # (expected, cwd, command, tool_input shape)
    ("allow", INFRA, "git merge feature/x", "claude"),
    (
        "allow",
        INFRA,
        "git -C " + INFRA + " merge --no-ff origin/main",
        "claude",
    ),
    ("allow", D, WRAP.format("git merge origin/main"), "claude"),
    ("allow", INFRA, "git merge-base main HEAD", "claude"),
    ("allow", INFRA, "git mergetool --help", "claude"),
    ("deny", INFRA, "gh pr merge 12 --squash", "claude"),
    (
        "deny",
        D,
        "distrobox enter dev -- bash -lc 'gh pr merge 12 -R sh4i-yurei/keepbreathing-infra --squash'",
        "claude",
    ),
    ("allow", INFRA, "gh pr view 12 --json state", "claude"),
    ("allow", INFRA, "gh pr create --title x --body y", "claude"),
    ("deny", INFRA, "git push --force origin chore/x", "claude"),
    ("deny", INFRA, "git push -f origin chore/x", "claude"),
    ("deny", INFRA, "git push --force-with-lease origin chore/x", "claude"),
    ("deny", INFRA, "git push origin +chore/x", "claude"),
    ("deny", CC, "git push --force origin main", "claude"),
    ("deny", INFRA, "git push origin main", "claude"),
    ("deny", INFRA, "git push origin HEAD:main", "claude"),
    ("deny", INFRA, "git push origin abc123:refs/heads/main", "claude"),
    ("deny", INFRA, "git push --dry-run origin HEAD:main", "claude"),
    ("deny", D, WRAP.format("git push origin main"), "claude"),
    ("allow", INFRA, "git push -u origin chore/ci-checks", "claude"),
    ("allow", INFRA, "git push origin HEAD:refs/heads/chore/x", "claude"),
    ("allow", CC, "git push origin main", "claude"),
    ("allow", f"{D}/Second_Brain", "git push", "claude"),
    ("allow", INFRA, "git status && git log --oneline -3", "claude"),
    ("allow", INFRA, "ls -la", "claude"),
    # Text that mentions the commands without running them must pass.
    (
        "allow",
        INFRA,
        'git commit -m "It refuses git merge, gh pr merge and force pushes"',
        "claude",
    ),
    (
        "allow",
        INFRA,
        "echo 'agents never run gh pr merge or git push --force'",
        "claude",
    ),
    ("allow", INFRA, "grep -n 'git merge' README.md", "claude"),
    (
        "allow",
        INFRA,
        "cat > body.md <<'EOF'\nThe hook refuses `git merge` and `gh pr merge`.\nEOF",
        "claude",
    ),
    # Prefixes that still put the command in command position.
    ("allow", INFRA, "sudo git merge x", "claude"),
    (
        "deny",
        D,
        "distrobox enter dev -- git -C " + MAIN + " push origin main",
        "claude",
    ),
    ("allow", INFRA, "git status; git merge x", "claude"),
    ("allow", INFRA, "(git merge x)", "claude"),
    ("allow", INFRA, ["bash", "-lc", "git merge origin/main"], "codex"),
    ("deny", INFRA, ["bash", "-lc", "git push origin main"], "codex"),
    ("allow", INFRA, ["bash", "-lc", "git push origin feature/y"], "codex"),
]

# W1 cases cover the strict default, parser boundaries, and real shell wrappers.
cases += [
    ("deny", MAIN, "git merge -q --ff-only origin/main", "claude"),
    ("deny", MAIN, "git merge -q --ff-only origin/main", "codex"),
    (
        "deny",
        INFRA,
        "env X=1 sudo timeout 10 command nohup git push origin main",
        "codex",
    ),
    ("deny", INFRA, "sh -c 'git push origin main'", "codex"),
    ("deny", INFRA, "bash -lc 'git push origin main'", "codex"),
    ("deny", INFRA, "distrobox enter dev -- bash -lc 'git push origin main'", "codex"),
    ("deny", INFRA, "echo $(git push origin main)", "codex"),
    ("deny", INFRA, "echo `git push origin main`", "codex"),
    ("deny", INFRA, "g''it push origin main", "codex"),
    ("allow", INFRA, "cat <<'EOF'\ngit push origin main\nEOF\n", "codex"),
    ("deny", INFRA, "bash <<'EOF'\ngit push origin main\nEOF\n", "codex"),
    ("allow", INFRA, "cat <<EOF\ngit push origin main\nEOF\n", "codex"),
    ("allow", INFRA, "python3 -c \"print('git merge')\"", "codex"),
    ("allow", INFRA, "grep -n 'gh pr merge' notes.md", "codex"),
    ("allow", INFRA, 'git commit -m "refuses git merge"', "codex"),
    ("deny", INFRA, "git push origin main && (", "codex"),
    ("deny", INFRA, "g''it push origin main && (", "codex"),
    ("allow", INFRA, "echo hello && (", "codex"),
    ("deny", INFRA, "git push", "codex"),
    ("deny", INFRA, "git push origin HEAD", "codex"),
    ("deny", INFRA, "git push origin x y", "codex"),
    ("deny", INFRA, "git push --all origin", "codex"),
    ("deny", INFRA, "git push --mirror origin", "codex"),
    ("deny", INFRA, "git push --tags origin", "codex"),
    ("deny", INFRA, "git push --force-if-includes origin feature/x", "codex"),
    ("allow", INFRA, "git push -u origin feature/x", "codex"),
    ("allow", INFRA, "git push origin HEAD:feature/x", "codex"),
    ("allow", CC, "git push -q origin main", "claude"),
    ("deny", CC, "git push -q origin main", "codex"),
    ("deny", CC, "git push -q origin main", "other"),
    ("deny", INFRA, "gh run rerun 1", "codex"),
    ("allow", INFRA, "gh run list", "codex"),
    ("allow", INFRA, "gh run view 1 --log-failed", "codex"),
    ("allow", INFRA, "gh run watch 1 --exit-status", "codex"),
    ("allow", INFRA, "gh pr view 1", "codex"),
    ("allow", INFRA, "gh pr list", "codex"),
    ("allow", INFRA, "gh pr diff 1", "codex"),
    ("allow", INFRA, "gh pr checks 1", "codex"),
    ("allow", INFRA, "gh pr status", "codex"),
    ("allow", INFRA, "gh issue view 1", "codex"),
    ("allow", INFRA, "gh issue list", "codex"),
    ("allow", INFRA, "gh repo view", "codex"),
    ("allow", INFRA, "gh api repos/a/b", "codex"),
    ("allow", INFRA, "gh api -X GET search/issues -f q=test", "codex"),
    ("allow", INFRA, "gh api --method GET repos/a/b --field q=x", "codex"),
    ("deny", INFRA, "gh api -X POST repos/a/b", "codex"),
    ("deny", INFRA, "gh api repos/a/b -f x=y", "codex"),
    ("deny", INFRA, "gh api --input x.json repos/a/b", "codex"),
    ("deny", INFRA, "gh pr create", "codex"),
    ("deny", INFRA, "gh issue create", "codex"),
    ("deny", INFRA, "git push origin refs/heads/main", "codex"),
    ("deny", INFRA, "git push origin HEAD:refs/heads/main", "codex"),
    ("deny", MAIN, "git push origin HEAD", "claude"),
    ("deny", MAIN, "git push origin @", "claude"),
    ("deny", MAIN, "git push -o ci.skip origin HEAD", "claude"),
    ("deny", MAIN, "git push --repo origin HEAD", "claude"),
    ("deny", MAIN, "git push --receive-pack helper origin HEAD", "claude"),
    ("deny", INFRA, "bash --norc -c 'git push --force origin x'", "claude"),
    (
        "deny",
        INFRA,
        "bash --rcfile /dev/null -lc 'git push --force origin x'",
        "claude",
    ),
    ("deny", INFRA, "env -i git push --force origin x", "claude"),
    ("deny", INFRA, "env -u X git push --force origin x", "claude"),
    ("deny", INFRA, "timeout -s KILL -k 1 5 git push --force origin x", "claude"),
    ("deny", INFRA, "command -p git push --force origin x", "claude"),
    ("deny", INFRA, "distrobox enter -n dev -- git push --force origin x", "claude"),
    (
        "deny",
        INFRA,
        "distrobox enter --name dev -- git push --force origin x",
        "claude",
    ),
    ("deny", INFRA, "ls | xargs git push --force origin x", "claude"),
    ("deny", INFRA, "cat <<'EOF' | bash\ngit push --force origin x\nEOF\n", "claude"),
    ("deny", INFRA, "for x in $(git push --force origin x); do :; done", "claude"),
    ("deny", INFRA, "case $(git push --force origin x) in x) :;; esac", "claude"),
    ("deny", INFRA, "echo x > $(git push --force origin x)", "claude"),
    ("deny", INFRA, "g``it push --force origin x && (", "claude"),
    ("deny", INFRA, "git push origin :feature/x", "codex"),
    ("allow", INFRA, "git push --tags", "claude"),
    ("allow", MAIN, "git push --tags", "claude"),
    ("allow", INFRA, "git -P log", "claude"),
    ("allow", INFRA, "git --no-optional-locks status", "claude"),
    ("allow", INFRA, "git --git-dir=.git status", "claude"),
    ("deny", INFRA, "git --git-dir=" + MAIN + "/.git merge x", "claude"),
    (
        "deny",
        INFRA,
        "git --work-tree=" + MAIN + " --git-dir=" + MAIN + "/.git merge x",
        "claude",
    ),
    ("allow", INFRA, "git --mystery-option log", "codex"),
    ("deny", INFRA, "git --mystery-option push origin feature/x", "codex"),
]
for item in json.loads(Path(__file__).with_name("git_guard_commands.json").read_text()):
    for agent in ("claude", "codex"):
        cwd = {"feature": INFRA, "main": MAIN, "config": CC}[item["cwd"]]
        command = item["command"].replace(
            "~/Documents/worktrees/claude-config-3.1", INFRA
        )
        cases.append((item[agent], cwd, command, agent))

fails = 0
for want, cwd, cmd, who in cases:
    event = {
        "hook_event_name": "PreToolUse",
        "cwd": cwd,
        "tool_name": "Bash",
        "tool_input": {"command": cmd},
    }
    run = subprocess.run(
        [sys.executable, HOOK]
        + (["--agent", who] if who in ("claude", "other") else []),
        input=json.dumps(event),
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0 and not run.stderr, (cmd, run.returncode, run.stderr)
    out = run.stdout
    got = (
        "deny"
        if out and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
        else "allow"
    )
    ok = got == want
    fails += not ok
    shown = cmd if isinstance(cmd, str) else " ".join(cmd)
    print(
        f"{'ok  ' if ok else 'FAIL'} {want:5} {os.path.basename(cwd):20} {shown[:90]}"
    )
# Failures in the hook must be valid deny decisions, including an import failure.
for raw in ("{}", "[]", "not-json", json.dumps({"cwd": INFRA, "tool_input": {}})):
    run = subprocess.run(
        ["/usr/bin/python3", HOOK], input=raw, capture_output=True, text=True
    )
    assert run.returncode == 0 and not run.stderr, (run.returncode, run.stderr)
    decision = json.loads(run.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny", decision
    assert "error" in decision["permissionDecisionReason"].lower(), decision

# Codex maps exec_command to Bash and apply_patch to apply_patch. Both inputs
# use command, while the envelope carries the same documented event fields.
dangerous = "g" + "it push --for" + "ce origin feature/x"
codex_envelope = {
    "session_id": "test-session",
    "turn_id": "test-turn",
    "transcript_path": None,
    "cwd": INFRA,
    "hook_event_name": "PreToolUse",
    "model": "test-model",
    "permission_mode": "never",
    "tool_use_id": "test-tool-use",
}
codex_events = [
    (
        "allow",
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "cwd": INFRA,
            "tool_input": {
                "command": '*** Begin Patch\n*** Update File: README.md\n@@\n+print("'
                + dangerous
                + '")\n*** End Patch'
            },
        },
    ),
    (
        "deny",
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "cwd": INFRA,
            "tool_input": {"command": dangerous},
        },
    ),
]
for expected, event in codex_events:
    event = {**codex_envelope, **event}
    run = subprocess.run(
        ["/usr/bin/python3", HOOK],
        input=json.dumps(event),
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0 and not run.stderr, run
    actual = "deny" if run.stdout else "allow"
    assert actual == expected, (event["tool_name"], expected, run.stdout)

with tempfile.TemporaryDirectory(
    prefix=".guard-no-vendor-", dir=Path(__file__).resolve().parents[1]
) as empty:
    copy = Path(empty) / "nested" / "guard.py"
    copy.parent.mkdir()
    copy.write_text(Path(HOOK).read_text())
    run = subprocess.run(
        ["/usr/bin/python3", str(copy)],
        input=json.dumps(
            {
                "tool_name": "Bash",
                "cwd": INFRA,
                "tool_input": {"command": "git push origin main"},
            }
        ),
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0 and not run.stderr, (run.returncode, run.stderr)
    decision = json.loads(run.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny", decision
    assert "error" in decision["permissionDecisionReason"].lower(), decision

command = "echo '" + "x" * 51200 + "'"
event = {"tool_name": "Bash", "cwd": INFRA, "tool_input": {"command": command}}
start = time.monotonic()
run = subprocess.run(
    ["/usr/bin/python3", HOOK], input=json.dumps(event), capture_output=True, text=True
)
assert run.returncode == 0 and run.stdout == "" and not run.stderr, run
assert time.monotonic() - start < 2, "50 KB command exceeded two seconds"

command = "git merge x; " * 3900
event = {"tool_name": "Bash", "cwd": INFRA, "tool_input": {"command": command}}
start = time.monotonic()
run = subprocess.run(
    ["/usr/bin/python3", HOOK], input=json.dumps(event), capture_output=True, text=True
)
assert run.returncode == 0 and run.stdout == "" and not run.stderr, run
assert time.monotonic() - start < 2, "git-heavy 50 KB command exceeded two seconds"

for cmd, phrase in (
    ("git push", "Name the branch"),
    ("gh run rerun 1", "Allowed gh commands"),
):
    event = {"tool_name": "Bash", "cwd": INFRA, "tool_input": {"command": cmd}}
    run = subprocess.run(
        ["/usr/bin/python3", HOOK],
        input=json.dumps(event),
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0 and not run.stderr
    decision = json.loads(run.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny", decision
    assert phrase in decision["permissionDecisionReason"], decision

print(f"\n{len(cases) - fails}/{len(cases)} passed")
assert fails == 0, f"{fails} behavior assertions failed"
