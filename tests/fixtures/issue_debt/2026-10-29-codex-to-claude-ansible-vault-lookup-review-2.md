---
type: note
from: codex
to: claude
state: done
project: "[[Ansible configuration management]]"
created: 2026-10-29
answered: 2026-10-29
tags: [handoff]
---

# Ansible vault lookup review, round 2

## Request

Review the round 1 blocking fix in `~/Documents/worktrees/infra-vault-lookup` on
`fix/vault-lookup`, plus regressions from that fix. The original build handoff is
[[2026-10-28-claude-to-codex-ansible-vault-lookup]] and the round 1 verdict is
[[2026-10-29-codex-to-claude-ansible-vault-lookup-review-1]]. The pushed commit
is `a8012780cd2a8c8fc567aaf2a5bca014f3aed4aa`, in
`sh4i-yurei/keepbreathing-infra` issue 74. The green CI run is
https://github.com/sh4i-yurei/keepbreathing-infra/actions/runs/40823115360.
Ignore `~/Documents/worktrees/infra-b1` and `feat/hub-backup-disk`, which belong to
another item.

Only `ansible/tests/test_vault_secret.py` and `.mutation-survivors.yml` changed
since round 1. The new test calls the lookup with a fake item lacking `fields` and
asserts the full fixed `AnsibleLookupError`. The explanation for mutant 116 was
removed. The focused test passed with `1 passed, 39 deselected in 0.24s`. The
complete local mutation run finished `1959/1959`, killed `1879`, and left eight
lookup survivors explained in `.mutation-survivors.yml`; mutant 116 no longer
survives. The final local check ran from `ansible/`:

```sh
set -euo pipefail
ansible-lint -q
for playbook in playbooks/*.yml; do ansible-playbook --syntax-check "$playbook"; done
python3 -m pytest -q ../ansible/tests
```

Lint printed no findings, syntax checks named all eight playbooks, and pytest
ended `239 passed, 1 skipped in 7.50s`.

Verify the round 1 blocking finding's fix and check for regressions against
the original handoff's TEST CASES and the repository's `ARCHITECTURE.md`. Before
deciding severity, check each finding against every TEST CASES bullet. A finding
that breaks a stated case is blocking, however small it looks. A design chosen
because it was quicker to build, or a problem fixed by stacking patches, is
blocking. Check for invented APIs, flags, configuration keys, imports or document
references at the pinned version; each is blocking. Treat a test that pins an
implementation detail instead of behavior as a defect. Check the buildlog against
the code and real output. Confirm with `gh run view` that the CI URL is green and
ran on the stated SHA; otherwise treat that as blocking.

Return a verdict and findings marked blocking or non-blocking, with file, line
and evidence. For each finding, set `breaks_test_case` to the exact TEST CASES
bullet it breaks, or `none`. Pass when no finding is blocking.

## Response

```json
{"repo":"sh4i-yurei/keepbreathing-infra","issue":74,"item":"Agents can run the playbooks again","verdict":"pass","cost":0.8292735999999999,"findings":[{"severity":"non_blocking","breaks_test_case":"none","file":"ansible/tests/test_vault_secret.py","line":221,"summary":"The new test covers an item with no \"fields\" key, but not the \"fields\": null input that the round 1 finding also named. The plugin handles both inputs through the same isinstance check, and mutant 116 is killed either way.","evidence":"test_field_lookup_when_item_omits_fields drops the fields key and asserts the full message \"Vault lookup failed for item 'keepbreath0 sudo (hub)' field 'hash' using runtime session file; run vu.\" The plugin at vault_secret.py lines 80-89 sends any non-list fields value to an empty match list. Rerunning `mutmut run --max-children 10 'ansible.lookup_plugins.vault_secret.xǁLookupModuleǁrun__mutmut_116'` reports it killed. A second parameter with \"fields\": None would make the test match the finding's wording, but no stated case depends on it."}]}
```

Round 2 verdict: pass. Cost: $0.8292735999999999.

- non_blocking: The new test does not separately cover `"fields": null`; the missing-key test kills mutant 116 and no stated case depends on the null input. Breaks test case: none.
