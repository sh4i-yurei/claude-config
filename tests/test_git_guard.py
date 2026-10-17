import json, os, subprocess, sys

HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "git-guard.py")
D = os.path.expanduser("~/Documents")
INFRA, CC = f"{D}/keepbreathing-infra", f"{D}/claude-config"
WRAP = "distrobox enter dev -- bash -lc 'cd ~/Documents/keepbreathing-infra && {}'"
cases = [
    # (expected, cwd, command, tool_input shape)
    ("deny", INFRA, "git merge feature/x", "claude"),
    (
        "deny",
        INFRA,
        "git -C ~/Documents/keepbreathing-infra merge --no-ff origin/main",
        "claude",
    ),
    ("deny", D, WRAP.format("git merge origin/main"), "claude"),
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
    # Prefixes that still put the command in command position.
    ("deny", INFRA, "sudo git merge x", "claude"),
    (
        "deny",
        D,
        "distrobox enter dev -- git -C ~/Documents/keepbreathing-infra push origin main",
        "claude",
    ),
    ("deny", INFRA, "git status; git merge x", "claude"),
    ("deny", INFRA, "(git merge x)", "claude"),
    ("deny", INFRA, ["bash", "-lc", "git merge origin/main"], "codex"),
    ("deny", INFRA, ["bash", "-lc", "git push origin main"], "codex"),
    ("allow", INFRA, ["bash", "-lc", "git push origin feature/y"], "codex"),
]
fails = 0
for want, cwd, cmd, who in cases:
    event = {
        "hook_event_name": "PreToolUse",
        "cwd": cwd,
        "tool_name": "Bash" if who == "claude" else "shell",
        "tool_input": {"command": cmd},
    }
    out = subprocess.run(
        [sys.executable, HOOK], input=json.dumps(event), capture_output=True, text=True
    ).stdout
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
print(f"\n{len(cases) - fails}/{len(cases)} passed")
sys.exit(1 if fails else 0)
