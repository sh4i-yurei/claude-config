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

# Ansible vault lookup review, round 1

## Request

Review the vault lookup item in `~/Documents/worktrees/infra-vault-lookup` on
`fix/vault-lookup` against [[2026-10-28-claude-to-codex-ansible-vault-lookup]],
the decisions it cites in [[Ansible configuration management]], and the repository's
`ARCHITECTURE.md`. The pushed commit is
`24609d1d7abbd3945f6efb62f98bb1978424f165`. Issue:
`sh4i-yurei/keepbreathing-infra #74`. The green CI run is
https://github.com/sh4i-yurei/keepbreathing-infra/actions/runs/40820977655.
The worktree `~/Documents/worktrees/infra-b1` and its branch
`feat/hub-backup-disk` are for another item; ignore them.

The changed files are `ansible/lookup_plugins/vault_secret.py`, `ansible/ansible.cfg`,
`ansible/group_vars/all.yml`, `ansible/group_vars/droplets.yml`,
`ansible/host_vars/vaultserv.yml`, `ansible/playbooks/become-password.yml`, the four
hub task files and eight hub templates named in the build handoff, `ansible/tests/test_vault_secret.py`,
`ansible/tests/expected_vault_render.json`, `ansible/tests/test_journal_pull_edges.py`,
`pyproject.toml`, `.mutation-survivors.yml`, and `ARCHITECTURE.md`.

Before deciding any finding's severity, check it against every TEST CASES bullet in
the build handoff. A finding that shows a stated case is broken is blocking, however
small it looks. A design chosen because it was quicker to build, or a problem fixed
by stacking patches, is also blocking. Confirm with `gh run view` that the CI URL is
green and ran on the stated SHA; otherwise treat that as blocking. Check each touched
piece against what `ARCHITECTURE.md` says it must and must not do. Check for invented
APIs, flags, configuration keys, imports, and document references at the pinned version;
each is blocking. Treat a test that pins an implementation detail instead of behavior
as a defect. Compare the buildlog's entry with the code and real output.

Return a verdict and findings marked blocking or non-blocking, with file, line and
evidence. For each finding, set `breaks_test_case` to the exact TEST CASES bullet it
breaks, or `none`. The verdict is `pass` when no finding is blocking.

The final local check ran from `ansible/` with:

```sh
set -euo pipefail
ansible-lint -q
for playbook in playbooks/*.yml; do ansible-playbook --syntax-check "$playbook"; done
python3 -m pytest -q ../ansible/tests
```

It printed no lint findings, named all eight playbooks in syntax checks, and ended:

```
238 passed, 1 skipped in 7.58s
```

The complete local mutation run finished `1959/1959` mutants. Nine surviving lookup
mutants have behavior-based explanations in `.mutation-survivors.yml`. No live
playbook ran; Claude owns that check after review.

## Response

```json
{"repo":"sh4i-yurei/keepbreathing-infra","issue":74,"item":"Agents can run the playbooks again","verdict":"changes_required","cost":1.7264467999999997,"findings":[{"severity":"blocking","breaks_test_case":"WHEN mutmut run --max-children 10 finishes on the plugin, THEN every surviving mutant of ansible/lookup_plugins/vault_secret.py is killed by a test through the lookup's public behaviour or explained in .mutation-survivors.yml under testing-standard rule 4. Local.","file":".mutation-survivors.yml","line":111,"summary":"The explanation for survivor mutmut_116 is false, and a test through the lookup's public behaviour can kill that mutant, so rule 4 does not allow it to be explained.","evidence":"`mutmut show ...run__mutmut_116` prints the change `- if isinstance(fields, list)` / `+ if (isinstance(fields, list)) or True` (vault_secret.py lines 81-88). The recorded reason says a non-list fields value raises 'the same public error' on both paths. That is wrong when the item has no \"fields\" key, or has \"fields\": null. Under the mutant, the comprehension iterates over None and raises TypeError('NoneType' object is not iterable) instead of AnsibleLookupError. Ansible then reports a different exception class and message, which is a change anyone running the play can see. The Bitwarden CLI leaves the fields key out of the JSON for an item with no custom fields, so this is a realistic input. A test calling field='hash' on an item with no \"fields\" key, and asserting AnsibleLookupError naming the item and the field, kills the mutant. No such test exists: test_missing_or_duplicate_field only uses fields=[] and a duplicated pair. Fix it by adding that test and removing the 116 entry."},{"severity":"non_blocking","breaks_test_case":"none","file":"ansible/playbooks/become-password.yml","line":20,"summary":"The rescue task swaps the plugin's error for a hand-written copy of it, so the session source never reaches the person running the playbook. The copy also quotes the item name differently from the plugin.","evidence":"The set_fact has no_log: true, which censors the plugin's AnsibleLookupError, so the rescue prints its own message: `Vault lookup failed for item {{ ... | to_json }}; run vu.` Because become-password.yml runs first in every playbook, this is the message seen whenever a session is stale. It leaves out 'using inherited BW_SESSION' or 'using runtime session file', which decision 53 point 6 promises at the level of the run ('the run fails and says which source it used'). The message format now exists in two places, and the two quote differently: the plugin uses Python repr with single quotes (`item 'keepbreath0 sudo (hub)'`) and the rescue uses JSON double quotes. Both test cases for the play still pass. Given the one-call-per-host and no_log constraints, this probably needs an Open question rather than a code fix."},{"severity":"non_blocking","breaks_test_case":"none","file":"ansible/tests/test_vault_secret.py","line":198,"summary":"The missing-field case removes every field from the item, so it never checks the 'nor any other field's value' part of its test case.","evidence":"test_missing_or_duplicate_field is parametrized with fields=[] for the missing case. The item then has no other field values that could leak, and only pw-hub-1 is checked. The code does not leak these values, but the test would not notice if it did. A fixture with only a token field (value token-1) that also asserts token-1 is absent would cover the stated case. In the same way, test_missing_login_username checks pw-hub-1 and HASH but not token-1."},{"severity":"non_blocking","breaks_test_case":"none","file":"ansible/tests/test_vault_secret.py","line":519,"summary":"The render comparison runs on a hand-built Jinja2 environment with re-implemented filters, not Ansible's own templating, so it shows equivalence under that harness rather than under Ansible.","evidence":"_environment() defines quote, from_json, items2dict, to_json and bool itself; for example, `bool` is Python's bool, so bool('false') is True. I re-rendered all 15 files from origin/main and from the branch through render_vault_file. Every file matched expected_vault_render.json, so the stored baseline is genuine and the conversion holds under this harness. A template that relies on Ansible-specific filter behaviour could pass here and still differ in a live run. The live --check --diff run is the remaining proof."},{"severity":"non_blocking","breaks_test_case":"none","file":"ansible/tests/test_vault_secret.py","line":89,"summary":"The direct-call helper plants a fake ansible.lookup_plugins package inside the installed ansible package for the rest of the pytest session, and the fixture also adds an unused directory to the global lookup_loader.","evidence":"call() writes sys.modules['ansible.lookup_plugins'] and sets ansible.lookup_plugins = namespace, so that mutmut's path-based module name matches; the buildlog's 04:46 entry explains why. The approach works and still goes through PluginLoader and run(). However, it changes global interpreter state, and line 85's lookup_loader.add_directory(...) is left over from the earlier design: no test uses the global loader in-process. A comment or a fixture-scoped teardown would keep it from surprising the next test author."},{"severity":"non_blocking","breaks_test_case":"none","file":"ARCHITECTURE.md","line":82,"summary":"The ansible/tests/ row still says it owns tests for the filter plugins and role scripts only. It now also holds the lookup plugin tests and a test that runs ansible-playbook.","evidence":"Row text: 'Python tests for the filter plugins and the scripts in role `files/` folders...'. test_vault_secret.py adds tests that call the lookup directly, two-host plays run through ansible-playbook on local connections, and a render-equivalence snapshot (expected_vault_render.json). The handoff did not ask for this row to change, so this is drift rather than a broken requirement."}]}
```

Round 1 verdict: changes required. Cost: $1.7264467999999997.

- blocking: The explanation for survivor mutmut_116 is false, and a test through the lookup's public behaviour can kill that mutant, so rule 4 does not allow it to be explained. Breaks test case: WHEN mutmut run --max-children 10 finishes on the plugin, THEN every surviving mutant of ansible/lookup_plugins/vault_secret.py is killed by a test through the lookup's public behaviour or explained in .mutation-survivors.yml under testing-standard rule 4. Local.
- non_blocking: The rescue task swaps the plugin's error for a hand-written copy of it, so the session source never reaches the person running the playbook. The copy also quotes the item name differently from the plugin. Breaks test case: none
- non_blocking: The missing-field case removes every field from the item, so it never checks the 'nor any other field's value' part of its test case. Breaks test case: none
- non_blocking: The render comparison runs on a hand-built Jinja2 environment with re-implemented filters, not Ansible's own templating, so it shows equivalence under that harness rather than under Ansible. Breaks test case: none
- non_blocking: The direct-call helper plants a fake ansible.lookup_plugins package inside the installed ansible package for the rest of the pytest session, and the fixture also adds an unused directory to the global lookup_loader. Breaks test case: none
- non_blocking: The ansible/tests/ row still says it owns tests for the filter plugins and role scripts only. It now also holds the lookup plugin tests and a test that runs ansible-playbook. Breaks test case: none
