import importlib.util, json, os, re, subprocess, sys, tempfile, time
from pathlib import Path
import pytest

HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "git-guard.py")


def help_flags(output):
    flags = {}
    for line in output.splitlines():
        if not line.startswith("  "):
            continue
        column = re.split(r"\s{3,}", line.strip(), maxsplit=1)[0]
        if not re.fullmatch(r"(?:-[A-Za-z], )?--[\w-]+(?: \S+)?", column):
            continue
        names = re.findall(r"(?:--[\w-]+|-[A-Za-z])", column)
        for name in names:
            flags[name] = bool(re.search(r"--[\w-]+\s+\S+", column))
    return flags


def reference_nodes(output, root_help):
    local_aliases = set()
    in_aliases = False
    for line in root_help.splitlines():
        if line == "ALIAS COMMANDS":
            in_aliases = True
            continue
        if in_aliases and line and not line.startswith(" "):
            in_aliases = False
        if in_aliases:
            match = re.match(r"  ([\w-]+):", line)
            if match:
                local_aliases.add(match.group(1))
    nodes = {(): {"name": "gh", "aliases": [], "flags": {}, "children": []}}
    paths = {()}
    aliases = set()
    in_aliases = False
    current = ()
    for line in output.splitlines():
        if re.match(r"^#{2,4} gh ", line):
            in_aliases = False
            match = re.match(r"^#{2,4} gh ((?:[a-z][a-z0-9-]*(?: |$))+)", line)
            if match:
                current = tuple(match.group(1).split())
                if current[0] not in local_aliases:
                    paths.add(current)
        elif line == "Aliases":
            in_aliases = True
        elif in_aliases and line.startswith("gh "):
            for alias in line.split(", "):
                words = tuple(alias.removeprefix("gh ").split())
                if words[0] not in local_aliases and current:
                    aliases.add((current, words[-1]))
        elif in_aliases and line and not line.startswith("gh "):
            in_aliases = False
    paths.add(("help",))
    for path in sorted(paths, key=lambda item: (len(item), item)):
        if not path:
            continue
        assert path[:-1] in nodes, ("missing parent", path)
        node = {"name": path[-1], "aliases": [], "flags": {}, "children": []}
        nodes[path] = node
        nodes[path[:-1]]["children"].append(node)
    for path, alias in sorted(aliases):
        if alias != path[-1]:
            nodes[path]["aliases"].append(alias)
    for node in nodes.values():
        node["children"].sort(key=lambda child: child["name"])
    return nodes


D = os.path.expanduser("~/Documents")
TEMP = tempfile.TemporaryDirectory(
    prefix=".guard-tests-", dir=Path(__file__).resolve().parents[1]
)
INFRA, CC = f"{TEMP.name}/feature", str(Path(__file__).resolve().parents[1])
MAIN = f"{TEMP.name}/main"
VAULT = f"{TEMP.name}/vault"
for directory, branch in ((INFRA, "feature/test"), (MAIN, "main"), (VAULT, "main")):
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
subprocess.run(
    [
        "git",
        "-C",
        VAULT,
        "remote",
        "set-url",
        "origin",
        "https://github.com/sh4i-yurei/second-brain.git",
    ],
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
    ("deny", CC, "git push origin main", "claude"),
    ("allow", VAULT, "git push", "claude"),
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
    ("deny", CC, "git push -q origin main", "claude"),
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
issue_tool_reason_cases = []
for item in json.loads(Path(__file__).with_name("git_guard_commands.json").read_text()):
    for agent in ("claude", "codex", "other"):
        if agent not in item:
            continue
        cwd = {"feature": INFRA, "main": MAIN, "config": CC}[item["cwd"]]
        command = item["command"].replace(
            "~/Documents/worktrees/claude-config-3.1", INFRA
        )
        cases.append((item[agent], cwd, command, agent))
        if item.get("reason") and item[agent] == "deny":
            issue_tool_reason_cases.append((cwd, command, agent, item["reason"]))


@pytest.mark.parametrize(("want", "cwd", "cmd", "who"), cases)
def test_guard_decision(want, cwd, cmd, who):
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
    assert got == want, (cwd, cmd, who, run.stdout)


for cwd, cmd, who, reason in issue_tool_reason_cases:
    event = {"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": cmd}}
    run = subprocess.run(
        [sys.executable, HOOK, "--agent", who],
        input=json.dumps(event),
        capture_output=True,
        text=True,
    )
    assert run.stdout, (cmd, "expected an issue-tool refusal")
    decision = json.loads(run.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny", (cmd, decision)
    if reason == "issue tool":
        assert decision["permissionDecisionReason"] == (
            "Use tools/workflow/issue.py open; see README.md, Opening an issue from a file."
        ), (cmd, decision)
    elif reason.startswith("unknown gh flag "):
        flag = reason.removeprefix("unknown gh flag ")
        assert decision["permissionDecisionReason"] == (
            f"The guard can't judge this gh command: it doesn't know the flag {flag}."
        ), (cmd, decision)
    elif reason.startswith("unknown gh command "):
        word = reason.removeprefix("unknown gh command ")
        assert decision["permissionDecisionReason"] == (
            f"The guard can't judge this gh command: it doesn't know the command {word}."
        ), (cmd, decision)
    elif reason == "strict rules":
        assert decision["permissionDecisionReason"] == (
            "Allowed gh commands: run list/view/watch; pr view/list/diff/checks/status; "
            "issue view/list; repo view; api GET."
        ), (cmd, decision)
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

PERFORMANCE_HOOK = (
    str(Path(HOOK).resolve().parents[1].parent / "hooks/git-guard.py")
    if Path(__file__).resolve().parents[1].name == "mutants"
    else HOOK
)
command = "echo '" + "x" * 51200 + "'"
event = {"tool_name": "Bash", "cwd": INFRA, "tool_input": {"command": command}}
start = time.monotonic()
run = subprocess.run(
    ["/usr/bin/python3", PERFORMANCE_HOOK],
    input=json.dumps(event),
    capture_output=True,
    text=True,
)
assert run.returncode == 0 and run.stdout == "" and not run.stderr, run
assert time.monotonic() - start < 2, "50 KB command exceeded two seconds"

command = "git merge x; " * 3900
event = {"tool_name": "Bash", "cwd": INFRA, "tool_input": {"command": command}}
start = time.monotonic()
run = subprocess.run(
    ["/usr/bin/python3", PERFORMANCE_HOOK],
    input=json.dumps(event),
    capture_output=True,
    text=True,
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

spec = importlib.util.spec_from_file_location("git_guard_under_test", HOOK)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
for name, command in {
    "api": ("api",),
    "issue-create": ("issue", "create"),
    "pr-merge": ("pr", "merge"),
}.items():
    fixture = Path(__file__).with_name("fixtures") / "gh-help-2.97.0" / (name + ".txt")
    expected = help_flags(fixture.read_text())
    actual_help = subprocess.run(
        ["gh", *command, "--help"], check=True, capture_output=True, text=True
    )
    actual = help_flags(actual_help.stdout)
    for flag in sorted(expected.keys() | actual.keys()):
        assert expected.get(flag) == actual.get(flag), (
            name,
            flag,
            expected.get(flag),
            actual.get(flag),
        )
    table = guard.GH_FLAG_TABLES.get(name)
    assert table is not None, (name, "missing gh flag table")
    for flag in sorted(expected.keys() | table.keys()):
        assert expected.get(flag) == table.get(flag), (
            name,
            flag,
            expected.get(flag),
            table.get(flag),
        )

fixture_root = Path(__file__).with_name("fixtures") / "gh-help-2.97.0"
tree = json.loads((Path(HOOK).with_name("gh-command-tree-2.97.0.json")).read_text())
reference = (fixture_root / "reference.txt").read_text()
root_help = (fixture_root / "root.txt").read_text()
live_reference = subprocess.run(
    ["gh", "reference"], check=True, capture_output=True, text=True
).stdout
live_root = subprocess.run(
    ["gh", "--help"], check=True, capture_output=True, text=True
).stdout
expected_nodes = reference_nodes(reference, root_help)
live_nodes = reference_nodes(live_reference, live_root)
for path in sorted(set(expected_nodes) | set(live_nodes)):
    assert path in expected_nodes and path in live_nodes, (
        " ".join(path) or "gh",
        "command differs from installed gh",
    )
    assert expected_nodes[path]["aliases"] == live_nodes[path]["aliases"], (
        " ".join(path) or "gh",
        "aliases differ from installed gh",
        expected_nodes.get(path),
        live_nodes.get(path),
    )
for path in sorted(path for path, node in expected_nodes.items() if node["children"]):
    group = " ".join(path)
    fixture = fixture_root / (
        "root.txt" if not group else "groups/" + group.replace(" ", "-") + ".txt"
    )
    expected = help_flags(fixture.read_text())
    live = help_flags(
        subprocess.run(
            ["gh", *group.split(), "--help"], check=True, capture_output=True, text=True
        ).stdout
    )
    for flag in sorted(expected.keys() | live.keys()):
        assert expected.get(flag) == live.get(flag), (
            group or "gh",
            flag,
            expected.get(flag),
            live.get(flag),
        )
    expected_nodes[path]["flags"] = expected
    live_nodes[path]["flags"] = live


def compare_nodes(expected, actual, path="gh"):
    for field in ("name", "aliases", "flags"):
        assert expected[field] == actual.get(field), (
            path,
            field,
            expected[field],
            actual.get(field),
        )
    expected_children = {node["name"]: node for node in expected["children"]}
    actual_children = {node["name"]: node for node in actual.get("children", [])}
    assert expected_children.keys() == actual_children.keys(), (
        path,
        "children",
        sorted(expected_children),
        sorted(actual_children),
    )
    for name, child in expected_children.items():
        compare_nodes(child, actual_children[name], path + " " + name)


compare_nodes(expected_nodes[()], tree)
compare_nodes(live_nodes[()], tree)
