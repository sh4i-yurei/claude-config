# Claude configuration work

Project note: [[Research tooling]], [[Vault system]]
Buildlog: [[research-tooling-log]], [[vault-system-log]]

Read the active project's note and open buildlog before editing. Stay within
the selected specification; ask before changing Claude's other tools or
rules. Use the Research tooling tests once that project provides them.
`.github/workflows/ci.yml` runs CI on every push and pull request. The nested
`skills/humanizer` package has its own validation workflow and is outside
Research tooling unless the spec names it.

Read `ARCHITECTURE.md` before changing anything. This checkout is live: `~/.claude` links into
it, so build in the worktree the handoff names, never by switching branches here. Run the tests
with `python3 -m pytest -q -p no:cacheprovider && bats tests/shell && git diff --check`.
