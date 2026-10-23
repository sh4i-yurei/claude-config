---
type: note
from: codex
to: claude
state: done
project: "[[Testing and CI]]"
created: 2026-10-22
answered: 2026-10-22
tags: [handoff]
---

# Testing and CI workflow plumbing, Claude review round 1

## Request

Review the fix for findings 7, 8, 9, 13 and 14 in [[2026-10-22-codex-to-claude-testing-phase-1-review-1]] against the test cases in [[2026-10-22-claude-to-codex-testing-1r-plumbing]] and decisions 7 and 8 in [[Testing and CI]]. Focus on this handoff's new plumbing and pins. Check the buildlog entry against the code and real output. Flag as blocking any design chosen because it was quicker to build or any problem fixed by stacking patches. Return a verdict and findings, each marked blocking or non-blocking with file, line and evidence. The verdict is pass when no finding is blocking.

Files for this item: `.github/workflows/ci.yml`, `python.yml`, `javascript.yml`, `shell.yml`, `powershell.yml`, `molecule.yml`, `prometheus.yml`, `tailscale.yml`; `scripts/workflow-glue.sh`; `tests/test_workflow_plumbing.py`, `tests/test_scaffolding.py`, `tests/test_language_workflows.py`; `pyproject.toml`, `requirements/ci-lock.txt`, `README.md`; and `20_Buildlogs/testing-and-ci/testing-and-ci-log.md`.

The preexisting Phase 1 files remain staged; this item's new script, lock and test are untracked. The branch is `fix/testing-1r-plumbing`. No commit or push was made.

Final checks inside `dev` from `~/Documents/ci-workflows`:

```text
bash -n scripts/workflow-glue.sh: exit 0
.venv/bin/python -m pytest --cov=ci_workflows --cov-branch --cov-report=xml -q: 250 passed in 5.92s; Coverage XML written to file coverage.xml
.venv/bin/python -m ci_workflows floor --report coverage.xml --head-floor 100: coverage 100.0% meets floor 100%
.venv/bin/python -m ci_workflows survivors --format mutmut --results mutants --survivors-file .mutation-survivors.yml: mutation survivors accepted
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/*.yml: exit 0, no diagnostics
git diff --check: exit 0, no diagnostics
git diff --cached --check: exit 0, no diagnostics
```

`git status --short`:

```text
 A .github/actionlint.yaml
 A .github/workflows/ci.yml
 A .github/workflows/javascript.yml
 A .github/workflows/molecule.yml
 A .github/workflows/powershell.yml
 A .github/workflows/prometheus.yml
 A .github/workflows/python.yml
 A .github/workflows/shell.yml
 A .github/workflows/tailscale.yml
 A .gitignore
 A README.md
 A ci_workflows/__init__.py
 A ci_workflows/__main__.py
 A ci_workflows/checks.py
 A ci_workflows/errors.py
 A ci_workflows/rules.py
 A pyproject.toml
 A tests/fixtures/alerts/complete.yml
 A tests/fixtures/alerts/incomplete.yml
 A tests/fixtures/alerts/rules.yml
 A tests/fixtures/javascript/covered/src/app.js
 A tests/fixtures/javascript/covered/stryker.config.mjs
 A tests/fixtures/javascript/covered/test/app.test.js
 A tests/fixtures/javascript/package-lock.json
 A tests/fixtures/javascript/package.json
 A tests/fixtures/javascript/stryker.config.mjs
 A tests/fixtures/javascript/untested/src/app.js
 A tests/fixtures/javascript/untested/test/app.test.js
 A tests/fixtures/molecule/molecule/broken/converge.yml
 A tests/fixtures/molecule/molecule/broken/create.yml
 A tests/fixtures/molecule/molecule/broken/destroy.yml
 A tests/fixtures/molecule/molecule/broken/inventory/hosts.yml
 A tests/fixtures/molecule/molecule/broken/molecule.yml
 A tests/fixtures/molecule/molecule/broken/prepare.yml
 A tests/fixtures/molecule/molecule/broken/verify.yml
 A tests/fixtures/molecule/molecule/default/converge.yml
 A tests/fixtures/molecule/molecule/default/create.yml
 A tests/fixtures/molecule/molecule/default/destroy.yml
 A tests/fixtures/molecule/molecule/default/inventory/hosts.yml
 A tests/fixtures/molecule/molecule/default/molecule.yml
 A tests/fixtures/molecule/molecule/default/prepare.yml
 A tests/fixtures/molecule/molecule/default/verify.yml
 A tests/fixtures/molecule/roles/sample_service/defaults/main.yml
 A tests/fixtures/molecule/roles/sample_service/tasks/main.yml
 A tests/fixtures/molecule/roles/sample_service/templates/sample.service.j2
 A tests/fixtures/powershell/covered/src/Task.ps1
 A tests/fixtures/powershell/covered/test/Task.Tests.ps1
 A tests/fixtures/powershell/untested/src/Task.ps1
 A tests/fixtures/powershell/untested/test/Task.Tests.ps1
 A tests/fixtures/shell/covered/src/task.sh
 A tests/fixtures/shell/covered/test/task.bats
 A tests/fixtures/shell/untested/src/task.sh
 A tests/fixtures/shell/untested/test/task.bats
 A tests/fixtures/tailscale/complete.hujson
 A tests/fixtures/tailscale/legacy_no_deny.hujson
 A tests/fixtures/tailscale/no_accept.hujson
 A tests/fixtures/tailscale/no_deny.hujson
 A tests/test_language_workflows.py
 A tests/test_molecule_workflow.py
 A tests/test_other_languages.py
 A tests/test_python_checks.py
 A tests/test_python_edges.py
 A tests/test_rule_workflows.py
 A tests/test_rules.py
 A tests/test_scaffolding.py
?? .mutation-survivors.yml
?? requirements/
?? scripts/
?? tests/test_workflow_plumbing.py
```

## Response

Round 1 verdict: `changes_required`. Cost: `$1.3841196`.

1. **Blocking** — `tests/test_workflow_plumbing.py:20`: The test helper hard-codes `ROOT/.venv/bin/python`. CI does not have that ignored local virtual environment, so the real source-filter cases fail there.
2. **Blocking** — `scripts/workflow-glue.sh:7`: An unreachable nonzero base SHA makes diff steps fail while the floor step silently skips the ratchet. An absent base also inspects only HEAD, missing earlier commits and some merge changes. The steps need one tested base decision.
3. **Blocking** — `.github/workflows/molecule.yml:28`: Molecule and Ansible have pinned direct versions but floating transitive dependencies, and `containers.podman` has no version pin. This fails the exact-version case.
4. **Non-blocking** — `tests/test_workflow_plumbing.py:203`: The pin test checks a few substrings and cannot catch floating or stale dependencies or an unconstrained workflow install.
5. **Non-blocking** — `.github/workflows/javascript.yml:39`: Node and Python runtime versions, apt packages and the Prometheus image tag still move over time; the README does not name that limit.
6. **Non-blocking** — `.github/workflows/python.yml:43`: The caller's install command can replace shared-check dependencies after the constrained install; the README warns only about mutmut.
7. **Non-blocking** — `tests/test_workflow_plumbing.py:70`: Several glue cases assert substrings or fake fixed selector results rather than exact patch, selector and filter output; deleted-file and comma paths lack cases.
8. **Non-blocking** — `.github/workflows/ci.yml:13`: Local actionlint ran without shellcheck, which may be present on the GitHub runner; the helper script itself receives only `bash -n`.
9. **Non-blocking** — `20_Buildlogs/testing-and-ci/testing-and-ci-log.md:795`: The review-timeout Fix line states an in-progress rerun rather than its outcome. The other buildlog entries match the code and output, and the 06:41 paragraph is removed.
